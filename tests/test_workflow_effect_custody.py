from datetime import datetime, timedelta, timezone
import hashlib
import pytest
from runtime.workflow_worker import _verify_prepared_effect_intents
from runtime.studio_models import digest
from runtime.studio_run_control import DurableRunControl
from runtime.execution_context import ExecutionContext
from runtime.effect_intent import EffectIntentLedger
from runtime.scope_lease import ScopeLeaseStore


@pytest.fixture
def custody(tmp_path):
    control = DurableRunControl(tmp_path, tmp_path / ".engineering-bootstrap/studios/workflows/sessions")
    state = control.create(kind="workflow", subject_id="workflow:fixture", version="1.0.0", owner="fixture-owner", revision_sha256="a" * 64, request_sha256="b" * 64, checkpoint={})
    state = control.transition(state["run_id"], "running", actor="fixture-owner", approved=True)
    run, node, epoch = state["run_id"], "node:group", 1
    hashes = {"binding:fixture": "c" * 64}
    # Keep the attempt as its own field in the canonical separator sequence.
    context_id = "workflow-node-" + hashlib.sha256("\0".join([run, node, "1", str(epoch)]).encode()).hexdigest()[:40]
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    context = ExecutionContext(execution_id=context_id, parent_execution_id=run, root_execution_id=run, project_id="px", session_id=run, revision=state["sequence"], epoch=epoch, generation_vector_sha256=None, authority_reference_sha256=digest(hashes), effect_budget_sha256="d" * 64, cancellation_scope_id=run, deadline_utc=deadline, actor_id="fixture-owner", provider_id=None, trace_root_id=run)
    execution = "workflow-effect-" + digest({"run_id": run, "node_id": node, "workflow_version": "1.0.0", "authority": hashes})[:40]
    key = "workflow-node-effect:" + digest({"run_id": run, "node_id": node, "effect": "execute", "scope": "runtime"})
    EffectIntentLedger(tmp_path).intend(idempotency_key=key, execution_id=execution, effect="execute", scopes=["runtime"])
    ScopeLeaseStore(tmp_path).acquire(lease_id="lease:fixture", execution_id=execution, effect="execute", scopes=["runtime"], reason="disposable effect-boundary fixture", expires_utc=deadline)
    binding = {"idempotency_key": key, "execution_id": execution, "effect": "execute", "scopes": ["runtime"], "lease_id": "lease:fixture"}
    task = {"run_id": run, "node_id": node, "attempt": 1, "workflow_id": "workflow:fixture", "execution_context": context.as_dict(), "authority_record_hashes": hashes, "prepared_effect_intents": [binding]}
    return tmp_path, control, task, [{"effects": ["execute"], "scope_roots": ["runtime"]}]


def test_exact_native_running_intent_and_scope_lease_are_required(custody):
    root, _, task, grants = custody
    assert _verify_prepared_effect_intents(root, task, grants) == tuple(task["prepared_effect_intents"])


@pytest.mark.parametrize("mutation", ["missing", "scope", "lease", "context", "cancelled", "committed"])
def test_workflow_effect_substitutions_fail_closed(custody, mutation):
    root, control, task, grants = custody
    binding = task["prepared_effect_intents"][0]
    if mutation == "missing":
        task["prepared_effect_intents"] = []
    elif mutation == "scope":
        binding["scopes"] = ["other"]
    elif mutation == "lease":
        binding["lease_id"] = "caller-asserted-lease"
    elif mutation == "context":
        task["execution_context"]["revision"] += 1
    elif mutation == "cancelled":
        control.transition(task["run_id"], "cancel_requested", actor="fixture-owner", approved=True)
    else:
        EffectIntentLedger(root).commit(idempotency_key=binding["idempotency_key"], execution_id=binding["execution_id"], result_sha256="f" * 64)
    with pytest.raises((PermissionError, ValueError)):
        _verify_prepared_effect_intents(root, task, grants)


def test_native_committed_effect_requires_exact_settlement_digest(custody):
    root, _, task, grants = custody
    binding = task["prepared_effect_intents"][0]
    ledger = EffectIntentLedger(root)
    ledger.commit(idempotency_key=binding["idempotency_key"], execution_id=binding["execution_id"], result_sha256="f" * 64)
    assert _verify_prepared_effect_intents(root, task, grants, native_results={("execute", "runtime"): "f" * 64})
    with pytest.raises(PermissionError):
        _verify_prepared_effect_intents(root, task, grants, native_results={("execute", "runtime"): "0" * 64})


@pytest.mark.parametrize("mutation", [None, "in-flight", "digest", "duplicate", "missing"])
def test_parent_observes_native_commit_instead_of_manufacturing_one(custody, monkeypatch, mutation):
    from runtime.workflow_studio import WorkflowStudio
    root, _, task, _ = custody
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(root.parent / (root.name + "-keys")))
    studio = WorkflowStudio(root)
    binding = task["prepared_effect_intents"][0]
    ledger = EffectIntentLedger(root)
    if mutation != "in-flight":
        ledger.commit(idempotency_key=binding["idempotency_key"], execution_id=binding["execution_id"], result_sha256="f" * 64)
    outcome = {**binding, "result_sha256": "0" * 64 if mutation == "digest" else "f" * 64}
    rows = [] if mutation == "missing" else [outcome, outcome] if mutation == "duplicate" else [outcome]
    if mutation is None:
        assert studio._settle_node_effect_intents([binding], {"completed_effects": rows}) == [outcome]
    else:
        with pytest.raises(RuntimeError):
            studio._settle_node_effect_intents([binding], {"completed_effects": rows})
    if mutation == "in-flight":
        assert ledger.fence(binding["idempotency_key"])["disposition"] == "in_flight"


def test_parent_records_intent_before_dispatch_and_fences_unknown_closure(custody, monkeypatch):
    from runtime.workflow_studio import WorkflowStudio
    from runtime.studio_run_control import DurableControlSignal
    from tests.test_workflow_studio import fixture
    from runtime.scope_lease import ScopeLeaseStore
    root, _, task, _ = custody
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(root.parent / (root.name + "-keys")))
    studio = WorkflowStudio(root)
    definition, _, _ = fixture()
    node = definition.nodes[0]
    # Separate fixture scope from the existing native lease above.
    monkeypatch.setattr(studio, "_node_authority", lambda *args: ({"native": "a" * 64}, [("fixture-output", "exclusive", "write")]))
    monkeypatch.setattr(studio.authority, "resolve_executor", lambda _: ({"adapter_id": "model-group"}, "controlled-boundary-fixture"))
    seen = []
    def uncertain(*args):
        bindings = args[-1]
        binding = bindings[0]
        assert EffectIntentLedger(root).fence(binding["idempotency_key"])["disposition"] == "in_flight"
        assert any(row.lease_id == binding["lease_id"] for row in ScopeLeaseStore(root).active(effect="write"))
        seen.append(binding)
        # A worker-shaped assertion cannot release native scope exclusion.
        raise RuntimeError('{"tree_closed": true}')
    monkeypatch.setattr(studio, "_run_node_attempt", uncertain)
    with pytest.raises(RuntimeError, match="reconciliation"):
        studio._run_node(definition, node, {}, task["run_id"], 1, DurableControlSignal(studio.run_control, task["run_id"]), {})
    assert EffectIntentLedger(root).fence(seen[0]["idempotency_key"])["disposition"] == "failed"
    assert ScopeLeaseStore(root).quarantines()
    with pytest.raises(RuntimeError, match="reconciliation"):
        studio._run_node(definition, node, {}, task["run_id"], 2, DurableControlSignal(studio.run_control, task["run_id"]), {})
    assert len(seen) == 1


def test_unused_permission_is_not_a_fabricated_pure_adapter_effect(custody):
    root, _, task, grants = custody
    task["adapter_id"] = "increment"
    task["prepared_effect_intents"] = []
    assert _verify_prepared_effect_intents(root, task, grants) == ()
