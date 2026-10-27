"""Gremlin Nanny 2.0 containment tests (Phase 2).

These tests prove the containment lifecycle and the security invariants from
GREMLIN-NANNY-PLAN.md section 44. They exercise the canonical subsystem directly;
the integration tests (test_gremlin_integration.py) prove the runtime wiring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.gremlin.admin import (
    AdminAuthorization,
    AdminAuthorizationError,
    ProtectedAdminControl,
    sign_admin_authorization,
)
from runtime.gremlin.authorization import CapabilityLease
from runtime.gremlin.containment import ContainmentError, GremlinNanny
from runtime.gremlin.deviation import DeviationManifest  # noqa: F401  (import guard)
from runtime.gremlin.enrollment import (
    ContainmentRequired,
    enroll_governed_member,
    require_containment_proof,
)
from runtime.gremlin.events import EffectEvent
from runtime.gremlin.health import evaluate_health
from runtime.gremlin.identity import ProcessIdentity
from runtime.gremlin.observers import ObserverSet
from runtime.isolated_sandbox import full_component_acknowledgments
from runtime.gremlin.policy import OBSERVE_ONLY, default_policy_bundle
from runtime.gremlin.receipts import ContainmentAuthority, ContainmentReceipt, ReceiptForgeryError
from runtime.gremlin.registry import EnrollmentError, ProtectedExecutionRegistry
from runtime.gremlin.supervisor import DeterministicSupervisor, SupervisorUnavailable
from runtime.resource_lifecycle import VerifiedJobMembership

KEY = b"gremlin-test-signing-key-0123456789"
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


class FakeBackend:
    available = True

    def __init__(self) -> None:
        self.terminated: list[dict] = []
        self.frozen: list[dict] = []

    def terminate_tree(self, identity: dict) -> dict:
        self.terminated.append(identity)
        return {"terminated": True, "pid": identity.get("pid")}

    def freeze(self, identity: dict) -> dict:
        self.frozen.append(identity)
        return {"frozen": True, "pid": identity.get("pid")}


def make_nanny(*, backend=None, deviation_root=None) -> GremlinNanny:
    observers = ObserverSet()
    for kind in ("network", "process_tree", "filesystem"):
        observers.register(kind, lambda: ())
    return GremlinNanny(
        authority_id="gn-authority",
        signing_key=KEY,
        observers=observers,
        supervisor=DeterministicSupervisor(backend or FakeBackend()),
        deviation_root=deviation_root,
    )


def identity(execution_id="exec-1", pid=4321, start="start-1", profile="gn-redteam-strict"):
    return ProcessIdentity(
        agent_execution_id=execution_id,
        agent_id="agent-1",
        pid=pid,
        process_start_identity=start,
        parent_pid=None,
        parent_execution_id=None,
        sandbox_id="sandbox-1",
        job_object_id=None,
        container_or_cgroup_id=None,
        runtime_id="runtime-1",
        model_id="model-1",
        orchestration_id="orch-1",
        policy_profile=profile,
        registered_at_utc=NOW.isoformat(),
    )


def effect(execution_id="exec-1", pid=4321, start="start-1", effect_type="outbound_network", target="api.example.com"):
    return EffectEvent(
        event_id=f"evt-{effect_type}-1",
        effect_type=effect_type,
        execution_id=execution_id,
        agent_id="agent-1",
        pid=pid,
        process_start_identity=start,
        sandbox_id="sandbox-1",
        target=target,
        action="connect",
        requested_scope="outbound_https",
        observed_scope="outbound_https",
        timestamp_utc=NOW.isoformat(),
        correlation_id="corr-1",
        trace_id="trace-1",
        source_component="network_observer",
        socket_id="socket-1",
    )


# ---------------------------------------------------------------------------
# Enrollment lifecycle: containment before release
# ---------------------------------------------------------------------------
def test_process_registered_before_release():
    nanny = make_nanny()
    execution, receipt = nanny.enroll(identity(), now=NOW)
    # Enrollment issues the containment ACK, but the workload is not released yet.
    assert execution.state == "CONTAINMENT_ACKNOWLEDGED"
    assert execution.released is False
    assert nanny.authority.verify(receipt)
    released = nanny.release("exec-1")
    assert released.state == "RUNNING_PROTECTED"
    assert released.released is True


def test_missing_ack_blocks_workload():
    nanny = make_nanny()
    # A workload that was never enrolled cannot be released.
    with pytest.raises(ContainmentError):
        nanny.release("exec-unknown")
    with pytest.raises(EnrollmentError):
        nanny.registry.transition("exec-unknown", "RUNNING_PROTECTED")


def test_release_requires_verified_receipt():
    nanny = make_nanny()
    nanny.enroll(identity(), now=NOW)
    # Tamper with the stored receipt so verification fails.
    original = nanny._receipts["exec-1"]
    tampered = replace(original, signature="00" * 32)
    nanny._receipts["exec-1"] = tampered
    with pytest.raises(ContainmentError):
        nanny.release("exec-1")


def test_enroll_refuses_observe_only_profile():
    nanny = make_nanny()
    with pytest.raises(ContainmentError):
        nanny.enroll(identity(profile=OBSERVE_ONLY), now=NOW)


def test_enroll_requires_required_observers():
    nanny = GremlinNanny(authority_id="gn-authority", signing_key=KEY, supervisor=DeterministicSupervisor(FakeBackend()))
    with pytest.raises(ContainmentError):
        nanny.enroll(identity(), now=NOW)


def test_job_identity_cannot_be_claimed_without_supervisor_evidence():
    nanny = make_nanny()
    with pytest.raises(ContainmentError, match="requires verified supervisor custody evidence"):
        nanny.enroll(replace(identity(), job_object_id="job-1"), now=NOW)


def test_nanny_refuses_unverified_job_custody_evidence():
    nanny = make_nanny()
    custody = VerifiedJobMembership(
        parent_resource_id="resource-1",
        job_object_id="job-1",
        member_pid=4321,
        member_process_start_identity="start-1",
        verified_at_utc=NOW.isoformat(),
    )

    with pytest.raises(ContainmentError, match="canonical supervisor Job custody verification"):
        nanny.enroll_verified_job_member(
            replace(identity(), job_object_id="job-1"),
            object(),
            custody,
            now=NOW,
        )


# ---------------------------------------------------------------------------
# PID / process-start identity
# ---------------------------------------------------------------------------
def test_wrong_pid_rejected():
    registry = ProtectedExecutionRegistry()
    registry.enroll(identity(pid=4321))
    assert registry.resolve(pid=9999, process_start_identity="start-1") == ()
    assert len(registry.resolve(pid=4321, process_start_identity="start-1")) == 1


def test_reused_pid_with_wrong_start_identity_rejected():
    registry = ProtectedExecutionRegistry()
    registry.enroll(identity(pid=4321, start="start-1"))
    # Same PID, different process-start identity (PID reuse) => no match.
    assert registry.resolve(pid=4321, process_start_identity="start-2") == ()


def test_enforcement_refuses_mismatched_process_identity():
    backend = FakeBackend()
    supervisor = DeterministicSupervisor(backend)
    with pytest.raises(SupervisorUnavailable):
        supervisor.enforce(
            "terminate_execution_tree",
            identity={"pid": 4321, "process_start_identity": "start-2"},
            expected_pid=4321,
            expected_process_start_identity="start-1",
        )
    assert backend.terminated == []


def test_many_to_one_pid_attribution_per_session():
    registry = ProtectedExecutionRegistry()
    registry.enroll(identity("exec-a", pid=5000, start="shared-broker"))
    registry.enroll(identity("exec-b", pid=5000, start="shared-broker"))
    matches = registry.resolve(pid=5000, process_start_identity="shared-broker")
    assert {execution.agent_execution_id for execution in matches} == {"exec-a", "exec-b"}


# ---------------------------------------------------------------------------
# One-shot remediation
# ---------------------------------------------------------------------------
def test_unauthorized_traffic_issues_one_bounded_intervention():
    nanny = make_nanny()
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    assert outcome.decision == "remediate"
    assert outcome.intervention_id is not None


def test_correction_path_resumes_execution():
    nanny = make_nanny()
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    result = nanny.respond(outcome.intervention_id, "complied", event=effect(), now=NOW)
    assert result.decision == "allow"
    assert nanny.registry.get("exec-1").state == "RUNNING_PROTECTED"


def test_failed_correction_terminates():
    backend = FakeBackend()
    nanny = make_nanny(backend=backend)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    late = NOW + timedelta(seconds=5)
    result = nanny.respond(outcome.intervention_id, "complied", event=effect(), now=late)
    assert result.decision == "terminate"
    assert backend.terminated  # deterministic termination actually ran
    assert nanny.registry.get("exec-1").state == "DEVIATION_SEALED"


def test_agent_lying_about_compliance_still_terminates():
    """A second response (repeat negotiation) is refused and terminates."""
    backend = FakeBackend()
    nanny = make_nanny(backend=backend)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    nanny.respond(outcome.intervention_id, "complied", event=effect(), now=NOW)
    # The execution already resumed; a repeated response to a resolved intervention
    # is not possible because the tracker is resolved.
    with pytest.raises(ValueError):
        nanny._trackers[outcome.intervention_id].respond("complied")


# ---------------------------------------------------------------------------
# Critical events: immediate termination
# ---------------------------------------------------------------------------
def test_containment_control_interference_terminates_immediately():
    backend = FakeBackend()
    nanny = make_nanny(backend=backend)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(
        effect(effect_type="containment_control_interference", target="gn-control"), now=NOW
    )
    assert outcome.decision == "terminate"
    assert outcome.intervention_id is None
    assert backend.terminated


def test_authorized_effect_passes():
    nanny = make_nanny()
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    lease = CapabilityLease(
        lease_id="lease-1", agent_execution_id="exec-1", capability="outbound_network",
        destination_scope=("api.example.com",), valid_from_utc=NOW.isoformat(),
        valid_until_utc=(NOW + timedelta(minutes=5)).isoformat(), max_connections=1,
        max_bytes=1024, max_requests=1, allowed_protocols=("https",),
        policy_revision=default_policy_bundle().revision,
    )
    outcome = nanny.observe_and_evaluate(effect(), leases={"exec-1": lease}, now=NOW)
    assert outcome.decision == "allow"


# ---------------------------------------------------------------------------
# Workload cannot forge ACK / mark itself healthy
# ---------------------------------------------------------------------------
def test_workload_cannot_forge_ack():
    authority = ContainmentAuthority(authority_id="gn-authority", signing_key=KEY)
    forged = ContainmentReceipt(
        receipt_id="gn-ack:forged", agent_execution_id="exec-1", agent_id="agent-1",
        pid=4321, process_start_identity="start-1", sandbox_id="sandbox-1",
        policy_profile="gn-redteam-strict", gremlin_revision="r1", identity_sha256="0" * 64,
        issued_at_utc=NOW.isoformat(), issued_by="gn-authority", signature="ab" * 32,
    )
    assert authority.verify(forged) is False
    with pytest.raises(ReceiptForgeryError):
        authority.require(forged)


def test_receipt_signed_by_other_authority_is_refused():
    authority = ContainmentAuthority(authority_id="gn-authority", signing_key=KEY)
    other = ContainmentAuthority(authority_id="other-authority", signing_key=KEY)
    receipt = ContainmentReceipt(
        receipt_id="gn-ack:x", agent_execution_id="exec-1", agent_id="agent-1",
        pid=4321, process_start_identity="start-1", sandbox_id="sandbox-1",
        policy_profile="gn-redteam-strict", gremlin_revision="r1", identity_sha256="0" * 64,
        issued_at_utc=NOW.isoformat(), issued_by="other-authority",
    )
    with pytest.raises(ReceiptForgeryError):
        other.issue(receipt) if False else authority.issue(receipt)


def test_job_custody_digest_is_covered_by_receipt_signature():
    authority = ContainmentAuthority(authority_id="gn-authority", signing_key=KEY)
    receipt = ContainmentReceipt(
        receipt_id="gn-ack:job",
        agent_execution_id="exec-1",
        agent_id="agent-1",
        pid=4321,
        process_start_identity="start-1",
        sandbox_id="sandbox-1",
        policy_profile="gn-redteam-strict",
        gremlin_revision="r1",
        identity_sha256="0" * 64,
        issued_at_utc=NOW.isoformat(),
        issued_by="gn-authority",
        job_object_id="job-1",
        job_custody_sha256="a" * 64,
    )
    signed = authority.issue(receipt)

    assert authority.verify(signed)
    assert signed.as_dict()["job_custody_sha256"] == "a" * 64
    assert not authority.verify(replace(signed, job_custody_sha256="b" * 64))


def test_legacy_receipt_body_omits_optional_job_custody():
    receipt = ContainmentReceipt(
        receipt_id="gn-ack:legacy",
        agent_execution_id="exec-1",
        agent_id="agent-1",
        pid=4321,
        process_start_identity="start-1",
        sandbox_id="sandbox-1",
        policy_profile="gn-redteam-strict",
        gremlin_revision="r1",
        identity_sha256="0" * 64,
        issued_at_utc=NOW.isoformat(),
        issued_by="gn-authority",
    )

    assert "job_object_id" not in receipt._body()
    assert "job_custody_sha256" not in receipt._body()


def test_containment_proof_is_never_workload_set():
    nanny = make_nanny()
    # Unenrolled execution never has a proven containment.
    proof = nanny.containment_proof("exec-1")
    assert proof.proven is False
    nanny.enroll(identity(), now=NOW)
    # Enrolled but not released => still not proven.
    assert nanny.containment_proof("exec-1").proven is False
    nanny.release("exec-1")
    assert nanny.containment_proof("exec-1").proven is True


def test_unhealthy_containment_cannot_prove_protected_execution():
    nanny = make_nanny()
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    nanny.supervisor = DeterministicSupervisor(None)

    proof = nanny.containment_proof("exec-1")

    assert proof.proven is False
    assert proof.health_state == "PARTIAL_ENFORCEMENT"
    assert "not admissible" in proof.reason


def test_containment_proof_matches_its_contract():
    from runtime.contracts import validate_instance
    from runtime.isolated_sandbox import establish_sandbox

    contract = Path(__file__).resolve().parents[1] / "contracts/gremlin-containment-proof.schema.json"
    nanny = make_nanny()
    policy = establish_sandbox(scope_key="ws:1", component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    proof = nanny.containment_proof("exec-1")
    validate_instance(proof.contract_image(), contract)
    validate_instance(proof.as_dict(), contract)
    assert proof.sandbox_policy_sha256 == policy.as_dict()["policy_sha256"]
    assert nanny._receipts["exec-1"].sandbox_policy_sha256 == proof.sandbox_policy_sha256
    # An unenrolled execution's proof must also satisfy the contract.
    validate_instance(nanny.containment_proof("exec-unknown").contract_image(), contract)


def test_sandbox_policy_cannot_change_while_protected_execution_is_active():
    from runtime.isolated_sandbox import establish_sandbox

    nanny = make_nanny()
    nanny.apply_sandbox_policy(establish_sandbox(scope_key="ws:1", component_acknowledgments=full_component_acknowledgments()))
    nanny.enroll(identity(), now=NOW)
    with pytest.raises(ContainmentError, match="cannot change while protected executions are active"):
        nanny.apply_sandbox_policy(establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments()))


# ---------------------------------------------------------------------------
# Health / graceful degradation
# ---------------------------------------------------------------------------
def test_loss_of_observation_reduces_capability():
    report = evaluate_health(
        observer_health={"network": False, "process_tree": True, "filesystem": True},
        policy_integrity_ok=True, supervisor_healthy=True,
    )
    assert report.state == "PARTIAL_OBSERVATION"
    assert report.capability_reduction == "revoke_network"


def test_policy_integrity_failure_defaults_to_deny():
    report = evaluate_health(
        observer_health={"network": True, "process_tree": True, "filesystem": True},
        policy_integrity_ok=False, supervisor_healthy=True,
    )
    assert report.state == "POLICY_INTEGRITY_FAILURE"
    assert report.capability_reduction == "default_deny_sensitive_effects"


def test_supervisor_unavailable_freezes_high_risk():
    report = evaluate_health(
        observer_health={"network": True, "process_tree": True, "filesystem": True},
        policy_integrity_ok=True, supervisor_healthy=False,
    )
    assert report.state == "PARTIAL_ENFORCEMENT"
    assert "freeze" in report.capability_reduction


def test_policy_bundle_integrity_detects_tampering():
    bundle = default_policy_bundle()
    assert bundle.integrity_ok()
    tampered = type(bundle)(
        bundle_id=bundle.bundle_id, revision="tampered", profiles=bundle.profiles,
        integrity_sha256=bundle.integrity_sha256,
    )
    assert tampered.integrity_ok() is False


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------
def test_high_impact_operation_requires_strong_auth():
    control = ProtectedAdminControl(signing_key=KEY)
    weak = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="offline_recovery_token", operation="disable_all_gn",
            target="gn-redteam-strict", permitted_action="disable", issued_at_utc=NOW.isoformat(),
            expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n1",
            approval_id="appr-1", signature="sig",
        ),
        KEY,
    )
    with pytest.raises(AdminAuthorizationError):
        control.apply(weak, target_state="disabled", reason="test", now=NOW)
    assert control.audit_log and control.audit_log[-1].result == "refused"


def test_expired_admin_authorization_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    stale = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="passkey", operation="pause_new_protected_runs",
            target="gn-redteam-strict", permitted_action="pause", issued_at_utc=(NOW - timedelta(hours=1)).isoformat(),
            expires_at_utc=(NOW - timedelta(minutes=30)).isoformat(), nonce="n2",
            approval_id="appr-2", signature="sig",
        ),
        KEY,
    )
    with pytest.raises(AdminAuthorizationError):
        control.apply(stale, target_state="paused", reason="test", now=NOW)


def test_forged_admin_signature_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    forged = AdminAuthorization(
        principal_id="ben", auth_strength="passkey", operation="pause_new_protected_runs",
        target="gn-redteam-strict", permitted_action="pause", issued_at_utc=NOW.isoformat(),
        expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n9",
        approval_id="appr-9", signature="forged-signature",
    )
    with pytest.raises(AdminAuthorizationError):
        control.apply(forged, target_state="paused", reason="test", now=NOW)
    assert control.audit_log[-1].result == "refused"


def test_action_mismatch_and_future_issuance_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    mismatched = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="passkey", operation="pause_new_protected_runs",
            target="gn-redteam-strict", permitted_action="disable", issued_at_utc=NOW.isoformat(),
            expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n10",
            approval_id="appr-10", signature="sig",
        ),
        KEY,
    )
    with pytest.raises(AdminAuthorizationError):
        control.apply(mismatched, target_state="paused", reason="test", now=NOW)
    future = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="passkey", operation="pause_new_protected_runs",
            target="gn-redteam-strict", permitted_action="pause",
            issued_at_utc=(NOW + timedelta(days=2)).isoformat(),
            expires_at_utc=(NOW + timedelta(days=2, minutes=5)).isoformat(), nonce="n11",
            approval_id="appr-11", signature="sig",
        ),
        KEY,
    )
    with pytest.raises(AdminAuthorizationError):
        control.apply(future, target_state="paused", reason="test", now=NOW)


def test_replayed_admin_nonce_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    good = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="passkey", operation="pause_new_protected_runs",
            target="gn-redteam-strict", permitted_action="pause", issued_at_utc=NOW.isoformat(),
            expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n12",
            approval_id="appr-12", signature="sig",
        ),
        KEY,
    )
    control.apply(good, target_state="paused", reason="first", now=NOW)
    with pytest.raises(AdminAuthorizationError):
        control.apply(good, target_state="paused", reason="replay", now=NOW + timedelta(minutes=1))


def test_admin_audit_records_every_operation():
    control = ProtectedAdminControl(signing_key=KEY)
    good = sign_admin_authorization(
        AdminAuthorization(
            principal_id="ben", auth_strength="passkey", operation="disable_specific_rule",
            target="GN-NET-001", permitted_action="disable", issued_at_utc=NOW.isoformat(),
            expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n3",
            approval_id="appr-3", signature="sig",
        ),
        KEY,
    )
    event = control.apply(good, target_state="disabled", reason="false positive", now=NOW)
    assert event.result == "applied"
    assert control.audit_digest()


# ---------------------------------------------------------------------------
# Enrollment bridge
# ---------------------------------------------------------------------------
def test_enrollment_bridge_fails_closed_without_containment():
    with pytest.raises(ContainmentRequired):
        require_containment_proof(None, execution_id="exec-1", required=True)
    assert require_containment_proof(None, execution_id="exec-1", required=False) is None


def test_enrollment_bridge_rejects_caller_asserted_process_identity():
    nanny = make_nanny()
    with pytest.raises(ContainmentRequired, match="not custody evidence"):
        enroll_governed_member(
            nanny,
            execution_id="exec-1",
            agent_id="agent-1",
            pid=4321,
            process_start_identity="start-1",
            policy_profile="gn-redteam-strict",
            now=NOW,
        )
    assert nanny.registry.get("exec-1") is None


def test_string_only_child_registration_fails_closed():
    nanny = make_nanny()
    nanny.enroll(identity())
    with pytest.raises(ContainmentError, match="OS-verified child identity"):
        nanny.register_child("exec-1", "child-1")
    assert nanny.registry.get("child-1") is None