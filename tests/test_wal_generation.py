from __future__ import annotations

import hashlib
import json

import pytest

from runtime.wal_generation import WalGeneration, immutable_manifest_digest, seal
from runtime.wal_transaction import WalConflictError, WalIntegrityError
from runtime.wal_transaction import JsonArtifact, JsonWal
from runtime.wal_ownership import WalOwnership


def test_fleet_registration_commit_refusal_does_not_publish_orphan_event(tmp_path, monkeypatch):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)
    def refuse(*args, **kwargs):
        raise RuntimeError('refuse fleet commit before effects')
    monkeypatch.setattr(coordinator.wal, 'commit', refuse)
    with pytest.raises(RuntimeError, match='refuse fleet commit'):
        _register(coordinator)
    replay = coordinator.bus.replay()
    assert replay['valid']
    assert replay['events'] == []
    assert not coordinator._registry_path.exists()


def _generation(tmp_path):
    journal = tmp_path / 'wal'
    journal.mkdir()
    owner = WalGeneration(journal)
    owner.initialize('a' * 64)
    return owner


def test_fleet_registration_stale_registry_refuses_event(tmp_path, monkeypatch):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)
    original = coordinator.bus._publish_with_projection

    def raced(*args, **kwargs):
        coordinator._registry_path.write_text('{"external": true}', encoding='utf-8')
        return original(*args, **kwargs)

    monkeypatch.setattr(coordinator.bus, '_publish_with_projection', raced)
    with pytest.raises(WalConflictError):
        _register(coordinator)
    assert coordinator.bus.replay()['events'] == []
    assert coordinator._registry_path.read_text() == '{"external": true}'


def test_fleet_projection_builder_failure_precedes_event_effects(tmp_path, monkeypatch):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)

    def refuse(value):
        raise ValueError('invalid coupled projection')

    monkeypatch.setattr(coordinator, '_validate_state', refuse)
    with pytest.raises(ValueError, match='invalid coupled projection'):
        _register(coordinator)
    assert coordinator.bus.replay()['events'] == []
    assert not coordinator._registry_path.exists()


def test_fleet_registration_uses_one_transaction_for_event_and_state(tmp_path, monkeypatch):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)
    commit = coordinator.wal.commit
    targets = []

    def record(artifacts, **kwargs):
        artifacts = tuple(artifacts)
        targets.append({a.path for a in artifacts})
        return commit(artifacts, **kwargs)

    monkeypatch.setattr(coordinator.wal, 'commit', record)
    registered = _register(coordinator)
    assert len(targets) == 1
    assert coordinator._registry_path in targets[0]
    assert coordinator._state_path('pacify-x', 'agent-a', 'session-a') in targets[0]
    assert coordinator.bus.root / 'events' / '00000001.json' in targets[0]
    assert coordinator.reconstruct_session('pacify-x', 'agent-a', 'session-a') == registered


def _activated_fleet(tmp_path):
    from tests.test_agent_session_coordinator import _coordinator
    coordinator = _coordinator(tmp_path)
    domains = [dict(path='operation-bus/' + part, kind='subtree')
               for part in ('events', 'receipts', '.authority', 'projections')]
    domains += [dict(path='operation-bus/' + part, kind='exact')
                for part in ('state.json', 'head.json')]
    domains += [dict(path='agent-sessions/registry.json', kind='exact'),
                dict(path='agent-sessions/sessions', kind='subtree')]
    WalOwnership.activate(tmp_path, [dict(journal='operation-bus/wal', domains=domains)])
    coordinator.wal.activate_generation(tmp_path)
    return coordinator


def test_fleet_transition_rejects_decision_generation_aba(tmp_path, monkeypatch):
    from tests.test_agent_session_coordinator import _register
    coordinator = _activated_fleet(tmp_path)
    registered = _register(coordinator)
    reconstruct = coordinator.reconstruct_session
    target = coordinator._state_path('pacify-x', 'agent-a', 'session-a')

    def raced(*args, **kwargs):
        state = reconstruct(*args, **kwargs)
        for image in ({'intermediate': True}, registered):
            coordinator.wal.commit([JsonArtifact('state', target, image)],
                                   expected_generation=coordinator.wal.capture_generation())
        return state

    monkeypatch.setattr(coordinator, 'reconstruct_session', raced)
    with pytest.raises((ValueError, WalConflictError), match='generation'):
        coordinator.heartbeat_session('pacify-x', 'agent-a', 'session-a',
                                      observed_at='2026-08-11T19:00:10Z')
    assert coordinator.bus.replay()['revision'] == 1


@pytest.mark.parametrize('boundary', ['target:0:published', 'target:6:published', 'target:7:published'])
def test_fleet_combined_interruption_recovers_registration(tmp_path, monkeypatch, boundary):
    from tests.test_agent_session_coordinator import _register
    coordinator = _activated_fleet(tmp_path)
    commit = coordinator.wal.commit

    def stop(label):
        if label == boundary:
            raise OSError('interrupted combined fleet publication')

    def interrupted(artifacts, **kwargs):
        return commit(artifacts, fault_injector=stop, **kwargs)

    monkeypatch.setattr(coordinator.wal, 'commit', interrupted)
    with pytest.raises(OSError, match='interrupted combined'):
        _register(coordinator)
    monkeypatch.setattr(coordinator.wal, 'commit', commit)
    state = coordinator.reconstruct_session('pacify-x', 'agent-a', 'session-a')
    replay = coordinator.bus.replay()
    assert replay['valid'] and replay['revision'] == 1
    assert state['last_event_id'] == replay['events'][0]['event']['event_id']
    assert coordinator.wal.inspect()['requires_recovery'] is False


def test_fleet_pending_legacy_journal_is_retained_and_refused(tmp_path):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)

    def stop(label):
        if label == 'target:0:published':
            raise OSError('legacy interruption')

    with pytest.raises(OSError):
        coordinator._legacy_wal.commit(
            [JsonArtifact('state', coordinator._registry_path, {'legacy': True})],
            fault_injector=stop,
        )
    before = {p: p.read_bytes() for p in coordinator._legacy_wal.journal_root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='pending legacy'):
        _register(coordinator)
    assert {p: p.read_bytes() for p in coordinator._legacy_wal.journal_root.rglob('*') if p.is_file()} == before
    assert not (coordinator.bus.root / 'events').exists()


def test_fleet_conflicting_catalog_owner_is_not_transferred(tmp_path):
    from tests.test_agent_session_coordinator import _coordinator, _register
    coordinator = _coordinator(tmp_path)
    WalOwnership.activate(tmp_path, [dict(
        journal='agent-sessions/.wal', domains=[
            dict(path='agent-sessions/registry.json', kind='exact'),
            dict(path='agent-sessions/sessions', kind='subtree'),
        ],
    )])
    before = (tmp_path / '.engineering-bootstrap/wal-ownership.json').read_bytes()
    with pytest.raises(ValueError, match='explicit producer adoption'):
        _register(coordinator)
    assert (tmp_path / '.engineering-bootstrap/wal-ownership.json').read_bytes() == before
    assert not coordinator._registry_path.exists()
    assert not (coordinator.bus.root / 'events').exists()


@pytest.mark.parametrize('reader', ['head', 'replay'])
def test_bus_read_refuses_changed_generation(tmp_path, monkeypatch, reader):
    from tests.test_agent_session_coordinator import _register
    coordinator = _activated_fleet(tmp_path)
    _register(coordinator)
    bus = coordinator.bus
    original = bus._state

    def changed():
        state = original()
        bus.wal.commit([JsonArtifact('state', bus._state_path, state)],
                       expected_generation=bus.wal.capture_generation())
        return state

    monkeypatch.setattr(bus, '_state', changed)
    with pytest.raises(WalConflictError, match='generation'):
        getattr(bus, reader)()


@pytest.mark.parametrize('operation', ['enable', 'capture'])
def test_observer_state_conflict_preserves_other_writer(tmp_path, monkeypatch, operation):
    from tests.test_operational_observers import _controller, _consent
    controller, backend = _controller(tmp_path)
    consent = _consent()
    target = controller._state_path(consent.observer_id)
    if operation == 'capture':
        controller.enable(consent)

    def race(*args):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"other_writer":true}', encoding='utf-8')
        return []

    monkeypatch.setattr(backend, 'start' if operation == 'enable' else 'read', race)
    with pytest.raises((RuntimeError, WalConflictError)):
        getattr(controller, operation)(consent)
    assert target.read_text() == '{"other_writer":true}'
    if operation == 'enable':
        assert backend.stopped


def test_doctor_immutable_receipt_refuses_existing_other_image(tmp_path):
    from pathlib import Path
    from tests.test_px_doctor import _sections, EVALUATED_AT
    from runtime.px_doctor import compose_doctor_report, retain_doctor_receipt
    report = compose_doctor_report(_sections('blocked'), evaluated_at=EVALUATED_AT)
    target = tmp_path / 'diagnostics/receipts' / (report['report_sha256'] + '.json')
    target.parent.mkdir(parents=True)
    target.write_text('{"other_writer":true}', encoding='utf-8')
    with pytest.raises((ValueError, WalConflictError)):
        retain_doctor_receipt(tmp_path, report, Path('diagnostics'))
    assert target.read_text() == '{"other_writer":true}'


def test_doctor_receipt_commits_exact_prepared_image(tmp_path, monkeypatch):
    from pathlib import Path
    from tests.test_px_doctor import _sections, EVALUATED_AT
    from runtime.px_doctor import compose_doctor_report, retain_doctor_receipt
    report = compose_doctor_report(_sections('blocked'), evaluated_at=EVALUATED_AT)
    original_report = json.loads(json.dumps(report))
    commit = JsonWal.commit

    def changed(wal, *args, **kwargs):
        report['sections']['coverage']['summary'] = 'changed after preparation'
        return commit(wal, *args, **kwargs)

    monkeypatch.setattr(JsonWal, 'commit', changed)
    result = retain_doctor_receipt(tmp_path, report, Path('diagnostics'))
    raw = (tmp_path / result['path']).read_bytes()
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw)['report'] == original_report


def test_fleet_registration_recovers_after_physical_child_exit(tmp_path):
    import os
    from pathlib import Path
    import sys
    from runtime.resource_lifecycle import ResourceManager
    from runtime.test_runner import run_test_command
    case = tmp_path / 'project'
    case.mkdir()
    coordinator = _activated_fleet(case)
    child = '''
import os, sys
from pathlib import Path
from tests.test_agent_session_coordinator import _coordinator, _register
coordinator = _coordinator(Path(sys.argv[1]))
commit = coordinator.wal.commit
def stop(label):
    if label == 'target:0:published':
        os._exit(91)
def interrupted(artifacts, **kwargs):
    return commit(artifacts, fault_injector=stop, **kwargs)
coordinator.wal.commit = interrupted
_register(coordinator)
'''
    result = run_test_command(
        [sys.executable, '-c', child, str(case)], cwd=Path(__file__).parents[1],
        environment=os.environ, resource_manager=ResourceManager(tmp_path / 'children.json'),
        run_id='fleet-registration-child-exit', lane_id='wal-fleet-recovery',
        timeout_seconds=20, manage_process_temp=True,
    )
    assert result['exit_code'] == 91, result.get('stderr')
    assert result['execution_started'] and result['process_tree_terminated']
    assert result['test_workspace']['reclaimed']
    assert not coordinator._registry_path.exists()
    state = coordinator.reconstruct_session('pacify-x', 'agent-a', 'session-a')
    replay = coordinator.bus.replay()
    assert replay['valid'] and replay['revision'] == 1
    assert state['last_event_id'] == replay['events'][0]['event']['event_id']


def _manifest(owner, transaction='test'):
    head = owner.read()
    return dict(schema_version='2.0', transaction_id=transaction, intent_sha256='b' * 64,
                generation=dict(epoch=head['epoch'], sequence=head['sequence'] + 1,
                                previous_token=head['sha256']),
                artifacts=[dict(path='state.json', before='old', after='new')])


def test_generation_allocates_before_effects_and_settles_exact_intent(tmp_path):
    owner = _generation(tmp_path)
    initial = owner.read()
    manifest = _manifest(owner)
    allocated = owner.allocate(manifest, expected_token=initial['sha256'])
    assert allocated['sequence'] == 1 and allocated['phase'] == 'allocated'
    with pytest.raises(WalIntegrityError):
        owner.settle_committed({**manifest, 'phase': 'committed'})
    owner.prepare_effects({**manifest, 'phase': 'prepared'})
    settled = owner.settle_committed({**manifest, 'phase': 'committed'})
    assert settled['phase'] == 'settled_committed'
    assert settled['manifest_binding'] == immutable_manifest_digest(manifest)
    assert owner.check_expected(settled['sha256']) == settled


def test_aborted_allocation_consumes_sequence_and_retains_disposition(tmp_path):
    owner = _generation(tmp_path)
    first = _manifest(owner)
    owner.allocate(first)
    aborted = owner.settle_aborted()
    assert json.loads((owner.root / 'aborted/00000000000000000001.json').read_bytes()) == aborted
    next_manifest = _manifest(owner, 'next')
    assert next_manifest['generation']['sequence'] == 2
    owner.allocate(next_manifest)
    assert owner.read()['sequence'] == 2


@pytest.mark.parametrize('phase', ['prepared', 'applying', 'committed'])
def test_phase_does_not_change_immutable_manifest_binding(tmp_path, phase):
    owner = _generation(tmp_path)
    manifest = _manifest(owner)
    owner.allocate(manifest)
    assert owner.bind({**manifest, 'phase': phase, 'manifest_sha256': 'c' * 64})['sequence'] == 1


@pytest.mark.parametrize('field', ['transaction_id', 'intent_sha256', 'artifacts', 'generation'])
def test_manifest_changes_cannot_gain_effect_authority(tmp_path, field):
    owner = _generation(tmp_path)
    manifest = _manifest(owner)
    owner.allocate(manifest)
    with pytest.raises(WalIntegrityError):
        owner.prepare_effects({**manifest, field: None})
    assert owner.read()['phase'] == 'allocated'


def test_aba_equal_intent_still_invalidates_prior_generation(tmp_path):
    owner = _generation(tmp_path)
    token = owner.read()['sha256']
    for tx in ['A', 'B', 'A-again']:
        manifest = _manifest(owner, tx)
        owner.allocate(manifest)
        owner.prepare_effects(manifest)
        owner.settle_committed({**manifest, 'phase': 'committed'})
    with pytest.raises(WalConflictError):
        owner.check_expected(token)
    assert owner.read()['sequence'] == 3


@pytest.mark.parametrize('name', ['head.json', 'marker.json'])
def test_missing_authority_is_not_recreated(tmp_path, name):
    owner = _generation(tmp_path)
    (owner.root / name).unlink()
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))
    with pytest.raises(WalIntegrityError):
        owner.read()
    with pytest.raises(WalIntegrityError):
        owner.initialize('a' * 64)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*')) == before


@pytest.mark.parametrize('value', [True, -1, 1.0, 2**63, '1'])
def test_resealed_invalid_sequence_is_rejected(tmp_path, value):
    owner = _generation(tmp_path)
    head = owner.read()
    (owner.root / 'head.json').write_text(json.dumps(seal({**head, 'sequence': value})))
    with pytest.raises(WalIntegrityError):
        owner.read()


def test_effects_possible_cannot_be_aborted(tmp_path):
    owner = _generation(tmp_path)
    manifest = _manifest(owner)
    owner.allocate(manifest)
    owner.prepare_effects(manifest)
    before = (owner.root / 'head.json').read_bytes()
    with pytest.raises(WalIntegrityError):
        owner.settle_aborted()
    assert (owner.root / 'head.json').read_bytes() == before


def test_read_only_absent_generation_has_no_effect(tmp_path):
    owner = WalGeneration(tmp_path / 'absent')
    with pytest.raises(WalIntegrityError):
        owner.read()
    assert list(tmp_path.iterdir()) == []


def test_activation_refuses_legacy_history(tmp_path):
    journal = tmp_path / 'wal'
    (journal / 'committed/old').mkdir(parents=True)
    with pytest.raises(WalIntegrityError):
        WalGeneration(journal).initialize('a' * 64)
    assert not (journal / 'generation').exists()


def test_interrupted_abort_keeps_sequence_and_can_finish(tmp_path):
    owner = _generation(tmp_path)
    owner.allocate(_manifest(owner))
    def stop(label):
        if label == 'generation:abort-disposition:published':
            raise OSError('injected abort interruption')
    with pytest.raises(OSError):
        owner.settle_aborted(fault_injector=stop)
    assert owner.read()['phase'] == 'allocated'
    assert owner.settle_aborted()['sequence'] == 1


def test_read_does_not_modify_valid_authority(tmp_path):
    owner = _generation(tmp_path)
    before = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
              for p in owner.root.rglob('*') if p.is_file()}
    owner.read()
    after = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
             for p in owner.root.rglob('*') if p.is_file()}
    assert after == before


def _activated_wal(root):
    WalOwnership.activate(root, [dict(journal='wal', domains=[dict(path='state.json', kind='exact')])])
    wal = JsonWal(root / 'wal', root)
    wal.activate_generation(root)
    return wal


def test_actual_transactions_detect_completed_aba_during_read_and_commit(tmp_path):
    wal = _activated_wal(tmp_path)
    target = tmp_path / 'state.json'
    wal.commit([JsonArtifact('state', target, {'value': 'A'})])
    snapshot = wal.read_consistent_images([target])
    def intervene(label):
        wal.commit([JsonArtifact('state', target, {'value': 'B'})])
        wal.commit([JsonArtifact('state', target, {'value': 'A'})])
    with pytest.raises(WalConflictError):
        wal.read_consistent_images([target], fault_injector=intervene)
    assert target.read_bytes() == snapshot['images']['state.json']
    with pytest.raises(WalConflictError):
        wal.commit([JsonArtifact('state', target, {'value': 'C'})], expected_generation=snapshot['generation_token'])
    assert json.loads(target.read_bytes()) == {'value': 'A'}


_GENERATION_BOUNDARIES = [
    'generation:allocated:staged', 'generation:allocated:published',
    'journal:transaction:created', 'journal:after:0',
    'manifest:prepared:staged', 'manifest:prepared:published',
    'manifest:applying:staged', 'manifest:applying:published',
    'generation:prepared_effects_possible:staged', 'generation:prepared_effects_possible:published',
    'target:0:staged', 'target:0:published',
    'manifest:committed:staged', 'manifest:committed:published',
    'journal:committed:published', 'generation:settled_committed:staged', 'generation:settled_committed:published',
]


@pytest.mark.parametrize('boundary', _GENERATION_BOUNDARIES)
def test_actual_generation_recovery_at_every_publication_boundary(tmp_path, boundary):
    wal = _activated_wal(tmp_path)
    target = tmp_path / 'state.json'
    def stop(label):
        if label == boundary:
            raise OSError('interrupted at ' + label)
    with pytest.raises(OSError):
        wal.commit([JsonArtifact('state', target, {'value': 'after'})], transaction_id='interrupted', fault_injector=stop)
    JsonWal(tmp_path / 'wal', tmp_path).recover()
    snapshot = wal.read_consistent_images([target])
    pre_manifest = _GENERATION_BOUNDARIES.index(boundary) < _GENERATION_BOUNDARIES.index('manifest:prepared:published')
    assert snapshot['images']['state.json'] is None if pre_manifest else json.loads(snapshot['images']['state.json']) == {'value': 'after'}
    wal.commit([JsonArtifact('state', target, {'value': 'next'})], transaction_id='next', expected_generation=snapshot['generation_token'])
    assert json.loads(target.read_bytes()) == {'value': 'next'}


def test_missing_effect_phase_authority_cannot_be_recovered_as_abort(tmp_path):
    wal = _activated_wal(tmp_path)
    def stop(label):
        if label == 'target:0:published':
            raise OSError('interrupted')
    with pytest.raises(OSError):
        wal.commit([JsonArtifact('state', tmp_path / 'state.json', {'value': 'after'})], transaction_id='missing', fault_injector=stop)
    (tmp_path / 'wal/transactions/missing/manifest.json').unlink()
    with pytest.raises(WalIntegrityError):
        wal.recover()
    assert WalGeneration(tmp_path / 'wal').read()['phase'] == 'prepared_effects_possible'


def test_ordinary_legacy_constructor_cannot_bypass_activated_owner(tmp_path):
    _activated_wal(tmp_path)
    before = WalGeneration(tmp_path / 'wal').read()
    with pytest.raises(WalIntegrityError):
        JsonWal(tmp_path / 'wal', tmp_path).commit([JsonArtifact('state', tmp_path / 'unowned.json', {})])
    assert not (tmp_path / 'unowned.json').exists()
    assert WalGeneration(tmp_path / 'wal').read() == before


def test_legacy_consistent_read_refuses_without_creating_paths(tmp_path):
    wal = JsonWal(tmp_path / 'wal', tmp_path)
    with pytest.raises(WalIntegrityError):
        wal.read_consistent_images([tmp_path / 'state.json'])
    assert list(tmp_path.iterdir()) == []


def test_external_journal_cannot_write_into_an_activated_domain(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    _activated_wal(project)
    outside = JsonWal(tmp_path / 'outside-wal', tmp_path)
    with pytest.raises(WalIntegrityError):
        outside.commit([JsonArtifact('state', project / 'state.json', {'bypass': True})])
    assert not (project / 'state.json').exists()
    assert not (tmp_path / 'outside-wal').exists()


@pytest.mark.parametrize('boundary', ['generation:allocated:published', 'journal:committed:published'])
def test_inspection_accounts_for_head_without_pending_directory(tmp_path, boundary):
    wal = _activated_wal(tmp_path)
    def stop(label):
        if label == boundary:
            raise OSError('interrupted')
    with pytest.raises(OSError):
        wal.commit([JsonArtifact('state', tmp_path / 'state.json', {})], fault_injector=stop)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert wal.inspect()['requires_recovery'] is True
    assert {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_inspection_cannot_classify_lost_effect_authority_as_rollback(tmp_path):
    wal = _activated_wal(tmp_path)
    def stop(label):
        if label == 'target:0:published':
            raise OSError('interrupted')
    with pytest.raises(OSError):
        wal.commit([JsonArtifact('state', tmp_path / 'state.json', {})], transaction_id='lost', fault_injector=stop)
    (tmp_path / 'wal/transactions/lost/manifest.json').unlink()
    with pytest.raises(WalIntegrityError):
        wal.inspect()


def test_physical_child_exit_at_generation_boundaries(tmp_path):
    import os
    from pathlib import Path
    import sys
    from runtime.test_runner import run_test_command
    from runtime.resource_lifecycle import ResourceManager
    child = '''
import os, sys
from pathlib import Path
from runtime.wal_transaction import JsonWal, JsonArtifact
root = Path(sys.argv[1])
def kill(label):
    if label == sys.argv[2]:
        os._exit(91)
JsonWal(root / 'wal', root).commit([JsonArtifact('state', root / 'state.json', {'value':'after'})], transaction_id='killed', fault_injector=kill)
'''
    manager = ResourceManager(tmp_path / 'child-ledger.json')
    for index, boundary in enumerate(_GENERATION_BOUNDARIES):
        case = tmp_path / f'case-{index}'
        case.mkdir()
        wal = _activated_wal(case)
        result = run_test_command([sys.executable, '-c', child, str(case), boundary],
            cwd=Path(__file__).parents[1], environment=os.environ, resource_manager=manager,
            run_id=f'generation-child-{index}', lane_id='wal-generation-crash', timeout_seconds=20,
            manage_process_temp=True)
        assert result['exit_code'] == 91, (boundary, result.get('stderr'))
        assert result['execution_started'] and result['process_tree_terminated']
        assert result['test_workspace']['reclaimed']
        wal.recover()
        image = wal.read_consistent_images([case / 'state.json'])['images']['state.json']
        pre_manifest = index < _GENERATION_BOUNDARIES.index('manifest:prepared:published')
        assert image is None if pre_manifest else json.loads(image) == {'value': 'after'}


def test_copied_generation_cannot_become_another_journals_authority(tmp_path):
    import shutil
    first = _generation(tmp_path)
    other = tmp_path / 'other-wal'
    other.mkdir()
    shutil.copytree(first.root, other / 'generation')
    with pytest.raises(WalIntegrityError, match='marker'):
        WalGeneration(other).read()
