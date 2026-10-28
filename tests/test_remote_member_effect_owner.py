"""Actual prepared consumer failures never become complete provider custody."""
import pytest
from tests.test_remote_model_bridge import configured
from tests.test_remote_group_effect_owner import remote_group_fixture
from runtime.effect_intent import EffectIntentLedger


def run(f):
    return f['controller'].execute_governed_group(f['spec'], task_plan=f['plan'].as_dict(),
        placements=f['placements'], approval=True, member_executor=f['executor'],
        generation_observer=lambda: f['plan'].context_generation, evidence_resolver=f['resolver'],
        accepted_producers={'unit:producer'}, attestation_provider=None, workflow_effect_receipt=f['signed'])


@pytest.mark.parametrize('failure', ['transport', 'child-commit'])
def test_actual_provider_effect_uncertainty_withholds_parent_completion(configured, monkeypatch, failure):
    f = remote_group_fixture(configured, monkeypatch)
    if failure == 'transport':
        def fail_open(**request):
            raise OSError('controlled fixture transport failure')
        monkeypatch.setattr(f['transport'], 'open', fail_open)
    else:
        original = EffectIntentLedger.commit
        def fail_child(self, **kwargs):
            if kwargs['idempotency_key'].startswith('remote-provider-child:'):
                raise OSError('controlled native child settlement failure')
            return original(self, **kwargs)
        monkeypatch.setattr(EffectIntentLedger, 'commit', fail_child)
    result = run(f)
    assert result['control_state'] == 'failed'
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition'] == 'in_flight' for row in f['effects'])
    children = [row for row in f['ledger']._load()['intents'] if row['idempotency_key'].startswith('remote-provider-child:')]
    assert len(children) == 3 and all(row['state'] == 'in_flight' for row in children)
    assert not result['member_receipts']
    if failure == 'child-commit':
        assert len(f['transport'].calls) == 1


def test_cancelled_native_workflow_cannot_reach_transport(configured, monkeypatch):
    f = remote_group_fixture(configured, monkeypatch)
    f['control'].transition(f['context'].root_execution_id, 'cancel_requested', actor='human:owner', approved=True)
    with pytest.raises(PermissionError):
        run(f)
    assert not f['transport'].calls
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition'] == 'in_flight' for row in f['effects'])


def test_remote_service_cannot_be_dispatched_as_local_cpu(configured, monkeypatch):
    f = remote_group_fixture(configured, monkeypatch)
    original = f['executor']
    def wrong_device(invocation, **kwargs):
        return original(invocation, **{**kwargs, 'device': 'cpu'})
    f['executor'] = wrong_device
    result = run(f)
    assert result['control_state'] == 'failed' and not f['transport'].calls
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition'] == 'in_flight' for row in f['effects'])


def test_actual_provider_proof_cannot_be_rebound_to_another_native_workflow(configured, monkeypatch):
    from dataclasses import replace
    import hashlib
    from runtime.studio_authority import StudioAuthorityStore
    from runtime.remote_member_execution import verify_remote_workflow_effect_results
    f = remote_group_fixture(configured, monkeypatch)
    result = run(f)
    assert result['control_state'] == 'succeeded'
    outcomes = {model: receipt['outcome']['remote_provider_execution'] for model, receipt in result['member_receipts'].items()}
    assert verify_remote_workflow_effect_results(f['root'], f['plan'].as_dict(), outcomes, signed_task=f['signed'])
    authority = StudioAuthorityStore.open_existing(f['root'])
    task = authority.verify_receipt(f['signed'])
    fresh = f['control'].create(kind='workflow', subject_id=task['workflow_id'], version='1.0.0',
        owner='human:owner', revision_sha256='a' * 64, request_sha256='b' * 64)
    fresh = f['control'].transition(fresh['run_id'], 'running', actor='human:owner', approved=True)
    run_id = fresh['run_id']
    context = replace(f['context'], execution_id='workflow-node-' + hashlib.sha256(
        f"{run_id}\0{task['node_id']}\0{task['attempt']}\0{1}".encode()).hexdigest()[:40],
        root_execution_id=run_id, parent_execution_id=run_id, session_id=run_id,
        cancellation_scope_id=run_id, trace_root_id=run_id, revision=fresh['sequence'])
    task.update(run_id=run_id, execution_context=context.as_dict())
    signed_fresh = authority.sign_receipt(task)
    # Negative readback: no second provider call or fabricated second-run effects.
    with pytest.raises(PermissionError, match='differs from exact prepared member'):
        verify_remote_workflow_effect_results(f['root'], f['plan'].as_dict(), outcomes, signed_task=signed_fresh)
    assert len(f['transport'].calls) == 1
    # Actual older effects do not authorize settlement against a changed profile.
    import json
    from runtime.remote_provider_profiles import CONFIG
    path = f['root'] / CONFIG
    profile_config = authority.verify_receipt(json.loads(path.read_text()))
    profile_config['profiles'][0]['model_revision'] = 'new-approved-fixture-declaration'
    path.write_text(json.dumps(authority.sign_receipt(profile_config)))
    with pytest.raises(PermissionError, match='profile/grant is no longer current'):
        verify_remote_workflow_effect_results(f['root'], f['plan'].as_dict(), outcomes, signed_task=f['signed'])
    assert len(f['transport'].calls) == 1
