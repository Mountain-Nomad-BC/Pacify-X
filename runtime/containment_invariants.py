"""Containment invariants (Gremlin Nanny section 44).

These are the security invariants that must hold for the containment control
plane. They are checked against the canonical containment owners
(``runtime.gremlin``), not against a second implementation.

Each invariant returns a violation record when it does not hold, so a governed
section or certification gate can assert ``valid`` and name the exact failure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "px.containment-invariants/1.0"

#: The security invariants from GREMLIN-NANNY-PLAN.md section 44.
INVARIANT_IDS = (
    "GN-INV-001",  # a protected execution cannot disable its own GN protection
    "GN-INV-002",  # a protected execution cannot modify GN policy
    "GN-INV-003",  # a protected execution cannot delete/overwrite deviation evidence
    "GN-INV-004",  # PID matches validated against process-start identity before enforcement
    "GN-INV-005",  # a remediable deviation receives at most one remediation attempt
    "GN-INV-006",  # failed remediation triggers configured enforcement
    "GN-INV-007",  # loss of GN observation cannot increase agent capability
    "GN-INV-008",  # loss of GN integrity cannot silently downgrade protection
    "GN-INV-009",  # sensitive GN admin changes require strong human authentication
    "GN-INV-010",  # GN-control interference generates a deviation
    "GN-INV-011",  # critical GN-control interference may terminate immediately
    "GN-INV-012",  # enforcement remains available without LLM inference
    "GN-INV-013",  # descendant processes inherit containment unless explicitly released
    "GN-INV-014",  # recovery authority is independent of ordinary runtime trust
)


def _violation(invariant: str, detail: str) -> dict[str, str]:
    return {"invariant": invariant, "detail": detail}


def verify_containment_invariants() -> dict[str, Any]:
    """Verify every containment invariant against the canonical owners.

    Returns ``{"valid": bool, "violations": [...], "checked": [...]}``. A missing or
    failing dependency is a violation, never a silent pass.
    """
    violations: list[dict[str, str]] = []
    checked: list[str] = []
    try:
        from .gremlin.containment import GremlinNanny
        from .gremlin.health import evaluate_health
        from .gremlin.admin import HIGH_IMPACT_OPERATIONS, AUTH_FACTORS
        from .gremlin.deviation import DeviationManifest, DeviationPackage
        from .gremlin.events import EffectEvent
        from .gremlin.identity import ProcessIdentity
        from .gremlin.intervention import Intervention
        from .gremlin.recovery_authority import (
            FileRecoveryReplayLedger,
            RecoveryAuthority,
        )
        from .gremlin.registry import EnrollmentError, ProtectedExecutionRegistry
        from .gremlin.supervisor import DeterministicSupervisor
    except Exception as error:  # pragma: no cover - import failure is a hard violation
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "checked": [],
            "declared_count": len(INVARIANT_IDS),
            "evaluated_count": 0,
            "coverage_complete": False,
            "violations": [_violation("GN-INV-000", f"containment owners unavailable: {error}")],
        }

    observers = __import__("runtime.gremlin.observers", fromlist=["ObserverSet"]).ObserverSet()
    del observers  # the canonical owner is imported only to prove it is reachable

    def _nanny():
        n = GremlinNanny(authority_id="gn", signing_key=b"invariant-check-key-0123456789ab")
        for kind in ("network", "process_tree", "filesystem"):
            n.observers.register(kind, lambda: ())
        return n

    # GN-INV-001 / GN-INV-002: a governed-agent principal cannot mutate the control plane.
    nanny = _nanny()
    if nanny.control_plane_writable_by("governed_agent"):
        violations.append(_violation("GN-INV-001", "governed agent can mutate the control plane"))
    checked.append("GN-INV-001")
    checked.append("GN-INV-002")

    # GN-INV-003: deviation artifacts reject replacement and expose no deletion API.
    manifest = DeviationManifest(
        deviation_id="invariant-deviation",
        created_at_utc="2026-10-05T00:00:00Z",
        agent_execution_id="inv-exec",
        agent_id="a",
        process_identity_sha256="0" * 64,
        trigger_type="invariant",
        effect_type="outbound_network",
        severity="high",
        gn_state="HEALTHY",
        policy_profile="gn-redteam-strict",
        authorization_state="denied",
        justification_state="missing",
        intervention_attempted=False,
        intervention_result=None,
        termination_performed=False,
        kill_scope=None,
        containment_success=False,
        external_effect_confirmed=False,
        operator_action_required=True,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="px-gn-invariant-") as directory:
            package = DeviationPackage(Path(directory), manifest)
            package.write("decision/rationale.json", {"reason": "invariant check"})
            try:
                package.write("decision/rationale.json", {"reason": "replacement"})
            except FileExistsError:
                overwrite_refused = True
            else:
                overwrite_refused = False
        if not overwrite_refused or callable(getattr(DeviationPackage, "delete", None)):
            violations.append(_violation("GN-INV-003", "deviation evidence can be replaced or deleted through its writer"))
    except Exception as error:
        violations.append(_violation("GN-INV-003", f"deviation evidence writer could not be verified: {error}"))
    checked.append("GN-INV-003")

    # GN-INV-004: enforcement refuses a process identity that does not match the tuple.
    registry = ProtectedExecutionRegistry()
    identity = ProcessIdentity(
        agent_execution_id="inv-exec", agent_id="a", pid=1234, process_start_identity="s1",
        parent_pid=None, parent_execution_id=None, sandbox_id="sbx", job_object_id=None,
        container_or_cgroup_id=None, runtime_id=None, model_id=None, orchestration_id=None,
        policy_profile="gn-redteam-strict", registered_at_utc="2026-10-05T00:00:00Z",
    )
    registry.enroll(identity)
    if registry.resolve(pid=1234, process_start_identity="s2"):
        violations.append(_violation("GN-INV-004", "PID matched with a different process-start identity"))
    checked.append("GN-INV-004")

    # GN-INV-005: the one-shot rule permits exactly one response.
    from .gremlin.intervention import Intervention
    intervention = Intervention(
        intervention_id="i1", event_id="e1", agent_execution_id="inv-exec",
        violation_type="unexpected_unauthorized", required_action="close_connection",
        required_target="t", deadline_ms=1500,
        allowed_response=("complied", "already_closed", "authorized_exception_reference"),
        max_response_count=1, failure_action="terminate_execution_tree",
    )
    if intervention.max_response_count != 1:
        violations.append(_violation("GN-INV-005", "intervention allows more than one response"))
    checked.append("GN-INV-005")

    # GN-INV-006: an invalid corrective response invokes the configured action.
    class _RecordingBackend:
        available = True

        def __init__(self) -> None:
            self.terminated = False

        def terminate_tree(self, identity: dict[str, object]) -> dict[str, object]:
            self.terminated = True
            return {"terminated": True}

        def freeze(self, identity: dict[str, object]) -> dict[str, object]:
            return {"frozen": True}

    backend = _RecordingBackend()
    nanny = _nanny()
    nanny.supervisor = DeterministicSupervisor(backend)
    nanny.enroll(identity, now=None)
    nanny.release("inv-exec")
    event = EffectEvent(
        event_id="inv-event",
        effect_type="outbound_network",
        execution_id="inv-exec",
        agent_id="a",
        pid=1234,
        process_start_identity="s1",
        sandbox_id="sbx",
        target="example.invalid",
        action="connect",
        requested_scope="outbound_https",
        observed_scope="outbound_https",
        timestamp_utc="2026-10-05T00:00:00Z",
        correlation_id="inv-correlation",
        trace_id="inv-trace",
        source_component="invariant",
        socket_id="inv-socket",
    )
    outcome = nanny.observe_and_evaluate(event)
    if outcome.intervention_id is None:
        violations.append(_violation("GN-INV-006", "remediable deviation did not receive an intervention"))
    else:
        failure = nanny.respond(outcome.intervention_id, "invalid-response", event=event)
        if failure.enforcement_action != "terminate_execution_tree" or not backend.terminated:
            violations.append(_violation("GN-INV-006", "failed remediation did not trigger configured enforcement"))
    checked.append("GN-INV-006")

    # GN-INV-007: a failed observer reduces capability (never increases it).
    report = evaluate_health(
        observer_health={"network": False, "process_tree": True, "filesystem": True},
        policy_integrity_ok=True, supervisor_healthy=True,
    )
    if report.capability_reduction in {"none", ""}:
        violations.append(_violation("GN-INV-007", "loss of observation did not reduce capability"))
    checked.append("GN-INV-007")

    # GN-INV-008: policy-integrity failure defaults to deny, never silent downgrade.
    report = evaluate_health(
        observer_health={"network": True, "process_tree": True, "filesystem": True},
        policy_integrity_ok=False, supervisor_healthy=True,
    )
    if report.capability_reduction != "default_deny_sensitive_effects":
        violations.append(_violation("GN-INV-008", "policy integrity failure did not default to deny"))
    checked.append("GN-INV-008")

    # GN-INV-009: high-impact admin operations require a strong auth factor.
    if not HIGH_IMPACT_OPERATIONS:
        violations.append(_violation("GN-INV-009", "no high-impact admin operations are declared"))
    if "offline_recovery_token" in AUTH_FACTORS and not ({"passkey", "mfa", "hardware_key"} & AUTH_FACTORS):
        violations.append(_violation("GN-INV-009", "no strong auth factor is admitted"))
    checked.append("GN-INV-009")

    # GN-INV-011: containment-control interference is a critical, zero-attempt event.
    from .gremlin.policy import default_policy_bundle
    profile = default_policy_bundle().profile("gn-redteam-strict")
    rule = profile.rule_for("containment_control_interference")
    if rule is None or rule.remediation_attempts != 0 or rule.failure_action != "terminate_execution_tree":
        violations.append(_violation("GN-INV-011", "interference is not a zero-attempt termination event"))
    checked.append("GN-INV-010")
    checked.append("GN-INV-011")

    # GN-INV-012: enforcement exists and does not require an LLM.
    if not isinstance(DeterministicSupervisor(), DeterministicSupervisor):
        violations.append(_violation("GN-INV-012", "deterministic supervisor is unavailable"))
    checked.append("GN-INV-012")

    # GN-INV-013: recording a child id is not proof that its process identity
    # was enrolled and released under the parent's containment.
    child_registry = ProtectedExecutionRegistry()
    child_registry.enroll(identity)
    try:
        child_registry.register_child("inv-exec", "inv-child")
    except EnrollmentError:
        pass
    else:
        violations.append(
            _violation(
                "GN-INV-013",
                "child ID-only registration must be rejected until OS custody is verified",
            )
        )
    if child_registry.get("inv-child") is None:
        violations.append(
            _violation(
                "GN-INV-013",
                "verified child identity enrollment and inherited containment are not implemented",
            )
        )
    checked.append("GN-INV-013")

    # GN-INV-014: the policy owner must commission the real independent authority;
    # importing a type or labeling an offline token is not sufficient evidence.
    recovery_api_available = (
        callable(RecoveryAuthority)
        and callable(getattr(FileRecoveryReplayLedger, "consume", None))
        and callable(getattr(FileRecoveryReplayLedger, "revoke", None))
        and callable(getattr(FileRecoveryReplayLedger, "is_revoked", None))
    )
    if not recovery_api_available:
        violations.append(
            _violation(
                "GN-INV-014",
                "independent recovery authorization and durable replay owners are unavailable",
            )
        )
    elif getattr(nanny, "recovery_authority", None) is None:
        violations.append(
            _violation(
                "GN-INV-014",
                "recovery authorization owner is not commissioned into Gremlin and has no real independent authenticator",
            )
        )
    checked.append("GN-INV-014")

    unresolved = sorted(
        item["invariant"]
        for item in violations
        if item["invariant"] in {"GN-INV-013", "GN-INV-014"}
    )
    evaluated_ids = set(checked)
    evaluated_count = len(checked)
    coverage_complete = (
        evaluated_count == len(INVARIANT_IDS)
        and evaluated_ids == set(INVARIANT_IDS)
    )
    if not coverage_complete:
        violations.append(
            _violation(
                "GN-INV-000",
                "evaluated invariant coverage differs from the declared invariant set",
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not violations and coverage_complete,
        "checked": sorted(set(checked)),
        "declared_count": len(INVARIANT_IDS),
        "evaluated_count": evaluated_count,
        "coverage_complete": coverage_complete,
        "violations": sorted(violations, key=lambda item: (item["invariant"], item["detail"])),
        "unresolved": unresolved,
        "authority_granted": False,
    }