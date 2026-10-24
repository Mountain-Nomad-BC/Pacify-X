import pytest
from pathlib import Path

from runtime.workflow_worker import (
    _GroupContainmentUnavailable,
    _group_approval,
    _host_custody_execution_id,
    _host_custody_parent_resource_id,
    _host_custody_state_path,
    _spec_for_group,
)


def _agent_spec():
    return {
        "agent_id": "group-agent",
        "version": "1.0.0",
        "project_id": "project-1",
        "owner": "workflow-owner",
        "harness_id": "workflow",
        "instruction_sha256": "a" * 64,
        "capability_binding_ids": [],
        "effect_grant_ids": [],
        "required_tests": ["identity"],
        "lifecycle": "admitted",
        "model": {
            "provider": "deterministic",
            "vendor": "",
            "family": "px-bounded-worker",
            "model_id": "px-bounded-worker",
            "version": "",
            "max_output_tokens": 1024,
            "temperature": 0.0,
        },
        "tool_binding_ids": [],
        "memory_binding_ids": [],
        "handoff_agent_ids": [],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }


def _group_node_config(agent_spec):
    return {
        "execution_mode": "prepared-model-group",
        "prepared_group_reference": {
            "schema_version": "px.prepared-group-reference/1.0",
            "plan_id": "task-plan-0123456789abcdef01234567",
            "plan_sha256": "a" * 64,
        },
        "agent_spec": agent_spec,
        "placements": {"px-bounded-worker": {"model_id": "px-bounded-worker"}},
    }


def test_group_adapter_requires_exact_canonical_agent_spec():
    spec = _spec_for_group({"node_config": _group_node_config(_agent_spec())})

    assert spec.agent_id == "group-agent"
    assert spec.instruction_sha256 == "a" * 64


def test_group_adapter_rejects_missing_or_extended_agent_spec():
    # A closed prepared-group declaration requires its exact four fields first;
    # a bare agent-spec object is no longer a valid node config at all.
    with pytest.raises(ValueError, match="exact four fields"):
        _spec_for_group({"node_config": {}})

    value = _agent_spec()
    value["unreviewed"] = True
    with pytest.raises(ValueError, match="exact canonical agent spec"):
        _spec_for_group({"node_config": _group_node_config(value)})


def test_group_adapter_requires_host_consumed_approval():
    evidence = {
        "required": True,
        "host_consumed": True,
        "approved_by": "operator",
        "approval_sha256": "b" * 64,
        "approval_id_sha256": "c" * 64,
    }

    assert _group_approval({
        "approval_required": True,
        "approval_execution": evidence,
    }) is True

    with pytest.raises(PermissionError, match="host-consumed approval"):
        _group_approval({
            "approval_required": False,
            "approval_execution": evidence,
        })


def test_group_adapter_reads_only_a_bounded_host_custody_reference():
    assert _host_custody_parent_resource_id(
        {"containment_parent_resource_id": "process-abcd"}
    ) == "process-abcd"

    # Absent, blank, and non-string values all resolve to no binding; the
    # reference is never inferred from an unadmitted field.
    assert _host_custody_parent_resource_id({}) is None
    assert _host_custody_parent_resource_id(
        {"containment_parent_resource_id": "   "}
    ) is None
    assert _host_custody_parent_resource_id(
        {"containment_parent_resource_id": 42}
    ) is None
    # Surrounding whitespace is trimmed so the reference resolves identically.
    assert _host_custody_parent_resource_id(
        {"containment_parent_resource_id": "  process-abcd  "}
    ) == "process-abcd"


def test_host_custody_execution_id_reads_only_a_bounded_string():
    assert _host_custody_execution_id(
        {"containment_execution_id": "workflow-worker-abc"}
    ) == "workflow-worker-abc"
    assert _host_custody_execution_id({}) is None
    assert _host_custody_execution_id({"containment_execution_id": 7}) is None
    assert _host_custody_execution_id({"containment_execution_id": "  "}) is None
    assert _host_custody_execution_id(
        {"containment_execution_id": "  workflow-worker-abc  "}
    ) == "workflow-worker-abc"


def test_host_custody_state_path_accepts_only_the_canonical_workflow_ledger(tmp_path):
    canonical_root = tmp_path / ".agentic_engineering_os_px" / "studios" / "workflows"
    canonical_root.mkdir(parents=True)
    ledger = canonical_root / "resources.json"
    ledger.write_text("{}", encoding="utf-8")
    resolved = _host_custody_state_path(
        {"containment_resource_state_path": str(ledger)}, tmp_path)
    assert resolved is not None and resolved.name == "resources.json"
    # A missing ledger fails closed instead of admitting an unproven authority.
    try:
        _host_custody_state_path({"containment_resource_state_path": str(
            canonical_root / "absent.json")}, tmp_path)
    except OSError:
        pass
    else:
        raise AssertionError("a missing custody ledger was admitted")
    # A file outside the canonical workflow state is never an admitted authority.
    outside = tmp_path / "elsewhere.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        _host_custody_state_path(
            {"containment_resource_state_path": str(outside)}, tmp_path)
    except ValueError as error:
        assert "canonical workflow resource ledger" in str(error)
    else:
        raise AssertionError("non-canonical custody state was admitted")


def test_host_recovery_verifier_requires_a_concrete_module_adapter():
    from runtime.gremlin.host_configuration import resolve_recovery_verifier_from_environment
    assert resolve_recovery_verifier_from_environment is not None
    # The adapter is resolved from an admitted environment binding only; an
    # absent binding is an explicit unavailable state, not a synthetic verifier.
    import os
    previous = os.environ.pop("PX_GREMLIN_RECOVERY_VERIFIER", None)
    try:
        assert resolve_recovery_verifier_from_environment() is None
        os.environ["PX_GREMLIN_RECOVERY_VERIFIER"] = "json"
        try:
            resolve_recovery_verifier_from_environment()
        except ValueError as error:
            assert "module:attribute" in str(error)
        else:
            raise AssertionError("malformed verifier binding was admitted")
    finally:
        if previous is not None:
            os.environ["PX_GREMLIN_RECOVERY_VERIFIER"] = previous


def test_group_containment_unavailable_is_a_distinct_fail_closed_error():
    # A missing host custody binding must be reportable distinctly from a member
    # execution failure, so an absent host wiring cannot be mistaken for a
    # member-level disposition.
    assert issubclass(_GroupContainmentUnavailable, RuntimeError)
    error = _GroupContainmentUnavailable("host custody binding absent")
    assert "host custody binding absent" in str(error)


def _native_effect_task(tmp_path):
    import hashlib
    from datetime import datetime, timedelta, timezone
    from runtime.studio_models import digest
    from runtime.studio_run_control import DurableRunControl
    from runtime.execution_context import ExecutionContext
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    control = DurableRunControl(tmp_path, tmp_path / ".agentic_engineering_os_px/studios/workflows/sessions")
    run = control.create(kind="workflow", subject_id="workflow:effect",
        version="1.0.0", owner="owner", revision_sha256="a" * 64, request_sha256="b" * 64)
    run = control.transition(run["run_id"], "running", actor="owner", approved=True)
    run_id = run["run_id"]
    task = {"run_id": run_id, "node_id": "node:effect", "attempt": 1,
        "workflow_id": "workflow:effect", "authority_record_hashes": {"grant:g": "a" * 64}}
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    context = ExecutionContext(
        execution_id="workflow-node-" + hashlib.sha256(
            f"{run_id}\0node:effect\0{1}\0{1}".encode()).hexdigest()[:40],
        parent_execution_id=run_id, root_execution_id=run_id,
        project_id="workflow:effect", session_id=run_id, revision=run["sequence"], epoch=1,
        generation_vector_sha256=None, authority_reference_sha256=digest(task["authority_record_hashes"]),
        effect_budget_sha256="c" * 64, cancellation_scope_id=run_id, deadline_utc=expiry,
        actor_id="owner", provider_id=None, trace_root_id=run_id, workflow_adapter_revision="d" * 64)
    task["execution_context"] = context.as_dict()
    execution_id = "workflow-effect-" + digest({"run_id": run_id, "node_id": "node:effect",
        "workflow_version": "1.0.0", "authority": task["authority_record_hashes"]})[:40]
    binding = {"idempotency_key": "workflow-node-effect:" + digest({"run_id": run_id,
        "node_id": "node:effect", "effect": "write", "scope": "workspace:demo"}),
        "execution_id": execution_id, "effect": "write", "scopes": ["workspace:demo"]}
    EffectIntentLedger(tmp_path).intend(**binding)
    lease_id = "lease:effect"
    ScopeLeaseStore(tmp_path).acquire(lease_id=lease_id, execution_id=execution_id,
        effect="write", scopes=["workspace:demo"], reason="test actual scope", expires_utc=expiry)
    binding["lease_id"] = lease_id
    task["prepared_effect_intents"] = [binding]
    return task, [{"effects": ["write"], "scope_roots": ["workspace:demo"]}], control

def test_worker_requires_native_preexecution_intent_and_exact_live_lease(tmp_path):
    from runtime.workflow_worker import _verify_prepared_effect_intents
    task, grants, _ = _native_effect_task(tmp_path)
    assert _verify_prepared_effect_intents(tmp_path, task, grants) == tuple(task["prepared_effect_intents"])

@pytest.mark.parametrize("tamper", ["lease", "scope", "key", "context", "cancel"] )
def test_worker_rejects_stale_or_rebound_effect_fences_before_execution(tmp_path, tamper):
    from runtime.workflow_worker import _verify_prepared_effect_intents
    task, grants, control = _native_effect_task(tmp_path)
    binding = task["prepared_effect_intents"][0]
    if tamper == "lease":
        binding["lease_id"] = "lease:forged"
    elif tamper == "scope":
        binding["scopes"] = ["workspace:other"]
    elif tamper == "key":
        binding["idempotency_key"] = "workflow-node-effect:" + "f" * 64
    elif tamper == "context":
        task["execution_context"]["epoch"] = 2
    else:
        control.transition(task["run_id"], "cancel_requested", actor="owner", approved=True)
    with pytest.raises((PermissionError, ValueError)):
        _verify_prepared_effect_intents(tmp_path, task, grants)


@pytest.mark.parametrize("effect,scope", [("write", "workspace:group"), ("execute", "runtime")])
def test_group_effect_binding_maps_only_native_runtime_execution(tmp_path, monkeypatch, effect, scope):
    from runtime import workflow_worker as worker
    task, grants, _ = _native_effect_task(tmp_path)
    task.update(schema_version="px.workflow-node-task/1.0", adapter_id="model-group",
        executor_binding_id="executor:group", effect_grant_ids=["g"])
    task["authority_record_hashes"].update({"executor:executor:group": "e" * 64,
        "binding:executor:group": "b" * 64})
    # Keep the native run/intent/lease fixture current after binding metadata changed.
    from runtime.studio_models import digest
    from dataclasses import replace
    from runtime.execution_context import execution_context_from_dict
    task["execution_context"] = replace(execution_context_from_dict(task["execution_context"]),
        authority_reference_sha256=digest(task["authority_record_hashes"])).as_dict()
    class Authority:
        def verify_receipt(self, value): return value
        def resolve_executor(self, value): return {"adapter_id": "model-group"}, "e" * 64
        def resolve_binding(self, *args, **kwargs): return {"effect_grant_ids": ["g"]}, "b" * 64
        def resolve_grant(self, *args, **kwargs): return grants[0], "a" * 64
    class AuthorityStore:
        @staticmethod
        def open_existing(_root: Path):
            return Authority()

    monkeypatch.setattr(worker, "StudioAuthorityStore", AuthorityStore)
    # Native intent execution identity must be rebound to the exact changed authority.
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    from datetime import datetime, timedelta, timezone
    binding = task["prepared_effect_intents"][0]
    binding["execution_id"] = "workflow-effect-" + digest({"run_id": task["run_id"],
        "node_id": task["node_id"], "workflow_version": "1.0.0",
        "authority": task["authority_record_hashes"]})[:40]
    # Use a distinct exact scope so this fixture creates a new native fence.
    binding["effect"] = effect
    binding["scopes"] = [scope]
    grants[0]["effects"] = [effect]
    grants[0]["scope_roots"] = binding["scopes"]
    binding["idempotency_key"] = "workflow-node-effect:" + digest({"run_id": task["run_id"],
        "node_id": task["node_id"], "effect": effect, "scope": scope})
    binding["lease_id"] = "lease:group"
    EffectIntentLedger(tmp_path).intend(**{k: binding[k] for k in ("idempotency_key", "execution_id", "effect", "scopes")})
    ScopeLeaseStore(tmp_path).acquire(lease_id=binding["lease_id"], execution_id=binding["execution_id"],
        effect=effect, scopes=binding["scopes"], reason="native mapping fixture",
        expires_utc=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat())
    if effect == "write":
        with pytest.raises(PermissionError, match="exact native execute/origin/gateway effect fences"):
            worker._verify_group_workflow_effect_receipt(tmp_path, task, task_plan={}, spec=None, placements={})
    else:
        spec = object()
        monkeypatch.setattr(worker, "_spec_for_group", lambda value: spec)
        task["task_execution_plan"] = {"plan_sha256": "f" * 64}
        task["node_config"] = {"placements": {"model": {"device": "cpu"}}}
        kwargs = dict(task_plan={"plan_sha256": "f" * 64}, spec=spec,
            placements=task["node_config"]["placements"])
        assert worker._verify_group_workflow_effect_receipt(tmp_path, task, **kwargs)[1] == (binding,)
        with pytest.raises(PermissionError, match="differs from the signed prepared task"):
            worker._verify_group_workflow_effect_receipt(tmp_path, task, **{**kwargs, "placements": {}})

