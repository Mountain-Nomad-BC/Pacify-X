"""Native exact-owner mirrors; no production certification or broad refresh."""
import json
import pytest
from runtime.operational_gap_ledger import append_event
from runtime.guarded_registry_projection import publish_guarded_registry_projection,publish_guarded_studio_operation_mirror,GuardedProjectionError
from scripts.reconcile_studio_operation_projections import reconcile
from tests.test_operational_gap_ledger import initialize,card,evidence

@pytest.fixture
def native(tmp_path):
    initialize(tmp_path);append_event(tmp_path,"card_discovered",card(),actor="unit")
    checkpoint=append_event(tmp_path,"work_checkpoint",{"active_gap_id":"PX-GAP-0001","learned":"Exact disposable mirror owner.","next_action":card()["next_action"],"unresolved_branch_gap_ids":[],"newly_discovered_gap_ids":[],"evidence":evidence("unit")},actor="unit")
    admission=append_event(tmp_path,"work_admitted",{"gap_id":"PX-GAP-0001","checkpoint_event_id":checkpoint["event_id"],"session_id":"pxsession.mirror-unit","expires_utc":"2099-01-01T00:00:00Z","effect_scopes":[{"effect":"write","scope":["registry","runtime/studio_operations.json","extension/resources/studio-operations.json",".agentic_engineering_os_px/runtime-core",".agentic_engineering_os_px/resource-lifecycle"]},{"effect":"read","scope":["registry/studio_operations.json"]}],"authority":"Disposable native mirror fixture only.","expected_effect":"Exact two operation contract mirrors.","rollback":"Retain unit source until teardown.","evidence":evidence("unit")},actor="unit")
    image={"schema_version":"px.studio-operation-contract/1.0","kinds":{"skill":["intake-foundry-candidate"]}}
    publish_guarded_registry_projection(tmp_path,"registry/studio_operations.json",image,admission_event_id=admission["event_id"])
    return tmp_path,admission["event_id"]

def test_real_reconcile_uses_native_two_mirror_owner_and_exact_bytes(native):
    root,event=native
    result=reconcile(root,check=False,admission_event_id=event)
    assert result["valid"] is True
    expected=(root/"registry/studio_operations.json").read_bytes()
    assert (root/"runtime/studio_operations.json").read_bytes()==expected
    assert (root/"extension/resources/studio-operations.json").read_bytes()==expected
    assert reconcile(root,check=True)["changed"]==[]
    from runtime.effect_intent import EffectIntentLedger
    assert all(x["state"]=="committed" for x in EffectIntentLedger(root)._load()["intents"])

def test_missing_admission_cannot_write_either_mirror(native):
    root,event=native
    with pytest.raises(GuardedProjectionError,match="explicit current"):
        reconcile(root,check=False)
    assert not (root/"runtime/studio_operations.json").exists()
    assert not (root/"extension/resources/studio-operations.json").exists()
    assert reconcile(root,check=True)["valid"] is False

def test_unlisted_target_does_not_broaden_registry_boundary(tmp_path):
    with pytest.raises(GuardedProjectionError,match="exact declared"):
        publish_guarded_studio_operation_mirror(tmp_path,"runtime/unlisted.json",admission_event_id="none")
    with pytest.raises(GuardedProjectionError,match="registry JSON"):
        publish_guarded_registry_projection(tmp_path,"runtime/studio_operations.json",{},admission_event_id="none")
    assert list(tmp_path.iterdir())==[]


def test_revoked_live_lease_during_staging_prevents_replace(native,monkeypatch):
    from runtime.scope_lease import ScopeLeaseStore
    import runtime.studio_models as models
    root,event=native;original=models.write_json_atomic
    def revoke(path,value):
        original(path,value)
        if path.name=="projection.json":
            store=ScopeLeaseStore(root);lease=store.active(effect="write")[0]
            store.release(lease_id=lease.lease_id,execution_id=lease.execution_id)
    monkeypatch.setattr(models,"write_json_atomic",revoke)
    with pytest.raises(GuardedProjectionError,match="expired or changed"):
        publish_guarded_studio_operation_mirror(root,"runtime/studio_operations.json",admission_event_id=event)
    assert not (root/"runtime/studio_operations.json").exists()


def test_held_native_lease_during_staging_is_not_healthy_owner(native,monkeypatch):
    from runtime.scope_lease import ScopeLeaseStore
    import runtime.studio_models as models
    root,event=native;original=models.write_json_atomic
    def quarantine(path,value):
        original(path,value)
        if path.name=="projection.json":
            store=ScopeLeaseStore(root);lease=store.active(effect="write")[0]
            store.quarantine_unresolved(lease_id=lease.lease_id,execution_id=lease.execution_id,
                run_id=lease.execution_id,node_id="unit-native-owner",authority_reference_sha256="a"*64,attempt=1)
    monkeypatch.setattr(models,"write_json_atomic",quarantine)
    with pytest.raises(GuardedProjectionError,match="unresolved quarantine"):
        publish_guarded_studio_operation_mirror(root,"runtime/studio_operations.json",admission_event_id=event)
    assert not (root/"runtime/studio_operations.json").exists()
    assert ScopeLeaseStore(root).quarantines(effect="write")


def test_held_lease_after_real_replace_never_commits(native,monkeypatch):
    from pathlib import Path
    from runtime.scope_lease import ScopeLeaseStore
    from runtime.effect_intent import EffectIntentLedger
    root,event=native;target=root/"runtime/studio_operations.json";original=Path.read_bytes;seen=[]
    def observed(path):
        raw=original(path)
        if path==target and not seen:
            seen.append(True);store=ScopeLeaseStore(root);lease=store.active(effect="write")[0]
            store.quarantine_unresolved(lease_id=lease.lease_id,execution_id=lease.execution_id,
                run_id=lease.execution_id,node_id="unit-native-owner",authority_reference_sha256="a"*64,attempt=1)
        return raw
    monkeypatch.setattr(Path,"read_bytes",observed)
    with pytest.raises(GuardedProjectionError,match="unresolved quarantine"):
        publish_guarded_studio_operation_mirror(root,"runtime/studio_operations.json",admission_event_id=event)
    assert target.exists()
    assert EffectIntentLedger(root)._load()["intents"][-1]["state"]=="in_flight"


def test_preexisting_held_overlap_rejects_before_any_mirror_output(native):
    from datetime import datetime,timedelta,timezone
    from runtime.scope_lease import ScopeLeaseStore
    root,event=native;store=ScopeLeaseStore(root)
    store.acquire(lease_id="other-held",execution_id="other-run",effect="write",
        scopes=("runtime/studio_operations.json",),reason="native unit uncertainty",
        expires_utc=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
    store.quarantine_unresolved(lease_id="other-held",execution_id="other-run",run_id="other-run",
        node_id="other-node",authority_reference_sha256="a"*64,attempt=1)
    with pytest.raises(ValueError,match="quarantine"):
        publish_guarded_studio_operation_mirror(root,"runtime/studio_operations.json",admission_event_id=event)
    assert not (root/"runtime/studio_operations.json").exists()
