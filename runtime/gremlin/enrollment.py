"""Containment enrollment bridge for governed execution.

This module binds a governed execution (a model-group member or an agent run) to a
Gremlin-protected process identity and requires a verified containment receipt
*before* the workload is released. It is the wiring seam between the runtime
execution owners and the Gremlin containment facade.

Design constraints:

* The **host/group owner** drives enrollment, never the member executor or the
  workload. A member executor cannot enroll itself, forge a receipt, or mark
  itself healthy.
* Containment is required only when the caller declares it required; when it is
  required and unavailable, enrollment fails closed (``ContainmentRequired``).
* The bridge exposes the resulting :class:`ContainmentProof` so a branch
  attestation can cite ``containment_proven`` from a real, verified receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .containment import ContainmentProof, GremlinNanny
from .identity import ProcessIdentity
from ..resource_lifecycle import ResourceManager, VerifiedJobMembership

SCHEMA_VERSION = "px.gremlin-enrollment-bridge/1.0"


class ContainmentRequired(RuntimeError):
    """Raised when containment is required but could not be established.

    The governed execution must fail closed: a branch without proven containment
    stays NOT_ADMITTED rather than running unprotected.
    """


@dataclass(frozen=True, slots=True)
class EnrollmentBinding:
    agent_execution_id: str
    execution_id: str
    containment_receipt_id: str
    containment_proof: ContainmentProof
    gremlin_revision: str
    process_identity: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_execution_id": self.agent_execution_id,
            "execution_id": self.execution_id,
            "containment_receipt_id": self.containment_receipt_id,
            "gremlin_revision": self.gremlin_revision,
            "containment_proven": self.containment_proof.proven,
            "process_identity": dict(self.process_identity),
        }


def process_identity_for(
    *,
    execution_id: str,
    agent_id: str,
    pid: int,
    process_start_identity: str,
    policy_profile: str,
    model_id: str | None = None,
    parent_execution_id: str | None = None,
    parent_pid: int | None = None,
    sandbox_id: str | None = None,
    job_object_id: str | None = None,
    runtime_id: str | None = None,
    orchestration_id: str | None = None,
    now: datetime | None = None,
) -> ProcessIdentity:
    """Build the durable process identity for a governed execution."""
    moment = now or datetime.now(timezone.utc)
    return ProcessIdentity(
        agent_execution_id=execution_id,
        agent_id=agent_id,
        pid=pid,
        process_start_identity=process_start_identity,
        parent_pid=parent_pid,
        parent_execution_id=parent_execution_id,
        sandbox_id=sandbox_id,
        job_object_id=job_object_id,
        container_or_cgroup_id=None,
        runtime_id=runtime_id,
        model_id=model_id,
        orchestration_id=orchestration_id,
        policy_profile=policy_profile,
        registered_at_utc=moment.isoformat(),
    )


def enroll_governed_member(*_args: object, **_kwargs: object) -> EnrollmentBinding:
    """Reject caller-asserted PIDs; use a supervisor-verified enrollment path."""
    _ = (_args, _kwargs)
    raise ContainmentRequired(
        "caller-supplied PID and process-start values are not custody evidence; "
        "use enroll_supervised_process or enroll_supervised_child"
    )


def enroll_supervised_process(
    nanny: GremlinNanny,
    resource_manager: ResourceManager,
    custody: VerifiedJobMembership,
    *,
    execution_id: str,
    agent_id: str,
    policy_profile: str,
    model_id: str | None = None,
    runtime_id: str | None = None,
    orchestration_id: str | None = None,
    now: datetime | None = None,
) -> EnrollmentBinding:
    """Enroll a suspended supervisor-owned Windows process before it resumes.

    This helper is intended for the supervisor's pre-release callback. It does
    not resume the process; returning successfully permits the supervisor to do so.
    """
    if (
        type(resource_manager) is not ResourceManager
        or type(custody) is not VerifiedJobMembership
    ):
        raise ContainmentRequired("OS-verified supervisor Job custody is required")
    try:
        verified = resource_manager.verify_owned_job(custody.parent_resource_id)
    except Exception as error:
        raise ContainmentRequired(
            f"supervisor-owned process custody could not be reverified: {error}"
        ) from error
    if (
        verified.job_object_id != custody.job_object_id
        or verified.member_pid != custody.member_pid
        or verified.member_process_start_identity != custody.member_process_start_identity
    ):
        raise ContainmentRequired("supervised process custody changed before enrollment")
    custody = verified
    identity = process_identity_for(
        execution_id=execution_id,
        agent_id=agent_id,
        pid=custody.member_pid,
        process_start_identity=custody.member_process_start_identity,
        policy_profile=policy_profile,
        job_object_id=custody.job_object_id,
        runtime_id=runtime_id,
        model_id=model_id,
        orchestration_id=orchestration_id,
        now=now,
    )
    try:
        _, receipt = nanny.enroll_verified_job_member(
            identity, resource_manager, custody, now=now
        )
        if not nanny.authority.verify(receipt):
            raise ContainmentRequired("containment receipt failed verification")
        if receipt.job_custody_sha256 != custody.custody_sha256:
            raise ContainmentRequired("containment receipt does not bind the verified Job evidence")
        nanny.release(execution_id)
        proof = nanny.containment_proof(execution_id)
        if not proof.proven:
            raise ContainmentRequired("containment proof is not established after release")
    except ContainmentRequired:
        raise
    except Exception as error:  # noqa: BLE001 - fail closed on any enrollment failure
        raise ContainmentRequired(f"supervised process enrollment failed: {error}") from error
    return EnrollmentBinding(
        agent_execution_id=execution_id,
        execution_id=execution_id,
        containment_receipt_id=receipt.receipt_id,
        containment_proof=proof,
        gremlin_revision=nanny.gremlin_revision,
        process_identity=identity.as_dict(),
    )


def enroll_supervised_child(
    nanny: GremlinNanny,
    resource_manager: ResourceManager,
    *,
    parent_execution_id: str,
    parent_resource_id: str,
    child_execution_id: str,
    child_pid: int,
    agent_id: str,
    policy_profile: str,
    model_id: str | None = None,
    runtime_id: str | None = None,
    orchestration_id: str | None = None,
    now: datetime | None = None,
) -> EnrollmentBinding:
    """Enroll and link a live child proven inside its parent's retained Job."""
    if type(resource_manager) is not ResourceManager:
        raise ContainmentRequired("canonical ResourceManager Job custody owner is required")
    parent = nanny.registry.get(parent_execution_id)
    if parent is None or parent.state != "RUNNING_PROTECTED":
        raise ContainmentRequired("child enrollment requires a running protected parent")
    try:
        custody = resource_manager.verify_job_member(parent_resource_id, child_pid)
        if parent.identity.job_object_id != custody.job_object_id:
            raise ContainmentRequired(
                "child Job membership does not match the protected parent's containment Job"
            )
        identity = process_identity_for(
            execution_id=child_execution_id,
            agent_id=agent_id,
            pid=custody.member_pid,
            process_start_identity=custody.member_process_start_identity,
            policy_profile=policy_profile,
            parent_execution_id=parent_execution_id,
            parent_pid=parent.identity.pid,
            job_object_id=custody.job_object_id,
            runtime_id=runtime_id,
            model_id=model_id,
            orchestration_id=orchestration_id,
            now=now,
        )
        _, receipt = nanny.enroll_verified_job_member(
            identity, resource_manager, custody, now=now
        )
        if not nanny.authority.verify(receipt):
            raise ContainmentRequired("child containment receipt failed verification")
        if receipt.job_custody_sha256 != custody.evidence_sha256:
            raise ContainmentRequired("child receipt does not bind the verified Job evidence")
        nanny.registry.register_verified_child(
            parent_execution_id, child_execution_id, custody
        )
        nanny.release(child_execution_id)
        proof = nanny.containment_proof(child_execution_id)
        if not proof.proven:
            raise ContainmentRequired("child containment proof is not established after release")
    except ContainmentRequired:
        raise
    except Exception as error:  # noqa: BLE001 - fail closed on any enrollment failure
        raise ContainmentRequired(f"verified child enrollment failed: {error}") from error
    return EnrollmentBinding(
        agent_execution_id=child_execution_id,
        execution_id=child_execution_id,
        containment_receipt_id=receipt.receipt_id,
        containment_proof=proof,
        gremlin_revision=nanny.gremlin_revision,
        process_identity=identity.as_dict(),
    )


def enroll_suspended_supervised_child(
    nanny: GremlinNanny, resource_manager: ResourceManager, custody: VerifiedJobMembership,
    *, parent_execution_id: str, parent_resource_id: str,
    child_execution_id: str, agent_id: str, policy_profile: str,
    model_id: str | None = None, runtime_id: str | None = None,
    orchestration_id: str | None = None, now: datetime | None = None,
) -> EnrollmentBinding:
    """Supervisor callback: parent Job assignment, enrollment and ACK before resume.

    This function never resumes. The canonical supervisor owns that final step.
    A running-child reference cannot enter this boundary.
    """
    if type(resource_manager) is not ResourceManager or type(custody) is not VerifiedJobMembership:
        raise ContainmentRequired("suspended child requires canonical supervisor custody")
    parent = nanny.registry.get(parent_execution_id)
    if parent is None or parent.state != "RUNNING_PROTECTED":
        raise ContainmentRequired("suspended child requires a protected parent execution")
    actual_parent = resource_manager.verify_owned_job(parent_resource_id)
    if (parent.identity.pid != actual_parent.member_pid
            or parent.identity.process_start_identity != actual_parent.member_process_start_identity
            or parent.identity.job_object_id != actual_parent.job_object_id):
        raise ContainmentRequired("parent execution differs from live supervisor custody")
    actual_child = resource_manager.verify_owned_job(custody.parent_resource_id)
    if (actual_child.member_pid != custody.member_pid
            or actual_child.member_process_start_identity != custody.member_process_start_identity
            or actual_child.job_object_id != custody.job_object_id):
        raise ContainmentRequired("child custody changed before enrollment")
    membership = resource_manager.attach_suspended_child(parent_resource_id, custody.parent_resource_id)
    if membership.member_process_start_identity != custody.member_process_start_identity:
        raise ContainmentRequired("child process identity changed during parent Job assignment")
    return enroll_supervised_child(nanny, resource_manager,
        parent_execution_id=parent_execution_id, parent_resource_id=parent_resource_id,
        child_execution_id=child_execution_id, child_pid=membership.member_pid,
        agent_id=agent_id, policy_profile=policy_profile, model_id=model_id,
        runtime_id=runtime_id, orchestration_id=orchestration_id, now=now)


def require_containment_proof(
    nanny: GremlinNanny | None,
    *,
    execution_id: str,
    required: bool,
) -> ContainmentProof | None:
    """Return the containment proof for an execution, or fail closed.

    When ``required`` is True and containment is absent or unproven, raise
    :class:`ContainmentRequired`. When not required, return ``None`` (the branch
    will be recorded NOT_ADMITTED by convergence).
    """
    if nanny is None:
        if required:
            raise ContainmentRequired("containment is required but no Gremlin Nanny is configured")
        return None
    proof = nanny.containment_proof(execution_id)
    if required and not proof.proven:
        raise ContainmentRequired("containment is required but not proven: " + proof.reason)
    return proof