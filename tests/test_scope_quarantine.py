"""Durable scope quarantine; native Windows process fixtures are disposable."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace
import pytest
from runtime.scope_lease import ScopeLeaseStore, ScopeLeaseError
from runtime.execution_context import ExecutionContext
from runtime.resource_lifecycle import ResourceManager, ResourceStatus, RunState
from runtime.process_supervisor import ProcessSupervisor

NOW = "2026-10-07T12:00:00+00:00"
EXPIRY = "2026-10-07T12:00:01+00:00"
LATER = "2026-10-07T12:00:02+00:00"
FUTURE = "2026-10-07T12:01:00+00:00"

def _acquire(store, *, lease_id="lease:original", execution_id="execution:original", effect="write", scopes=("workspace:demo",), now=NOW, expiry=EXPIRY):
    return store.acquire(lease_id=lease_id, execution_id=execution_id, effect=effect,
        scopes=scopes, reason="disposable native fixture", expires_utc=expiry, now_utc=now)

def test_ordinary_expired_lease_is_still_reclaimable(tmp_path):
    store = ScopeLeaseStore(tmp_path)
    _acquire(store)
    result = _acquire(store,lease_id="lease:new",execution_id="execution:new",now=LATER,expiry=FUTURE)
    assert result.execution_id == "execution:new"
    assert store.quarantines() == ()

@pytest.mark.parametrize("scope", ["workspace:demo", "workspace:demo/child", "workspace:demo/child/nested"])
def test_unknown_custody_blocks_fresh_execution_after_expiry(tmp_path,scope):
    store = ScopeLeaseStore(tmp_path)
    _acquire(store)
    quarantine_id = store.quarantine_unresolved(lease_id="lease:original",execution_id="execution:original",
        run_id="run:unknown",node_id="node:unknown",authority_reference_sha256="a"*64,attempt=1)
    # A new owner view, not only an in-memory exclusion, observes the quarantine.
    restored = ScopeLeaseStore(tmp_path)
    assert restored.active(effect="write",now_utc=LATER) == ()
    with pytest.raises(ScopeLeaseError,match="quarantined"):
        _acquire(restored,lease_id="lease:new",execution_id="execution:new",scopes=(scope,),now=LATER,expiry=FUTURE)
    assert restored.quarantines()[0]["quarantine_id"] == quarantine_id
    with pytest.raises(ScopeLeaseError,match="independent native closure"):
        restored.release(lease_id="lease:original",execution_id="execution:original")
    # Scope/effect isolation remains intact.
    _acquire(restored,lease_id="lease:other",execution_id="execution:other",scopes=("workspace:other",),now=LATER,expiry=FUTURE)
    _acquire(restored,lease_id="lease:read",execution_id="execution:read",effect="read",now=LATER,expiry=FUTURE)
    with pytest.raises(ScopeLeaseError,match="native resource owner"):
        restored.resolve_quarantine(lease_id="lease:original",execution_id="execution:original",manager=SimpleNamespace(tree_closed=True))


def _context(expiry):
    return ExecutionContext(execution_id="execution:worker",parent_execution_id="run:unit",
        root_execution_id="run:unit",project_id="project:unit",session_id="run:unit",revision=1,epoch=1,
        generation_vector_sha256=None,authority_reference_sha256="a"*64,effect_budget_sha256="b"*64,
        cancellation_scope_id="run:unit",deadline_utc=expiry,actor_id="human:unit",provider_id=None,
        trace_root_id="run:unit",workflow_adapter_revision="c"*64)

@pytest.mark.skipif(os.name != "nt",reason="native suspended Windows Job custody required")
@pytest.mark.parametrize("tamper", [None,"signature","identity","acknowledgment"])
def test_actual_native_job_closure_releases_only_matching_quarantine(tmp_path,tamper):
    manager = ResourceManager(tmp_path/".agentic_engineering_os_px/studios/unit/resources.json")
    supervisor = ProcessSupervisor(manager)
    store = ScopeLeaseStore(tmp_path)
    now = datetime.now(timezone.utc)
    expiry = (now+timedelta(seconds=20)).isoformat()
    late = (now+timedelta(seconds=30)).isoformat()
    later_expiry = (now+timedelta(seconds=60)).isoformat()
    context = _context(expiry)
    _acquire(store,now=now.isoformat(),expiry=expiry)
    retained = {}
    def before_release(custody):
        retained["resource_id"] = custody.parent_resource_id
        retained["job_id"] = custody.job_object_id
        retained["quarantine_id"] = store.quarantine(lease_id="lease:original",execution_id="execution:original",
            execution_context=context,manager=manager,resource_id=custody.parent_resource_id)
        with pytest.raises(ScopeLeaseError,match="quarantined"):
            _acquire(store,lease_id="lease:blocked",execution_id="execution:blocked",now=late,expiry=later_expiry)
        # A resource's old reclaimed bit, without independently produced proof,
        # is insufficient even if supplied by a native manager record update.
        record = manager.ledger.get(custody.parent_resource_id)
        manager.update(record.resource_id,active=False,status=ResourceStatus.RECLAIMED.value)
        with pytest.raises(FileNotFoundError):
            store.resolve_quarantine(lease_id="lease:original",execution_id="execution:original",manager=manager)
        manager.update(record.resource_id,active=record.active,status=record.status)
    budget={"startup_timeout_seconds":5,"idle_timeout_seconds":5,"total_timeout_seconds":10,
        "graceful_shutdown_seconds":1,"force_shutdown_seconds":3,"stdout_limit_bytes":1024,"stderr_limit_bytes":1024}
    result = supervisor.run([sys.executable,"-B","-c","print('native disposable work')"],cwd=tmp_path,
        action={"action_id":"unit:quarantine","effects":["process"],"allowed_effects":["process"],
            "target_paths":[str(tmp_path)],"owned_paths":[str(tmp_path)],"budget":budget,"limits":budget,
            "approval":True,"policy_override_requested":False},project_id="project:unit",run_id="run:unit",
        lane_id="node:unit",creator="human:unit",execution_context=context,
        assert_execution_current=lambda current: None,before_release=before_release)
    assert result.tree_closed and result.exit_code == 0
    resource_id = retained["resource_id"]
    proof = manager.read_physical_process_tree_closure(resource_id,project_root=tmp_path,job_object_id=retained["job_id"])
    path = manager._physical_closure_path(tmp_path,proof["identity"])
    original_bytes = path.read_bytes()
    original_record = manager.ledger.get(resource_id)
    if tamper == "signature":
        document=json.loads(original_bytes)
        document["identity"]["run_id"]="run:forged"
        path.write_text(json.dumps(document))
    elif tamper == "identity":
        manager.update(resource_id,process_identity="process-start:"+"f"*64)
    if tamper == "acknowledgment":
        # Model an acknowledgment lost after actual native zero-member proof;
        # no physical proof bytes or live process observations are fabricated.
        manager.update(resource_id,active=True,status=ResourceStatus.CLEANUP_PENDING.value,
            run_state=RunState.RECOVERABLE.value)
        with pytest.raises(PermissionError,match="not acknowledged"):
            manager.read_physical_process_tree_closure(resource_id,project_root=tmp_path,job_object_id=retained["job_id"])
    if tamper in {"signature","identity"}:
        with pytest.raises((ValueError,PermissionError)):
            store.resolve_quarantine(lease_id="lease:original",execution_id="execution:original",manager=manager)
        assert store.quarantines()
        with pytest.raises(ScopeLeaseError,match="quarantined"):
            _acquire(store,lease_id="lease:blocked2",execution_id="execution:blocked2",now=late,expiry=later_expiry)
        path.write_bytes(original_bytes)
        manager.update(resource_id,process_identity=original_record.process_identity)
    # Restored owner and scope store consume the actually produced retained proof.
    restored_manager = ResourceManager(manager.ledger.path)
    restored = ScopeLeaseStore(tmp_path)
    sha = restored.resolve_quarantine(lease_id="lease:original",execution_id="execution:original",manager=restored_manager)
    assert sha == proof["receipt_sha256"] and restored.quarantines() == ()
    if tamper == "acknowledgment":
        recovered = restored_manager.ledger.get(resource_id)
        assert not recovered.active and recovered.status==ResourceStatus.RECLAIMED.value
        assert recovered.run_state==RunState.ABANDONED.value
        assert recovered.cleanup_result=="physical_tree_closure:"+sha
    assert restored.resolve_quarantine(lease_id="lease:original",execution_id="execution:original",manager=restored_manager) == sha
    assert restored.release(lease_id="lease:original",execution_id="execution:original")
    _acquire(restored,lease_id="lease:new",execution_id="execution:new",now=late,expiry=later_expiry)
    rows=restored._load()
    tombstone=next(row for row in rows if row["lease_id"]=="lease:original")
    assert tombstone["quarantine"]["state"]=="resolved"
    assert tombstone["quarantine"]["closure_receipt_sha256"]==sha


@pytest.mark.parametrize("handle", [True,False,None,-1,0,"123"])
def test_native_handle_type_repair_preserves_invalid_handle_rejection(handle):
    from runtime.process_supervisor import _WindowsJob
    job = object.__new__(_WindowsJob)
    with pytest.raises(OSError,match="handle is unavailable"):
        job.verify_owned_process(SimpleNamespace(_handle=handle,pid=123))


def test_workflow_unknown_failure_fences_actual_next_execution_before_intent(tmp_path,monkeypatch):
    from tests.test_workflow_studio import _effect_fence_studio
    from runtime.workflow_studio import _WorkflowEffectReconciliationRequired
    from runtime.effect_intent import EffectIntentLedger
    from runtime.studio_models import digest
    import runtime.scope_lease as lease_module
    import runtime.workflow_studio as workflow_module
    studio, definition, node = _effect_fence_studio(tmp_path,monkeypatch)
    calls=[]
    def unknown_worker(*args):
        calls.append(args[-1])
        raise RuntimeError("unit fixture: physical closure cannot be established")
    monkeypatch.setattr(studio,"_run_node_attempt",unknown_worker)
    with pytest.raises(_WorkflowEffectReconciliationRequired):
        studio._run_node(definition,node,{},"run:old",1,None,None)
    quarantine = ScopeLeaseStore(tmp_path).quarantines()[0]
    assert quarantine["binding"]["custody"] is None
    future = datetime.now(timezone.utc)+timedelta(minutes=5)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return future if tz is not None else future.replace(tzinfo=None)
    monkeypatch.setattr(lease_module,"datetime",Clock)
    monkeypatch.setattr(workflow_module,"datetime",Clock)
    with pytest.raises(_WorkflowEffectReconciliationRequired):
        studio._run_node(definition,node,{},"run:fresh",1,None,None)
    assert len(calls)==1
    key="workflow-node-effect:"+digest({"run_id":"run:fresh","node_id":node.node_id,
        "effect":"write","scope":"workspace:demo"})
    assert EffectIntentLedger(tmp_path).fence(key)["disposition"]=="new"


@pytest.mark.skipif(os.name!="nt",reason="native suspended Windows Job custody required")
def test_actual_workflow_worker_quarantine_resolves_from_native_custody_not_effect_claim(tmp_path):
    from tests.test_workflow_studio import fixture
    from runtime.workflow_studio import WorkflowStudio,_WorkflowEffectReconciliationRequired
    from runtime.studio_run_control import DurableControlSignal
    from runtime.effect_intent import EffectIntentLedger
    definition, bindings, grants = fixture()
    grant=replace(grants[0],effects=("write",))
    studio=WorkflowStudio(tmp_path)
    studio.register_authority(bindings[:1],[grant],{bindings[0].binding_id:"increment"})
    for index in range(2):
        run=studio.run_control.create(kind="workflow",subject_id=definition.workflow_id,
            version=definition.version,owner=definition.owner,revision_sha256="a"*64,request_sha256="b"*64)
        run=studio.run_control.transition(run["run_id"],"running",actor=definition.owner,approved=True)
        with pytest.raises(_WorkflowEffectReconciliationRequired):
            studio._run_node(definition,definition.nodes[0],{"value":2},run["run_id"],1,
                DurableControlSignal(studio.run_control,run["run_id"]),None)
        # Pure arithmetic did not perform a workspace write, despite permission.
        assert ScopeLeaseStore(tmp_path).quarantines()==()
        assert ScopeLeaseStore(tmp_path).active(effect="write")==()
    rows=ScopeLeaseStore(tmp_path)._load()
    assert len(rows)==2 and all(row["quarantine"]["state"]=="resolved" for row in rows)
    assert all(row["quarantine"]["closure_receipt_sha256"] for row in rows)
    assert all(row["state"]=="failed" for row in EffectIntentLedger(tmp_path)._load()["intents"])
    assert len(list((tmp_path/".agentic_engineering_os_px/runtime-core/process-tree-closures").glob("*.json")))==2


def test_known_unsupported_prelaunch_does_not_invent_unknown_custody(tmp_path,monkeypatch):
    from tests.test_workflow_studio import fixture
    import runtime.workflow_studio as workflow_module
    from runtime.workflow_studio import WorkflowStudio,_WorkflowEffectReconciliationRequired
    from runtime.effect_intent import EffectIntentLedger
    definition,bindings,grants=fixture()
    studio=WorkflowStudio(tmp_path)
    studio.register_authority(bindings[:1],[replace(grants[0],effects=("write",))],
        {bindings[0].binding_id:"increment"})
    calls=[]
    monkeypatch.setattr(studio.supervisor,"run",lambda *args,**kwargs:calls.append("launch"))
    # Only this owner's platform capability is simulated; global filesystem/OS
    # modules retain the actual host so no native identity proof is fabricated.
    monkeypatch.setattr(workflow_module,"os",SimpleNamespace(name="posix"))
    with pytest.raises(_WorkflowEffectReconciliationRequired):
        studio._run_node(definition,definition.nodes[0],{"value":2},"run:unsupported",1,None,None)
    assert calls==[]
    assert ScopeLeaseStore(tmp_path).quarantines()==()
    assert ScopeLeaseStore(tmp_path).active(effect="write")==()
    assert EffectIntentLedger(tmp_path)._load()["intents"][0]["state"]=="failed"


def test_stored_resolution_claim_without_native_proof_never_admits_overlap(tmp_path):
    store=ScopeLeaseStore(tmp_path)
    _acquire(store)
    store.quarantine_unresolved(lease_id="lease:original",execution_id="execution:original",
        run_id="run:unknown",node_id="node:unknown",authority_reference_sha256="a"*64,attempt=1)
    rows=store._load()
    # Explicit disposable corrupted owner-state fixture, not closure evidence.
    rows[0]["quarantine"].update(state="resolved",closure_receipt_sha256="f"*64)
    store._store(rows)
    with pytest.raises(ScopeLeaseError,match="no native physical closure custody"):
        _acquire(ScopeLeaseStore(tmp_path),lease_id="lease:fresh",execution_id="execution:fresh",now=LATER,expiry=FUTURE)
