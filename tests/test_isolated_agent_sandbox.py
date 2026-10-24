"""Isolated Agent Sandbox tests.

These prove the coordinated-mode contract: ON atomically establishes every
component, enforcement fails closed for governed external connectivity, the
control plane is read-only to governed agents, and external information follows
the escalation boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from runtime.gremlin.containment import GremlinNanny
from runtime.gremlin.events import EffectEvent
from runtime.gremlin.identity import ProcessIdentity
from runtime.gremlin.observers import ObserverSet
from runtime.gremlin.supervisor import DeterministicSupervisor
from runtime.isolated_sandbox import (
    REQUIRED_COMPONENTS,
    SANDBOX_POLICY_RELATIVE,
    EscalationBoundary,
    EscalationRequest,
    SandboxPolicyError,
    control_plane_read_only_for_agents,
    decide_connection,
    establish_sandbox,
    full_component_acknowledgments,
    load_sandbox_policy,
    orchestrator_context,
    sandbox_off,
    sandbox_policy_from_dict,
    sandbox_provenance,
)

KEY = b"sandbox-test-signing-key-0123456789"
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


class FakeBackend:
    available = True

    def __init__(self):
        self.terminated = []

    def terminate_tree(self, identity):
        self.terminated.append(identity)
        return {"terminated": True}

    def freeze(self, identity):
        return {"frozen": True}


def make_nanny(backend=None):
    observers = ObserverSet()
    for kind in ("network", "process_tree", "filesystem"):
        observers.register(kind, lambda: ())
    return GremlinNanny(
        authority_id="gn-authority", signing_key=KEY, observers=observers,
        supervisor=DeterministicSupervisor(backend or FakeBackend()),
    )


def identity(execution_id="exec-1", pid=111, start="s1"):
    return ProcessIdentity(
        agent_execution_id=execution_id, agent_id="agent-1", pid=pid,
        process_start_identity=start, parent_pid=None, parent_execution_id=None,
        sandbox_id="sbx-1", job_object_id=None, container_or_cgroup_id=None,
        runtime_id="rt-1", model_id="m1", orchestration_id="orch-1",
        policy_profile="gn-redteam-strict", registered_at_utc=NOW.isoformat(),
    )


def network_event(execution_id="exec-1", target="evil.example.com"):
    return EffectEvent(
        event_id="evt-net-1", effect_type="outbound_network", execution_id=execution_id,
        agent_id="agent-1", pid=111, process_start_identity="s1", sandbox_id="sbx-1",
        target=target, action="connect", requested_scope="outbound_https",
        observed_scope="outbound_https", timestamp_utc=NOW.isoformat(),
        correlation_id="c1", trace_id="t1", source_component="network_observer",
    )


# ---------------------------------------------------------------------------
# Coordinated mode
# ---------------------------------------------------------------------------
def test_sandbox_on_establishes_every_component_atomically():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    assert policy.active is True
    assert set(policy.established_components) == set(REQUIRED_COMPONENTS)
    assert policy.network_policy.default == "deny"


def test_sandbox_off_is_not_active():
    policy = sandbox_off(scope_key="ws:1")
    assert policy.active is False
    assert policy.established_components == ()


def test_persisted_sandbox_policy_loads_only_for_its_project_scope(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    policy = establish_sandbox(scope_key=project.resolve().as_posix(), component_acknowledgments=full_component_acknowledgments())
    target = project / SANDBOX_POLICY_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(policy.as_dict()), encoding="utf-8")

    assert load_sandbox_policy(project) == policy


def test_persisted_sandbox_policy_rejects_a_different_project_scope(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    policy = establish_sandbox(scope_key="another-project", component_acknowledgments=full_component_acknowledgments())
    target = project / SANDBOX_POLICY_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(policy.as_dict()), encoding="utf-8")

    with pytest.raises(SandboxPolicyError, match="different project scope"):
        load_sandbox_policy(project)


def test_persisted_sandbox_policy_rejects_a_tampered_digest(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    image = establish_sandbox(scope_key=project.resolve().as_posix(), component_acknowledgments=full_component_acknowledgments()).as_dict()
    image["policy_sha256"] = "0" * 64
    target = project / SANDBOX_POLICY_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(image), encoding="utf-8")

    with pytest.raises(SandboxPolicyError, match="canonical typed representation"):
        load_sandbox_policy(project)


def test_sandbox_policy_round_trips_and_detects_tampering():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["a.internal:443"], component_acknowledgments=full_component_acknowledgments())
    image = policy.as_dict()
    assert sandbox_policy_from_dict(image).mode == "ON"
    tampered = {**image, "policy_sha256": "0" * 64}
    with pytest.raises(SandboxPolicyError):
        sandbox_policy_from_dict(tampered)


def test_sandbox_rejects_url_endpoint():
    with pytest.raises(SandboxPolicyError):
        establish_sandbox(scope_key="ws:1", allowed_endpoints=["https://api.internal/x"], component_acknowledgments=full_component_acknowledgments())
def test_partial_activation_is_refused():
    with pytest.raises(SandboxPolicyError):
        from runtime.isolated_sandbox import SandboxPolicy, NetworkPolicy

        SandboxPolicy(
            mode="ON", scope_key="ws:1", policy_revision="r1",
            network_policy=NetworkPolicy(default="deny"),
            established_components=("monitoring",),
        )


# ---------------------------------------------------------------------------
# Network policy enforcement (fail closed)
# ---------------------------------------------------------------------------
def test_connection_to_unlisted_endpoint_is_denied():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    decision = decide_connection(policy, "evil.example.com", known_authorized=True)
    assert decision.permitted is False
    assert decision.enforcement_action == "terminate_execution_tree"


def test_unknown_authorization_fails_closed():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    decision = decide_connection(policy, "api.internal:443", known_authorized=None)
    assert decision.permitted is False
    assert "fail closed" in decision.reason


def test_authorized_listed_endpoint_is_permitted():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    decision = decide_connection(policy, "api.internal:443", known_authorized=True)
    assert decision.permitted is True


def test_sandbox_off_permits_normal_execution():
    policy = sandbox_off(scope_key="ws:1")
    assert decide_connection(policy, "anything.example.com", known_authorized=None).permitted is True


def test_sandbox_enforcement_terminates_unauthorized_connection():
    backend = FakeBackend()
    nanny = make_nanny(backend)
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(network_event(target="evil.example.com"), now=NOW)
    assert outcome.decision == "terminate"
    assert backend.terminated


def test_sandbox_enforcement_permits_allowlisted_connection():
    nanny = make_nanny()
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    # Authorization must be *proven* externally; the allowlist alone is not proof
    # (an unknown authorization fails closed).
    allowances = {"outbound_network:api.internal:443": "allow-api-internal"}
    outcome = nanny.observe_and_evaluate(
        network_event(target="api.internal:443"), allowances=allowances, now=NOW
    )
    assert outcome.decision == "allow"


def test_sandbox_allowlisted_endpoint_without_proof_still_fails_closed():
    nanny = make_nanny()
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    # No external authorization proof: being listed is not itself proof.
    outcome = nanny.observe_and_evaluate(network_event(target="api.internal:443"), now=NOW)
    assert outcome.decision == "terminate"


# ---------------------------------------------------------------------------
# Read-only control plane
# ---------------------------------------------------------------------------
def test_control_plane_read_only_to_agents_while_active():
    policy = establish_sandbox(scope_key="ws:1", component_acknowledgments=full_component_acknowledgments())
    assert control_plane_read_only_for_agents(policy) is True
    nanny = make_nanny()
    nanny.apply_sandbox_policy(policy)
    assert nanny.control_plane_writable_by("governed_agent") is False
    assert nanny.control_plane_writable_by("containment_authority") is True


def test_control_plane_writable_when_sandbox_off():
    nanny = make_nanny()
    assert nanny.control_plane_writable_by("administrator") is True


# ---------------------------------------------------------------------------
# Orchestrator awareness + provenance
# ---------------------------------------------------------------------------
def test_orchestrator_context_declares_sandbox_active():
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    context = orchestrator_context(policy)
    assert context["isolated_agent_sandbox"] == "ACTIVE"
    assert context["subordinate_agents_cannot_retrieve_external_information"] is True
    assert context["network_policy"]["allowed_endpoints"] == ["api.internal:443"]


def test_run_provenance_records_isolation_state():
    policy = establish_sandbox(scope_key="ws:1", component_acknowledgments=full_component_acknowledgments())
    provenance = sandbox_provenance(policy, run_id="run-1", agent_id="agent-1", process_identity="pid:111")
    assert provenance["isolated_agent_sandbox"] == "ON"
    assert provenance["run_id"] == "run-1"


# ---------------------------------------------------------------------------
# External information escalation
# ---------------------------------------------------------------------------
def test_isolated_agent_escalates_rather_than_retrieving():
    boundary = EscalationBoundary(authorized_mediators=["workspace-orchestrator"])
    request = EscalationRequest(
        escalation_id="esc-1", agent_execution_id="exec-1",
        requested_information="latest upstream API schema", reason="task requires it",
        raised_at_utc=NOW.isoformat(),
    )
    boundary.raise_request(request, now=NOW)
    assert boundary.open_requests == (request,)
    result = boundary.resolve(
        "esc-1", mediator="workspace-orchestrator",
        sanitized_result="schema-v2 (sanitized)", now=NOW,
    )
    assert result.disposition == "resolved"
    assert boundary.open_requests == ()


def test_unauthorized_mediator_cannot_resolve_escalation():
    boundary = EscalationBoundary(authorized_mediators=["workspace-orchestrator"])
    boundary.raise_request(EscalationRequest(
        escalation_id="esc-2", agent_execution_id="exec-1",
        requested_information="x", reason="y", raised_at_utc=NOW.isoformat(),
    ), now=NOW)
    with pytest.raises(SandboxPolicyError):
        boundary.resolve("esc-2", mediator="isolated-agent", sanitized_result="z", now=NOW)

# ---------------------------------------------------------------------------
# Coordinated-mode integration with the canonical Gremlin Nanny
# ---------------------------------------------------------------------------
def test_sandbox_mode_configures_canonical_nanny_not_a_second_monitor():
    """The mode configures the ONE containment instance; it creates no monitor."""
    from runtime.gremlin.containment import GremlinNanny

    nanny = make_nanny()
    assert nanny.sandbox_active is False
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"], component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    assert nanny.sandbox_active is True
    # There is exactly one containment authority; the sandbox did not add another.
    assert nanny.authority.authority_id == "gn-authority"


def test_sandbox_denied_connection_without_termination_stays_running():
    nanny = make_nanny()
    policy = establish_sandbox(scope_key="ws:1", allowed_endpoints=["api.internal:443"],
        terminate_on_unauthorized=False,
        component_acknowledgments=full_component_acknowledgments())
    nanny.apply_sandbox_policy(policy)
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    outcome = nanny.observe_and_evaluate(network_event(target="evil.example.com"), now=NOW)
    assert outcome.decision == "deny"
    assert nanny.registry.get("exec-1").state == "RUNNING_PROTECTED"


def test_sandbox_off_leaves_normal_containment_behaviour():
    nanny = make_nanny()
    nanny.apply_sandbox_policy(sandbox_off(scope_key="ws:1"))
    nanny.enroll(identity(), now=NOW)
    nanny.release("exec-1")
    # With sandbox off, a normal unauthorized network effect follows the base
    # policy (one bounded intervention), not sandbox immediate termination.
    outcome = nanny.observe_and_evaluate(network_event(target="evil.example.com"), now=NOW)
    assert outcome.decision == "remediate"