"""Gremlin Nanny containment facade — the single enrollment/evaluation API.

This is the canonical entrypoint the rest of PX uses. It ties the discrete
components together into the required lifecycle::

    assignment
      -> generation/execution identity
      -> exact PID/process-start identity
      -> Gremlin registration
      -> process-tree registration
      -> isolated monitor registration
      -> containment/network ACK
      -> workload release

and the runtime enforcement pipeline::

    event observed -> evaluate -> (allow | one-shot intervention | terminate)
                                   -> deviation package -> analysis pending

Containment control is isolated from workload control: the facade owns the
registry, the policy bundle, the observers and the enforcement supervisor. The
workload never receives a handle that lets it mutate any of them, forge a receipt,
or mark itself healthy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..json_io import bounded_canonical_json_bytes
from .admin import ProtectedAdminControl
from .authorization import AuthorizationResolution, CapabilityLease, resolve_authorization
from .deviation import DeviationManifest, DeviationPackage
from .events import EffectEvent
from .health import HealthReport, evaluate_health
from .identity import ProcessIdentity
from .intervention import Intervention, InterventionTracker
from .observers import ObserverSet
from .policy import OBSERVE_ONLY, PolicyBundle, default_policy_bundle
from .receipts import ContainmentAuthority, ContainmentReceipt
from .registry import EnrollmentError, ProtectedExecution, ProtectedExecutionRegistry
from .runtime_identity import GremlinRuntimeIdentityStore, RuntimeIdentityMetadata
from .supervisor import DeterministicSupervisor, SupervisorUnavailable
from ..resource_lifecycle import ResourceManager, VerifiedJobMembership

SCHEMA_VERSION = "px.gremlin-containment/1.0"


class ContainmentError(ValueError):
    """Raised when a containment requirement is not met (fail closed)."""


@dataclass(frozen=True, slots=True)
class ContainmentProof:
    """The per-execution containment proof exposed into ExecutionContext.

    ``proven`` is True only when a verified containment receipt exists for the
    exact identity tuple. It is the value a branch attestation cites for
    ``containment_proven``; it is never set by the workload.
    """

    agent_execution_id: str
    proven: bool
    receipt_id: str | None
    gremlin_revision: str
    identity_sha256: str
    health_state: str
    reason: str
    sandbox_policy_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return self.contract_image()

    def contract_image(self) -> dict[str, object]:
        """The exact image validated by contracts/gremlin-containment-proof.schema.json."""
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_execution_id": self.agent_execution_id,
            "proven": self.proven,
            "receipt_id": self.receipt_id,
            "gremlin_revision": self.gremlin_revision,
            "identity_sha256": self.identity_sha256 or ("0" * 64),
            "health_state": self.health_state,
            "reason": self.reason,
            "sandbox_policy_sha256": self.sandbox_policy_sha256,
            "authority_granted": False,
        }


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    event_id: str
    decision: str
    decision_category: str
    intervention_id: str | None
    enforcement_action: str | None
    deviation_id: str | None
    containment_success: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        # Slotted dataclasses expose no ``__dict__``; asdict() covers every
        # decision variant (G09: serialization must never crash).
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


class GremlinNanny:
    """The canonical containment control plane instance."""

    def __init__(
        self,
        *,
        authority_id: str,
        signing_key: bytes | None = None,
        runtime_identity_store: GremlinRuntimeIdentityStore | None = None,
        runtime_identity: RuntimeIdentityMetadata | None = None,
        policy: PolicyBundle | None = None,
        observers: ObserverSet | None = None,
        supervisor: DeterministicSupervisor | None = None,
        deviation_root: Path | None = None,
    ) -> None:
        self.policy = policy or default_policy_bundle()
        if not self.policy.integrity_ok():
            raise ContainmentError("policy bundle integrity check failed")
        if runtime_identity_store is None and runtime_identity is None:
            self.authority = ContainmentAuthority(
                authority_id=authority_id,
                signing_key=signing_key,
            )
        elif runtime_identity_store is None or runtime_identity is None:
            raise ContainmentError(
                "local runtime identity store and metadata must be supplied together"
            )
        else:
            try:
                self.authority = ContainmentAuthority.from_runtime_identity(
                    authority_id=authority_id,
                    identity_store=runtime_identity_store,
                    identity=runtime_identity,
                )
            except (RuntimeError, ValueError) as error:
                raise ContainmentError(
                    "local Gremlin runtime identity is unavailable"
                ) from error
        self.observers = observers or ObserverSet()
        self.supervisor = supervisor or DeterministicSupervisor()
        self.registry = ProtectedExecutionRegistry()
        self.admin = ProtectedAdminControl(
            signing_key=signing_key
            if signing_key
            else self.authority.signing_key()
        )
        self.deviation_root = Path(deviation_root) if deviation_root else None
        self._receipts: dict[str, ContainmentReceipt] = {}
        self._trackers: dict[str, InterventionTracker] = {}
        self._tracker_events: dict[str, EffectEvent] = {}
        self._revoked_leases: set[str] = set()
        #: Durable-in-memory atomic budget accounting per lease id (G01).
        self._budget_ledger: dict[str, dict[str, int]] = {}
        self.gremlin_revision = self.policy.computed_integrity_sha256
        #: Optional Isolated Agent Sandbox policy this containment instance enforces.
        self.sandbox_policy = None
        self.sandbox_policy_sha256: str | None = None

    def apply_sandbox_policy(self, policy: object) -> None:
        """Configure this containment instance from an Isolated Agent Sandbox policy.

        The sandbox mode does not create a second monitor: it *configures* this
        canonical containment instance. When the mode is ON, the network
        enforcement allowlist becomes the sandbox allowlist and the control plane
        is read-only to governed agents. When OFF, containment behaves normally.
        """
        from ..isolated_sandbox import SandboxPolicy, sandbox_policy_from_dict

        if type(policy) is not SandboxPolicy:
            raise ContainmentError("canonical typed sandbox policy required")
        validated = sandbox_policy_from_dict(policy.as_dict())
        policy_sha256 = validated.as_dict()["policy_sha256"]
        if self.registry.active() and policy_sha256 != self.sandbox_policy_sha256:
            raise ContainmentError(
                "sandbox policy cannot change while protected executions are active"
            )
        self.sandbox_policy = validated
        self.sandbox_policy_sha256 = policy_sha256

    @property
    def sandbox_active(self) -> bool:
        return bool(getattr(self.sandbox_policy, "active", False))

    def control_plane_writable_by(self, principal: str) -> bool:
        """Whether a principal may mutate the containment control plane.

        While sandbox mode is ON the control plane is read-only to governed
        agents (GN-INV-002 / sandbox requirement 3). Only the containment
        authority and an authenticated administrator may mutate it.
        """
        if principal in {"containment_authority", self.authority.authority_id}:
            return True
        if self.sandbox_active:
            return False
        return principal == "administrator"

    # ------------------------------------------------------------------
    # Lifecycle: enrollment before release
    # ------------------------------------------------------------------
    def enroll(
        self,
        identity: ProcessIdentity,
        *,
        now: datetime | None = None,
    ) -> tuple[ProtectedExecution, ContainmentReceipt]:
        """Register a protected execution and issue its containment ACK.

        This is the *pre-release* step: the caller must not release the workload
        until the returned receipt is verified. The receipt is issued only after
        the policy profile is resolved and the required observers for that profile
        are registered.
        """
        return self._enroll(identity, now=now, custody_evidence=None)

    def enroll_verified_job_member(
        self,
        identity: ProcessIdentity,
        resource_manager: ResourceManager,
        custody: VerifiedJobMembership,
        *,
        now: datetime | None = None,
    ) -> tuple[ProtectedExecution, ContainmentReceipt]:
        """Re-query the canonical OS custody owner before signing Job evidence."""
        if (
            type(resource_manager) is not ResourceManager
            or type(custody) is not VerifiedJobMembership
            or identity.job_object_id is None
        ):
            raise ContainmentError("canonical supervisor Job custody verification is required")
        try:
            verified = (
                resource_manager.verify_job_member(custody.parent_resource_id, identity.pid)
                if identity.parent_execution_id is not None
                else resource_manager.verify_owned_job(custody.parent_resource_id)
            )
        except Exception as error:
            raise ContainmentError(
                f"supervisor Job custody could not be reverified: {error}"
            ) from error
        if (
            custody.parent_resource_id != verified.parent_resource_id
            or custody.job_object_id != verified.job_object_id
            or custody.member_pid != verified.member_pid
            or custody.member_process_start_identity != verified.member_process_start_identity
            or identity.pid != verified.member_pid
            or identity.process_start_identity != verified.member_process_start_identity
            or identity.job_object_id != verified.job_object_id
        ):
            raise ContainmentError("process identity does not match reverified Job custody evidence")
        return self._enroll(identity, now=now, custody_evidence=verified)

    def _enroll(
        self,
        identity: ProcessIdentity,
        *,
        now: datetime | None,
        custody_evidence: VerifiedJobMembership | None,
    ) -> tuple[ProtectedExecution, ContainmentReceipt]:
        moment = now or datetime.now(timezone.utc)
        if identity.job_object_id is not None and custody_evidence is None:
            raise ContainmentError("Job Object identity requires verified supervisor custody evidence")
        profile = self.policy.profile(identity.policy_profile)
        if profile.name == OBSERVE_ONLY:
            raise ContainmentError("gn-observe-only is not real containment and cannot enroll")
        required = []
        if profile.network_enforcement:
            required.append("network")
        if profile.process_tree_enforcement:
            required.append("process_tree")
        if profile.filesystem_enforcement:
            required.append("filesystem")
        missing = [kind for kind in required if kind not in self.observers.observers]
        if missing:
            raise ContainmentError(
                "cannot enroll: required observers are not registered: " + ",".join(missing)
            )
        execution = self.registry.enroll(identity)
        receipt = ContainmentReceipt(
            receipt_id="gn-ack:" + hashlib.sha256(
                (identity.agent_execution_id + identity.identity_sha256).encode("utf-8")
            ).hexdigest()[:32],
            agent_execution_id=identity.agent_execution_id,
            agent_id=identity.agent_id,
            pid=identity.pid,
            process_start_identity=identity.process_start_identity,
            sandbox_id=identity.sandbox_id,
            policy_profile=identity.policy_profile,
            gremlin_revision=self.gremlin_revision,
            identity_sha256=identity.identity_sha256,
            issued_at_utc=moment.isoformat(),
            issued_by=self.authority.authority_id,
            sandbox_policy_sha256=self.sandbox_policy_sha256,
            job_object_id=identity.job_object_id,
            job_custody_sha256=(
                custody_evidence.custody_sha256 if custody_evidence is not None else None
            ),
        )
        receipt = self.authority.issue(receipt)
        self._receipts[identity.agent_execution_id] = receipt
        self.registry.acknowledge_containment(identity.agent_execution_id, receipt.receipt_id)
        return self.registry.get(identity.agent_execution_id), receipt

    def release(self, agent_execution_id: str) -> ProtectedExecution:
        """Release the workload after containment acknowledgment.

        Fails closed if the execution is not enrolled or has no verified receipt.
        """
        execution = self.registry.get(agent_execution_id)
        if execution is None:
            raise ContainmentError("cannot release: execution is not enrolled")
        receipt = self._receipts.get(agent_execution_id)
        if receipt is None or not self.authority.verify(receipt):
            raise ContainmentError("cannot release: no verified containment acknowledgment")
        return self.registry.transition(agent_execution_id, "RUNNING_PROTECTED")

    def register_child(self, parent_execution_id: str, child_execution_id: str) -> ProtectedExecution:
        """Reject ID-only child references until OS custody evidence is wired."""
        try:
            self.registry.register_child(parent_execution_id, child_execution_id)
        except EnrollmentError as error:
            raise ContainmentError(str(error)) from error
        raise ContainmentError("child enrollment did not produce a containment proof")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self, *, deviation_writer_available: bool = True, telemetry_trusted: bool = True) -> HealthReport:
        return evaluate_health(
            observer_health=self.observers.health.as_dict(),
            policy_integrity_ok=self.policy.integrity_ok(),
            supervisor_healthy=self.supervisor.healthy,
            deviation_writer_available=deviation_writer_available,
            telemetry_trusted=telemetry_trusted,
        )

    def close_supervised_execution(self, execution_id: str, resource_manager, resource_id: str) -> None:
        """Invalidate enrollment only after the canonical host has settled custody."""
        from ..resource_lifecycle import ResourceManager
        if type(resource_manager) is not ResourceManager:
            raise ContainmentError("canonical supervisor resource manager required")
        execution = self.registry.get(execution_id)
        if execution is None:
            raise ContainmentError("protected execution is not registered")
        resource_manager.verify_closed_owned_process(resource_id, pid=execution.identity.pid,
            process_identity=execution.identity.process_start_identity)
        if execution.state not in {"TERMINATED", "DEVIATION_SEALED", "ANALYSIS_PENDING"}:
            self.registry.transition(execution_id, "TERMINATED")

    def containment_proof(self, agent_execution_id: str) -> ContainmentProof:
        """Return the containment proof for one execution (never workload-set).

        Proven requires a verified receipt AND that the execution was released
        under that containment. An acknowledged-but-not-yet-released execution is
        not yet proven, and a terminated execution is never proven.
        """
        execution = self.registry.get(agent_execution_id)
        if execution is None:
            return ContainmentProof(
                agent_execution_id, False, None, self.gremlin_revision, "",
                "OFFLINE", "execution is not enrolled", self.sandbox_policy_sha256,
            )
        receipt = self._receipts.get(agent_execution_id)
        verified = receipt is not None and self.authority.verify(receipt)
        sandbox_policy_matches = bool(
            receipt is not None
            and receipt.sandbox_policy_sha256 == self.sandbox_policy_sha256
        )
        state = execution.state
        health = self.health()
        proven = bool(
            verified
            and sandbox_policy_matches
            and execution.released
            and state not in {"TERMINATED", "DEVIATION_SEALED"}
            and health.safe_for_high_risk
        )
        if proven:
            reason = "verified containment receipt and admissible containment health"
        elif not health.safe_for_high_risk:
            reason = "containment health is not admissible: " + health.state
        elif not sandbox_policy_matches:
            reason = "sandbox policy differs from the policy bound to the containment receipt"
        else:
            reason = "no verified containment receipt for a released execution"
        return ContainmentProof(
            agent_execution_id,
            proven,
            receipt.receipt_id if receipt else None,
            self.gremlin_revision,
            execution.identity.identity_sha256,
            health.state,
            reason,
            receipt.sandbox_policy_sha256 if receipt is not None else self.sandbox_policy_sha256,
        )

    # ------------------------------------------------------------------
    # Observation -> evaluation -> enforcement
    # ------------------------------------------------------------------
    def observe_and_evaluate(
        self,
        event: EffectEvent,
        *,
        leases: Mapping[str, CapabilityLease] | None = None,
        allowances: Mapping[str, str] | None = None,
        expected_effects: frozenset[str] = frozenset(),
        justification: str | None = None,
        now: datetime | None = None,
    ) -> EvaluationOutcome:
        """Evaluate one observed effect and enforce the policy decision.

        The workload cannot call this to clear itself: evaluation consumes the
        *observed* event and the externally-held leases/allowances. A protected
        execution that is not enrolled is refused.
        """
        execution = self.registry.get(event.execution_id)
        if execution is None:
            raise ContainmentError("observed effect belongs to an unenrolled execution (fail closed)")
        if not execution.released:
            raise ContainmentError("execution was not released under containment (fail closed)")
        # G03: the observed event must carry the complete enrolled process tuple.
        # Caller-populated fields are never accepted as proof of origin.
        identity = execution.identity
        observed = (
            event.agent_id,
            event.pid,
            event.process_start_identity,
            event.sandbox_id,
        )
        enrolled = (
            identity.agent_id,
            identity.pid,
            identity.process_start_identity,
            identity.sandbox_id,
        )
        if observed != enrolled:
            raise ContainmentError(
                "observed effect process identity does not match the enrolled tuple (fail closed)"
            )
        self.registry.transition(event.execution_id, "EVALUATING")
        # Isolated Agent Sandbox: for a governed external network effect, the
        # sandbox policy is authoritative. An authorization the enforcement layer
        # cannot prove is a denial (fail closed); an unauthorized connection is a
        # termination when the sandbox policy says so.
        if self.sandbox_active and event.effect_type in {"outbound_network", "external_api", "dns", "raw_socket"}:
            from ..isolated_sandbox import decide_connection

            policy = self.sandbox_policy
            # Authorization is known only if an external allowance/lease proves it.
            known = None
            allowance_id_sandbox = (allowances or {}).get(f"{event.effect_type}:{event.target}")
            lease = (leases or {}).get(event.execution_id)
            if allowance_id_sandbox is not None:
                known = True
            else:
                from .authorization import lease_denial_reason, trusted_utc

                moment = trusted_utc(now)
                denial = lease_denial_reason(
                    lease,
                    event,
                    capability=event.effect_type,
                    now=moment,
                    revoked_lease_ids=self._revoked_leases,
                    current_policy_revision=self.policy.revision,
                    budget_ledger=self._budget_ledger,
                )
                if denial is not None:
                    known = False
                    decision_reason = "lease not authoritative: " + denial
                elif lease is not None and (
                    policy.network_policy.permits(event.target)
                    or not lease.destination_scope
                    or event.target in lease.destination_scope
                ):
                    known = True
                else:
                    known = False
                    decision_reason = "endpoint not in sandbox allowlist or lease scope"
            decision = decide_connection(policy, event.target, known_authorized=known)
            if decision.permitted:
                self._consume_budget(lease)
                self.registry.transition(event.execution_id, "RUNNING_PROTECTED")
                return EvaluationOutcome(event.event_id, "allow", "expected_authorized", None, None, None, True, decision.reason)
            if decision.enforcement_action == "terminate_execution_tree":
                return self._terminate(event, None, now=now, detail="sandbox: " + decision.reason)
            # Denied without termination: record the refusal, stay running.
            self.registry.transition(event.execution_id, "RUNNING_PROTECTED")
            return EvaluationOutcome(event.event_id, "deny", "unexpected_unauthorized", None, "deny", None, False, decision.reason)
        profile = self.policy.profile(execution.identity.policy_profile)
        resolution: AuthorizationResolution = resolve_authorization(
            event,
            profile=profile,
            leases=leases,
            allowances=allowances,
            expected_effects=expected_effects,
            justification=justification,
            now=now,
            revoked_lease_ids=self._revoked_leases,
            current_policy_revision=self.policy.revision,
            budget_ledger=self._budget_ledger,
        )
        if resolution.final_decision == "allow":
            self._consume_budget((leases or {}).get(event.execution_id))
            self.registry.transition(event.execution_id, "RUNNING_PROTECTED")
            return EvaluationOutcome(event.event_id, "allow", resolution.decision_category, None, None, None, True, "authorized effect")
        if resolution.final_decision == "terminate":
            return self._terminate(event, resolution, now=now)
        # remediate: one bounded corrective attempt.
        rule = profile.rule_for(event.effect_type)
        assert rule is not None
        self.registry.transition(event.execution_id, "INTERVENTION")
        intervention = Intervention(
            intervention_id="gn-int:" + hashlib.sha256(
                (event.execution_id + "\0" + event.event_id).encode("utf-8")
            ).hexdigest()[:32],
            event_id=event.event_id,
            agent_execution_id=event.execution_id,
            violation_type=resolution.decision_category,
            required_action=rule.remediation_action,
            required_target=event.target,
            deadline_ms=rule.remediation_timeout_ms,
            allowed_response=("complied", "already_closed", "authorized_exception_reference"),
            max_response_count=1,
            failure_action=rule.failure_action,
        )
        tracker = InterventionTracker(intervention=intervention)
        tracker.issue(now=now)
        # Insert-only tracker registry: a colliding id from a different execution
        # can never overwrite an existing tracker (G04).
        if intervention.intervention_id in self._trackers:
            raise ContainmentError("intervention identity collision (fail closed)")
        self._trackers[intervention.intervention_id] = tracker
        self._tracker_events[intervention.intervention_id] = event
        return EvaluationOutcome(
            event.event_id, "remediate", resolution.decision_category,
            intervention.intervention_id, None, None, False, "one bounded corrective opportunity issued",
        )

    def respond(
        self,
        intervention_id: str,
        response: str,
        *,
        event: EffectEvent,
        leases: Mapping[str, CapabilityLease] | None = None,
        allowances: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> EvaluationOutcome:
        """Record the single allowed response to an intervention.

        Compliance resumes (or restricts) the execution; a non-compliant or
        absent response terminates it deterministically.
        """
        tracker = self._trackers.get(intervention_id)
        if tracker is None:
            raise ContainmentError("unknown intervention")
        # G02: a response is bound to the immutable intervention identity. An
        # event borrowed from another execution is rejected before any state
        # change or backend action.
        bound_event = self._tracker_events.get(intervention_id)
        if (
            bound_event is None
            or event.event_id != tracker.intervention.event_id
            or event.execution_id != tracker.intervention.agent_execution_id
            or (event.event_id, event.execution_id, event.pid, event.process_start_identity)
            != (bound_event.event_id, bound_event.execution_id, bound_event.pid, bound_event.process_start_identity)
        ):
            raise ContainmentError(
                "intervention response event does not bind the intervention (fail closed)"
            )
        execution = self.registry.get(tracker.intervention.agent_execution_id)
        if execution is None or not execution.released:
            raise ContainmentError("intervention execution is not enrolled/released (fail closed)")
        moment = now or datetime.now(timezone.utc)
        if moment >= tracker.deadline_utc:
            tracker.expire(now=moment)
            return self._terminate(event, None, now=moment, detail="remediation window elapsed")
        try:
            outcome = tracker.respond(response, now=moment)
        except ValueError:
            tracker.expire(now=tracker.deadline_utc)
            return self._terminate(event, None, now=tracker.deadline_utc, detail="invalid or repeated response")
        if outcome in {"complied", "already_closed", "authorized_exception_reference"}:
            self.registry.transition(event.execution_id, "RUNNING_PROTECTED")
            return EvaluationOutcome(event.event_id, "allow", "expected_authorized", intervention_id, None, None, True, "remediation complied")
        return self._terminate(event, None, now=moment, detail="remediation failed")

    def _terminate(
        self,
        event: EffectEvent,
        resolution: AuthorizationResolution | None,
        *,
        now: datetime | None,
        detail: str = "",
    ) -> EvaluationOutcome:
        moment = now or datetime.now(timezone.utc)
        execution = self.registry.get(event.execution_id)
        if execution is None:
            raise ContainmentError("cannot enforce against an unenrolled execution")
        # G06: only the exact owning execution can be terminated by its own event.
        identity = execution.identity
        if (
            event.execution_id != identity.agent_execution_id
            or event.pid != identity.pid
            or event.process_start_identity != identity.process_start_identity
        ):
            raise ContainmentError("termination event does not bind the enrolled execution (fail closed)")
        self.registry.transition(event.execution_id, "TERMINATING")
        profile = self.policy.profile(identity.policy_profile)
        rule = profile.rule_for(event.effect_type)
        action = rule.failure_action if rule is not None else profile.default_failure_action
        enforcement_action = action
        performed = False
        unconfirmed = False
        try:
            result = self.supervisor.enforce(
                action,
                identity=identity.as_dict(),
                expected_pid=identity.pid,
                expected_process_start_identity=identity.process_start_identity,
            )
            performed = result.performed
        except SupervisorUnavailable as error:
            detail = f"{detail}; supervisor unavailable: {error}" if detail else f"supervisor unavailable: {error}"
            performed = False
        # G06: TERMINATED requires a confirmed OS postcondition. A failed or
        # unavailable enforcement stays unconfirmed and fails closed — the
        # execution is never marked terminated without verified process exit.
        if performed:
            self.registry.transition(event.execution_id, "TERMINATED")
        else:
            unconfirmed = True
        deviation_id = self._seal_deviation(event, execution, resolution, action, performed, detail, moment)
        if performed:
            self.registry.transition(event.execution_id, "DEVIATION_SEALED")
        return EvaluationOutcome(
            event.event_id, "terminate",
            resolution.decision_category if resolution else "unexpected_unauthorized",
            None, enforcement_action, deviation_id, performed,
            (detail or "deterministic termination")
            + ("; enforcement unconfirmed: execution is not verified terminated" if unconfirmed else ""),
        )

    def _seal_deviation(
        self,
        event: EffectEvent,
        execution: ProtectedExecution,
        resolution: AuthorizationResolution | None,
        action: str,
        performed: bool,
        detail: str,
        moment: datetime,
    ) -> str | None:
        deviation_id = "gn-dev:" + hashlib.sha256(
            (event.event_id + execution.identity.identity_sha256).encode("utf-8")
        ).hexdigest()[:32]
        if self.deviation_root is None:
            return deviation_id
        manifest = DeviationManifest(
            deviation_id=deviation_id,
            created_at_utc=moment.isoformat(),
            agent_execution_id=execution.identity.agent_execution_id,
            agent_id=execution.identity.agent_id,
            process_identity_sha256=execution.identity.identity_sha256,
            trigger_type="effect_observed",
            effect_type=event.effect_type,
            severity=(resolution.decision_category if resolution else "critical"),
            gn_state=self.health().state,
            policy_profile=execution.identity.policy_profile,
            authorization_state=(resolution.final_decision if resolution else "terminate"),
            justification_state=("received" if resolution and resolution.justification_received else "absent"),
            intervention_attempted=resolution is not None and resolution.final_decision == "remediate",
            intervention_result=None,
            termination_performed=performed,
            kill_scope="protected_execution_tree",
            containment_success=performed,
            external_effect_confirmed=True,
            operator_action_required=not performed,
        )
        package = DeviationPackage(self.deviation_root, manifest)
        package.write("provenance/execution_identity.json", execution.identity.as_dict())
        package.write("gremlin_nanny/trigger.json", event.as_dict())
        package.write(
            "authority/authorization_result.json",
            resolution.as_dict() if resolution else {"final_decision": "terminate"},
        )
        package.write("decision/termination.json", {"action": action, "performed": performed, "detail": detail})
        package.seal()
        return deviation_id

    # ------------------------------------------------------------------
    # Deadline enforcement (G08): the facade itself sweeps outstanding
    # interventions whose bounded window elapsed without any client response.
    # ------------------------------------------------------------------
    def sweep_expired_interventions(self, *, now: datetime | None = None) -> tuple[EvaluationOutcome, ...]:
        """Expire every outstanding intervention past its deadline and enforce.

        Idempotent: a tracker resolved by a sweep (or a client response) is never
        enforced twice; only the owning execution of each expired intervention is
        acted on.
        """
        moment = now or datetime.now(timezone.utc)
        outcomes: list[EvaluationOutcome] = []
        for intervention_id, tracker in list(self._trackers.items()):
            if tracker.resolved:
                continue
            event = self._tracker_events.get(intervention_id)
            if event is None:
                continue
            if moment >= tracker.deadline_utc:
                tracker.expire(now=moment)
                outcomes.append(
                    self._terminate(event, None, now=moment, detail="remediation deadline elapsed without response")
                )
        return tuple(outcomes)

    def _consume_budget(self, lease: CapabilityLease | None) -> None:
        """Atomically debit the applicable budgets for an authorized effect."""
        if lease is None:
            return
        ledger = self._budget_ledger.setdefault(lease.lease_id, {"connections": 0, "requests": 0, "bytes": 0})
        ledger["connections"] += 1
        ledger["requests"] += 1

    def record_budget_consumption(self, lease: CapabilityLease, *, bytes_used: int = 0) -> None:
        """Debit byte accounting for an authorized effect (host-owned)."""
        if bytes_used < 0:
            raise ContainmentError("byte consumption must be non-negative")
        ledger = self._budget_ledger.setdefault(lease.lease_id, {"connections": 0, "requests": 0, "bytes": 0})
        ledger["bytes"] += int(bytes_used)
    def revoke_capability_lease(self, lease: CapabilityLease) -> None:
        """Revoke a capability lease. GN can revoke/narrow leases dynamically.

        Revocation is recorded in the audit log; the caller's lease map must drop
        the lease for it to take effect, which is why revocation is authoritative
        only through the containment facade.
        """
        if not lease.revocable:
            raise ContainmentError("lease is not revocable")
        self._revoked_leases.add(lease.lease_id)

    @property
    def revoked_leases(self) -> frozenset[str]:
        return frozenset(self._revoked_leases)

    # ------------------------------------------------------------------
    # Certification artifact
    # ------------------------------------------------------------------
    def containment_certification(self, *, experiment_id: str, tested_agent: str, tested_model: str,
                                  policy_profile: str) -> dict[str, Any]:
        """Produce a scoped containment certification artifact.

        This certifies a specific tested configuration and scope; it never claims
        "the model is safe".
        """
        body = {
            "schema_version": "px.gremlin-containment-certification/1.0",
            "experiment_id": experiment_id,
            "tested_agent": tested_agent,
            "tested_model": tested_model,
            "policy_profile": policy_profile,
            "GN_version": SCHEMA_VERSION,
            "gremlin_revision": self.gremlin_revision,
            "health_state": self.health().state,
            "result": "SCOPED_CONTAINMENT_ONLY",
        }
        return {**body, "certification_sha256": hashlib.sha256(bounded_canonical_json_bytes(body, max_bytes=65536)).hexdigest()}
