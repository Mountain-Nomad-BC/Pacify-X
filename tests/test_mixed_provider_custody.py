import pytest
from tests.test_remote_model_bridge import configured
from tests.mixed_provider_fixture import mixed_fixture
from runtime.remote_member_execution import verify_remote_workflow_effect_results


def test_local_native_writer_proof_before_mixed_guard_removal(configured,monkeypatch):
    f=mixed_fixture(configured,monkeypatch)
    receipt=f['controller'].execute_governed_plan(f['spec'],task_plan=f['plan'].as_dict(),placement=f['placements'][f['local_id']],approval=True,gpu_fn=None,cpu_fn=None,current_context_generation=f['plan'].context_generation,member_executor=f['executor'])
    assert receipt['outcome']['status']=='succeeded'
    evidence=receipt['outcome']['local_provider_execution']
    assert evidence['schema_version']=='px.local-member-provider-evidence/1.0'
    assert 'value' not in evidence and len(f['opener'].requests)==1
    with pytest.raises(PermissionError,match='denominator'):
        verify_remote_workflow_effect_results(f['root'],f['plan'].as_dict(),{f['local_id']:evidence},signed_task=f['signed'])
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition']=='in_flight' for row in f['effects'])


def test_actual_three_member_group_observes_every_shared_writer(configured,monkeypatch):
    from tests.test_remote_member_effect_owner import run
    f=mixed_fixture(configured,monkeypatch)
    result=run(f)
    assert result['control_state']=='succeeded',result['member_failures']
    assert len(result['member_receipts'])==3 and len(f['transport'].calls)==2 and len(f['opener'].requests)==1
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition']=='committed' for row in f['effects'])
    outcomes={model:row['outcome'].get('remote_provider_execution',row['outcome'].get('local_provider_execution')) for model,row in result['member_receipts'].items()}
    verify_remote_workflow_effect_results(f['root'],f['plan'].as_dict(),outcomes,signed_task=f['signed'])
    before=(len(f['transport'].calls),len(f['opener'].requests))
    with pytest.raises(PermissionError,match='exact native in-flight fence'):
        run(f)
    assert (len(f['transport'].calls),len(f['opener'].requests))==before
    del outcomes[f['local_id']]
    with pytest.raises(PermissionError,match='denominator'):
        verify_remote_workflow_effect_results(f['root'],f['plan'].as_dict(),outcomes,signed_task=f['signed'])


@pytest.mark.parametrize('failure',['missing-local-receipt','local-cancel'])
def test_missing_or_cancelled_local_writer_cannot_commit_shared_parents(configured,monkeypatch,failure):
    from tests.test_remote_member_effect_owner import run
    f=mixed_fixture(configured,monkeypatch)
    original=f['executor']
    def execute(invocation,**kwargs):
        if invocation.model_id==f['local_id']:
            if failure=='missing-local-receipt':return 'unproved local output'
            kwargs['cancellation_token']=lambda:True
        return original(invocation,**kwargs)
    f['executor']=execute
    result=run(f)
    assert result['control_state']=='failed' and f['local_id'] in result['member_failures']
    assert f['opener'].requests==[]
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition']=='in_flight' for row in f['effects'])


def test_unsigned_local_policy_is_refused_before_any_provider(configured,monkeypatch):
    import os,json
    from pathlib import Path
    from tests.test_remote_member_effect_owner import run
    f=mixed_fixture(configured,monkeypatch)
    path=Path(os.environ['PX_PROVIDER_EXECUTION_POLICY'])
    path.write_text(json.dumps(f['authority'].verify_receipt(json.loads(path.read_text()))))
    with pytest.raises((PermissionError,ValueError)):
        run(f)
    assert f['transport'].calls==[] and f['opener'].requests==[]
