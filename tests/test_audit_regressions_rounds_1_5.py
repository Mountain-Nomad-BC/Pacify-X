"""Negative/positive regression matrix for the unified audit rounds 1-5.

Each test cites its finding id (G01..G09, M01..M03, H01, E01, S01) from
PACIFY_X_IMPLEMENTATION_FIX_LIST.md. Negative probes reproduce the audited
adversarial case and must be rejected; positive controls prove valid behavior
still works. Inert backends and deterministic time only — no OS effects.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from runtime.effect_intent import EffectIntentError, EffectIntentLedger
from runtime.gremlin.admin import (
    AdminAuthorization,
    AdminAuthorizationError,
    ProtectedAdminControl,
    sign_admin_authorization,
)
from runtime.gremlin.authorization import (
    CapabilityLease,
    lease_denial_reason,
    resolve_authorization,
)
from runtime.gremlin.containment import ContainmentError, EvaluationOutcome, GremlinNanny
from runtime.gremlin.events import EffectEvent
from runtime.gremlin.observers import ObserverSet
from runtime.gremlin.policy import default_policy_bundle
from runtime.gremlin.registry import ProtectedExecutionRegistry
from runtime.gremlin.supervisor import DeterministicSupervisor
from runtime.isolated_sandbox import (
    SandboxPolicyError,
    establish_sandbox,
    full_component_acknowledgments,
)
from runtime.memory_broker import build_memory_query_plan, materialize_memory_context
from runtime.memory_fabric import MemoryRecord
from runtime.agent_handoff import (
    acknowledge_handoff,
    consume_handoff,
    create_handoff_packet,
    validate_handoff_packet,
)

KEY = b"audit-regression-signing-key-0123456789"
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
POLICY = default_policy_bundle()


class FakeBackend:
    available = True

    def __init__(self, *, terminated_result: dict | object | None = None, frozen_result: dict | object | None = None) -> None:
        self.terminated: list[dict] = []
        self.frozen: list[dict] = []
        self.terminated_result = terminated_result if terminated_result is not None else {"terminated": True}
        self.frozen_result = frozen_result if frozen_result is not None else {"frozen": True}

    def terminate_tree(self, identity: dict) -> dict:
        self.terminated.append(identity)
        return dict(self.terminated_result) if isinstance(self.terminated_result, dict) else self.terminated_result

    def freeze(self, identity: dict) -> dict:
        self.frozen.append(identity)
        return dict(self.frozen_result) if isinstance(self.frozen_result, dict) else self.frozen_result


class UnavailableBackend:
    available = False


def make_nanny(backend=None) -> GremlinNanny:
    observers = ObserverSet()
    for kind in ("network", "process_tree", "filesystem"):
        observers.register(kind, lambda: ())
    return GremlinNanny(
        authority_id="gn-authority",
        signing_key=KEY,
        observers=observers,
        supervisor=DeterministicSupervisor(backend or FakeBackend()),
    )


def identity(execution_id="exec-1", pid=4321, start="start-1"):
    from runtime.gremlin.identity import ProcessIdentity

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
        policy_profile="gn-redteam-strict",
        registered_at_utc=NOW.isoformat(),
    )


def effect(execution_id="exec-1", pid=4321, start="start-1", effect_type="outbound_network", target="api.example.com", event_id=None, agent_id="agent-1", sandbox_id="sandbox-1"):
    return EffectEvent(
        event_id=event_id or f"evt-{execution_id}-{effect_type}",
        effect_type=effect_type,
        execution_id=execution_id,
        agent_id=agent_id,
        pid=pid,
        process_start_identity=start,
        sandbox_id=sandbox_id,
        target=target,
        action="connect",
        requested_scope="outbound_https",
        observed_scope="outbound_https",
        timestamp_utc=NOW.isoformat(),
        correlation_id="corr-1",
        trace_id="trace-1",
        source_component="network_observer",
    )


def lease(execution_id="exec-1", **changes) -> CapabilityLease:
    values = {
        "lease_id": "lease-1",
        "agent_execution_id": execution_id,
        "capability": "outbound_network",
        "destination_scope": ("api.example.com",),
        "valid_from_utc": NOW.isoformat(),
        "valid_until_utc": (NOW + timedelta(minutes=5)).isoformat(),
        "max_connections": 2,
        "max_bytes": 1024,
        "max_requests": 2,
        "allowed_protocols": ("https",),
        "policy_revision": POLICY.revision,
    }
    values.update(changes)
    return CapabilityLease(**values)


def enrolled_nanny(nanny: GremlinNanny) -> GremlinNanny:
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    return nanny


# ---------------------------------------------------------------------------
# G01 — lease authorization is authoritative
# ---------------------------------------------------------------------------
def test_g01_lease_negative_table():
    event = effect()
    cases = {
        "lease_missing": None,
        "lease_foreign_owner": lease(execution_id="exec-OTHER"),
        "lease_capability_mismatch": lease(capability="dns"),
        "lease_target_out_of_scope": lease(destination_scope=("other.example.com",)),
        "lease_not_yet_valid": lease(valid_from_utc=(NOW + timedelta(minutes=2)).isoformat()),
        "lease_expired": lease(valid_from_utc=(NOW - timedelta(minutes=5)).isoformat(), valid_until_utc=(NOW - timedelta(minutes=1)).isoformat()),
        "lease_revoked": lease(),
        "lease_stale_policy_revision": lease(policy_revision="ancient-revision"),
        "lease_zero_budget:connections": lease(max_connections=0),
    }
    for expected_reason, candidate in cases.items():
        revoked = {candidate.lease_id} if expected_reason == "lease_revoked" else frozenset()
        reason = lease_denial_reason(
            candidate,
            event,
            capability="outbound_network",
            now=NOW,
            revoked_lease_ids=revoked,
            current_policy_revision=POLICY.revision,
        )
        assert reason == expected_reason, (expected_reason, reason)
    # Positive control: a valid lease authorizes.
    assert lease_denial_reason(lease(), event, capability="outbound_network", now=NOW,
                               current_policy_revision=POLICY.revision) is None


def test_g01_resolve_authorization_dies_on_invalid_lease():
    profile = POLICY.profile("gn-redteam-strict")
    resolution = resolve_authorization(
        effect(), profile=profile, leases={"exec-1": lease(valid_until_utc=(NOW - timedelta(seconds=1)).isoformat())},
        now=NOW, current_policy_revision=POLICY.revision,
    )
    assert resolution.final_decision != "allow"


def test_g01_exhausted_budget_denies_but_unrelated_zero_budget_does_not():
    event = effect()
    # Applicable dimension exhausted by consumption.
    assert lease_denial_reason(
        lease(max_connections=1), event, capability="outbound_network", now=NOW,
        current_policy_revision=POLICY.revision,
        budget_ledger={"lease-1": {"connections": 1, "requests": 0}},
    ) == "lease_budget_exhausted:connections"
    # An unrelated zero dimension (bytes) does not block a dns request.
    assert lease_denial_reason(
        lease(max_bytes=0, capability="dns"), effect(effect_type="dns"),
        capability="dns", now=NOW, current_policy_revision=POLICY.revision,
    ) is None


def test_g01_concurrent_last_budget_requests_admit_only_the_authorized_number():
    nanny = enrolled_nanny(make_nanny())
    bounded = lease(max_connections=1, max_requests=1)
    leases = {"exec-1": bounded}
    first = nanny.observe_and_evaluate(effect(event_id="evt-a"), leases=leases, now=NOW)
    second = nanny.observe_and_evaluate(effect(event_id="evt-b"), leases=leases, now=NOW)
    decisions = [first.decision, second.decision]
    assert sorted(decisions) == ["allow", "remediate"], decisions


# ---------------------------------------------------------------------------
# G02 — intervention response cannot target another execution
# ---------------------------------------------------------------------------
def test_g02_response_with_borrowed_event_rejected_before_effects():
    backend = FakeBackend()
    nanny = enrolled_nanny(make_nanny(backend))
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    foreign = effect(execution_id="exec-2", pid=9999, start="start-2", event_id="evt-foreign")
    with pytest.raises(ContainmentError):
        nanny.respond(outcome.intervention_id, "complied", event=foreign, now=NOW)
    assert backend.terminated == []
    assert nanny.registry.get("exec-2") is None
    assert nanny.registry.get("exec-1").state == "INTERVENTION"


# ---------------------------------------------------------------------------
# G03 — event process identity must match the enrolled tuple
# ---------------------------------------------------------------------------
def test_g03_foreign_process_identity_event_rejected():
    nanny = enrolled_nanny(make_nanny())
    for changes in (
        {"pid": 8675309},
        {"start": "start-recycled"},
        {"agent_id": "agent-evil"},
    ):
        with pytest.raises(ContainmentError):
            nanny.observe_and_evaluate(effect(**changes), now=NOW)
    # Positive control: the exact enrolled identity evaluates.
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    assert outcome.decision == "remediate"


# ---------------------------------------------------------------------------
# G04 — intervention id collision across executions
# ---------------------------------------------------------------------------
def test_g04_same_event_id_across_executions_gets_distinct_trackers():
    registry = ProtectedExecutionRegistry()
    assert registry is not None
    nanny = make_nanny()
    nanny.enroll(identity(execution_id="exec-1", pid=4321, start="start-1"), now=NOW)
    nanny.enroll(identity(execution_id="exec-2", pid=4322, start="start-2"), now=NOW)
    nanny.release("exec-1")
    nanny.release("exec-2")
    first = nanny.observe_and_evaluate(effect(execution_id="exec-1", pid=4321, start="start-1"), now=NOW)
    second = nanny.observe_and_evaluate(
        effect(execution_id="exec-2", pid=4322, start="start-2", event_id="evt-exec-1-outbound_network"),
        now=NOW,
    )
    assert first.intervention_id != second.intervention_id
    assert nanny._trackers[first.intervention_id].intervention.agent_execution_id == "exec-1"
    assert nanny._trackers[second.intervention_id].intervention.agent_execution_id == "exec-2"


# ---------------------------------------------------------------------------
# G05/G06 — enforcement truth and lifecycle
# ---------------------------------------------------------------------------
def test_g05_backend_refusal_is_not_success():
    backend = FakeBackend(terminated_result={"terminated": False, "pid": 4321})
    nanny = enrolled_nanny(make_nanny(backend))
    outcome = nanny.observe_and_evaluate(
        effect(effect_type="containment_control_interference", target="gn-control"), now=NOW
    )
    assert outcome.containment_success is False
    assert "unconfirmed" in outcome.detail


def test_g06_supervisor_unavailable_never_marks_terminated():
    nanny = enrolled_nanny(make_nanny(UnavailableBackend()))
    outcome = nanny.observe_and_evaluate(
        effect(effect_type="containment_control_interference", target="gn-control"), now=NOW
    )
    assert outcome.containment_success is False
    state = nanny.registry.get("exec-1").state
    assert state not in {"TERMINATED", "DEVIATION_SEALED"}
    assert state == "TERMINATING"


def test_g06_confirmed_termination_still_progresses():
    backend = FakeBackend()
    nanny = enrolled_nanny(make_nanny(backend))
    outcome = nanny.observe_and_evaluate(
        effect(effect_type="containment_control_interference", target="gn-control"), now=NOW
    )
    assert outcome.containment_success is True
    assert nanny.registry.get("exec-1").state == "DEVIATION_SEALED"
    assert backend.terminated


# ---------------------------------------------------------------------------
# G08 — autonomous deadline enforcement
# ---------------------------------------------------------------------------
def test_g08_silent_client_sweep_terminates_past_deadline():
    backend = FakeBackend()
    nanny = enrolled_nanny(make_nanny(backend))
    outcome = nanny.observe_and_evaluate(effect(), now=NOW)
    intervention_id = outcome.intervention_id
    # Client never responds; time advances past the 1500 ms deadline.
    swept = nanny.sweep_expired_interventions(now=NOW + timedelta(seconds=5))
    assert len(swept) == 1 and swept[0].decision == "terminate"
    assert backend.terminated
    assert nanny.registry.get("exec-1").state == "DEVIATION_SEALED"
    # Idempotent: a second sweep performs nothing further.
    assert nanny.sweep_expired_interventions(now=NOW + timedelta(seconds=6)) == ()
    assert nanny._trackers[intervention_id].resolved


def test_g08_sweep_leaves_open_windows_alone():
    nanny = enrolled_nanny(make_nanny())
    nanny.observe_and_evaluate(effect(), now=NOW)
    assert nanny.sweep_expired_interventions(now=NOW) == ()
    assert nanny.registry.get("exec-1").state == "INTERVENTION"


# ---------------------------------------------------------------------------
# G09 — outcome serialization
# ---------------------------------------------------------------------------
def test_g09_every_outcome_variant_serializes():
    outcomes = [
        EvaluationOutcome("e1", "allow", "expected_authorized", None, None, None, True, "ok"),
        EvaluationOutcome("e2", "deny", "unexpected_unauthorized", None, "deny", None, False, "denied"),
        EvaluationOutcome("e3", "remediate", "expected_unauthorized", "gn-int:x", None, None, False, "issued"),
        EvaluationOutcome("e4", "terminate", "unexpected_unauthorized", None, "terminate_execution_tree", "gn-dev:x", False, "unconfirmed"),
    ]
    for outcome in outcomes:
        image = outcome.as_dict()
        assert image["event_id"] == outcome.event_id
        assert image["schema_version"].startswith("px.gremlin")


# ---------------------------------------------------------------------------
# G07 — admin authentication
# ---------------------------------------------------------------------------
def admin_auth(**changes) -> AdminAuthorization:
    values = {
        "principal_id": "ben", "auth_strength": "passkey", "operation": "pause_new_protected_runs",
        "target": "gn-redteam-strict", "permitted_action": "pause",
        "issued_at_utc": NOW.isoformat(),
        "expires_at_utc": (NOW + timedelta(minutes=5)).isoformat(),
        "nonce": "nonce-g1", "approval_id": "appr-1", "signature": "sig",
    }
    values.update(changes)
    return AdminAuthorization(**values)


def test_g07_forged_signature_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    with pytest.raises(AdminAuthorizationError):
        control.apply(admin_auth(signature="forged"), target_state="paused", reason="x", now=NOW)
    assert control.audit_log[-1].result == "refused"


def test_g07_action_mismatch_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    signed = sign_admin_authorization(admin_auth(permitted_action="disable"), KEY)
    with pytest.raises(AdminAuthorizationError):
        control.apply(signed, target_state="paused", reason="x", now=NOW)


def test_g07_future_issuance_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    signed = sign_admin_authorization(
        admin_auth(issued_at_utc=(NOW + timedelta(hours=1)).isoformat(),
                   expires_at_utc=(NOW + timedelta(hours=1, minutes=5)).isoformat()), KEY)
    with pytest.raises(AdminAuthorizationError):
        control.apply(signed, target_state="paused", reason="x", now=NOW)


def test_g07_nonce_replay_refused():
    control = ProtectedAdminControl(signing_key=KEY)
    signed = sign_admin_authorization(admin_auth(), KEY)
    control.apply(signed, target_state="paused", reason="first", now=NOW)
    with pytest.raises(AdminAuthorizationError):
        control.apply(signed, target_state="paused", reason="replay", now=NOW + timedelta(seconds=1))


def test_g07_valid_signature_applies():
    control = ProtectedAdminControl(signing_key=KEY)
    event = control.apply(sign_admin_authorization(admin_auth(), KEY), target_state="paused", reason="ok", now=NOW)
    assert event.result == "applied"


# ---------------------------------------------------------------------------
# S01 — sandbox readiness truth
# ---------------------------------------------------------------------------
def test_s01_unacknowledged_components_are_not_protected():
    for acks in (None, {}, {name: True for name in list(full_component_acknowledgments())[:-1]}):
        with pytest.raises(SandboxPolicyError, match="not ready"):
            establish_sandbox(scope_key="ws:1", component_acknowledgments=acks)


def test_s01_fully_acknowledged_establishes():
    policy = establish_sandbox(scope_key="ws:1", component_acknowledgments=full_component_acknowledgments())
    assert policy.mode == "ON"


# ---------------------------------------------------------------------------
# M01/M02/M03 — memory broker
# ---------------------------------------------------------------------------
def memory_record(memory_id="memory:one", **changes) -> MemoryRecord:
    values = {
        "memory_id": memory_id, "workspace_id": "workspace", "project_id": "project",
        "owner_id": "actor", "session_id": "session", "lease_id": "lease",
        "title": "Decision", "memory_type": "decision", "summary": "Use bounded proof",
        "source_artifact": "evidence.json", "source_sha256": "a" * 64,
        "evidence_locator": "evidence:one", "epistemic_status": "observation",
        "confidence": 0.9, "confidence_method": "direct", "classification": "internal",
        "acl": ("project", "actor"), "observed_at": NOW, "effective_at": NOW,
        "certification_status": "certified", "retrieval_enabled": True, "layer": "L1",
        "visibility": "project", "priority": 80,
    }
    values.update(changes)
    return MemoryRecord(**values)


def memory_plan(**changes):
    values = {
        "project_id": "project", "subject_id": "task", "actor_id": "actor",
        "agent_id": "agent", "binding_ids": ("memory:one",),
        "memory_classes": ("decision",), "tiers": ("L1",), "max_items": 2,
        "max_bytes": 4096, "max_tokens": 1024, "trust_floor": 0.8,
        "max_age_seconds": 3600, "conflict_policy": "quarantine",
        "provenance_required": True, "writeback_policy": "deny",
        "source_revision": "source-1", "dependency_revisions": {"memory": "revision-1"},
    }
    values.update(changes)
    return build_memory_query_plan(**values)


def test_m01_duplicate_memory_ids_quarantined_order_independently():
    plan = memory_plan(binding_ids=("memory:one", "memory:two"))
    left = memory_record("memory:one", summary="version A")
    right = memory_record("memory:one", summary="version B")
    shuffled = [right, left]
    results = [
        materialize_memory_context(plan, [left, right], now_utc=NOW),
        materialize_memory_context(plan, shuffled, now_utc=NOW),
    ]
    assert results[0] == results[1]
    assert results[0]["eligible"] is False
    assert "duplicate_memory_id:memory:one" in results[0]["quarantined"]


def test_m02_future_memory_quarantined_but_current_still_loads():
    future = materialize_memory_context(
        memory_plan(), [memory_record(effective_at=NOW + timedelta(days=30))], now_utc=NOW)
    assert "memory_future_effective:memory:one" in future["quarantined"]
    future_observed = materialize_memory_context(
        memory_plan(), [memory_record(observed_at=NOW + timedelta(days=30))], now_utc=NOW)
    assert "memory_future_observed:memory:one" in future_observed["quarantined"]
    ok = materialize_memory_context(memory_plan(), [memory_record()], now_utc=NOW)
    assert ok["eligible"] is True


def test_m03_stale_revision_materialization_fails_closed():
    with pytest.raises(ValueError, match="source revision is stale"):
        materialize_memory_context(memory_plan(), [memory_record()], now_utc=NOW,
                                   current_source_revision="source-2")
    with pytest.raises(ValueError, match="dependency revisions are stale"):
        materialize_memory_context(memory_plan(), [memory_record()], now_utc=NOW,
                                   current_dependency_revisions={"memory": "revision-2"})
    ok = materialize_memory_context(memory_plan(), [memory_record()], now_utc=NOW,
                                    current_source_revision="source-1",
                                    current_dependency_revisions={"memory": "revision-1"})
    assert ok["eligible"] is True


# ---------------------------------------------------------------------------
# H01 — handoff time bounds
# ---------------------------------------------------------------------------
def handoff_packet(**changes):
    values = {
        "project_id": "project", "task_plan_id": "plan-1", "task_plan_revision": "b" * 64,
        "run_id": "run-1", "sender_agent_id": "sender", "sender_revision": "c" * 64,
        "receiver_agent_id": "receiver", "receiver_revision": "d" * 64,
        "evidence": ({"ref": "evidence:one", "sha256": "e" * 64, "revision": "f" * 64},),
        "hypotheses": (), "open_questions": (), "authority": ("read",),
        "sender_authority": ("read",), "budgets": {"items": 1},
        "memory_query_plan_sha256": "1" * 64, "created_utc": NOW.isoformat(),
        "expires_utc": (NOW + timedelta(minutes=10)).isoformat(),
    }
    values.update(changes)
    return create_handoff_packet(**values)


def handoff_context(**changes):
    values = {
        "expected_project_id": "project", "receiver_agent_id": "receiver",
        "receiver_revision": "d" * 64,
        "current_evidence_revisions": {"evidence:one": "f" * 64},
        "now_utc": NOW.isoformat(),
    }
    values.update(changes)
    return values


def test_h01_future_created_packet_rejected():
    packet = handoff_packet(created_utc=(NOW + timedelta(days=30)).isoformat(),
                            expires_utc=(NOW + timedelta(days=31)).isoformat())
    report = validate_handoff_packet(packet, **handoff_context())
    assert not report["valid"] and "packet_created_in_future" in report["errors"]


def test_h01_future_acknowledgment_rejected():
    packet = handoff_packet()
    with pytest.raises(ValueError, match="future"):
        acknowledge_handoff(packet, decision="accept", reason="ok",
                            receiver_agent_id="receiver", receiver_revision="d" * 64,
                            acknowledged_utc=(NOW + timedelta(days=3)).isoformat(),
                            now_utc=NOW.isoformat())


def test_h01_valid_ack_and_consume_still_work():
    packet = handoff_packet()
    ack = acknowledge_handoff(packet, decision="accept", reason="ok",
                              receiver_agent_id="receiver", receiver_revision="d" * 64,
                              acknowledged_utc=NOW.isoformat(), now_utc=NOW.isoformat())
    body = consume_handoff(packet, ack, **handoff_context())
    assert body["consumable"] is True


# ---------------------------------------------------------------------------
# E01 — abandoned effect reconciliation custody
# ---------------------------------------------------------------------------
def test_e01_abandoned_intent_cannot_commit_from_a_valid_digest_alone(tmp_path):
    ledger = EffectIntentLedger(tmp_path, trusted_reconciliation_authorities=("effect-owner",))
    ledger.intend(idempotency_key="k1", execution_id="exec-1", effect="write_file", scopes=["out/x"])
    ledger.reclaim_in_flight(execution_id="exec-1")
    digest = "a" * 64
    with pytest.raises(EffectIntentError, match="reconciliation"):
        ledger.commit(idempotency_key="k1", execution_id="exec-1", result_sha256=digest)
    with pytest.raises(EffectIntentError, match="authority"):
        ledger.commit(idempotency_key="k1", execution_id="exec-1", result_sha256=digest,
                      reconciliation={"observed_outcome": "effect_occurred", "evidence_sha256": digest,
                                      "authority": "caller-not-trusted"})
    committed = ledger.commit(
        idempotency_key="k1", execution_id="exec-1", result_sha256=digest,
        reconciliation={"observed_outcome": "effect_occurred", "evidence_sha256": digest,
                        "authority": "effect-owner"})
    assert committed.state == "committed"


def test_e01_in_flight_commit_still_works(tmp_path):
    ledger = EffectIntentLedger(tmp_path)
    ledger.intend(idempotency_key="k2", execution_id="exec-1", effect="write_file", scopes=["out/x"])
    committed = ledger.commit(idempotency_key="k2", execution_id="exec-1", result_sha256="b" * 64)
    assert committed.state == "committed"
