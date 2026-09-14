"""Read-only resource planning must not write receipts, leases, or kill children."""
from dataclasses import replace
import json

import pytest

from runtime import resource_lifecycle as resources
from runtime import wal_transaction as wal


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def fixture(root):
    owner = resources.ResourceManager(root / 'state/ledger.json')
    record = owner.create_workspace(root, project_id='p', run_id='r', lane_id='l', creator='fixture')
    owner.mark_run_ended('r', resources.RunState.COMPLETED)
    return owner, record


def test_absent_status_does_not_create_ledger_or_lock(tmp_path):
    before = tree(tmp_path)
    assert resources.resource_status(tmp_path / 'absent/ledger.json')['resource_count'] == 0
    assert tree(tmp_path) == before
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('failure', [False, True])
def test_reclamation_dry_run_has_no_effects_even_on_inventory_failure(tmp_path, monkeypatch, failure):
    owner, record = fixture(tmp_path)
    before = tree(tmp_path)
    if failure:
        def failed(path):
            raise OSError('injected inventory failure')
        monkeypatch.setattr(owner, 'inventory', failed)
    receipt = owner.reclaim(record.resource_id, reason='read-only plan', apply=False)
    assert receipt.dry_run is True
    assert receipt.resources_reclaimed == 0
    assert receipt.resources_failed == int(failure)
    assert tree(tmp_path) == before
    assert not owner.receipt_dir.exists()


def test_reconcile_dry_run_does_not_terminate_retained_live_handle(tmp_path, monkeypatch):
    owner, record = fixture(tmp_path)
    process_record = replace(record, resource_id='process-fixture', resource_type='process', active=True,
                             run_state=resources.RunState.ACTIVE.value, status=resources.ResourceStatus.ACTIVE.value,
                             path=None, allowed_cleanup_root=None, pid=123456789)
    owner.ledger.upsert(process_record)
    owner._processes[process_record.resource_id] = object()
    def forbidden(*args, **kwargs):
        pytest.fail('read-only reconciliation invoked process termination')
    monkeypatch.setattr(owner, 'terminate_owned_process', forbidden)
    before = tree(tmp_path)
    report = owner.reconcile(apply=False)
    assert report['owned_child_processes_active'] == 1
    assert report['dry_run'] is True
    assert tree(tmp_path) == before


def test_absent_process_dry_run_does_not_acknowledge_or_publish(tmp_path, monkeypatch):
    owner, record = fixture(tmp_path)
    process_record = replace(record, resource_id='process-fixture', resource_type='process', active=True,
                             run_state=resources.RunState.ACTIVE.value, status=resources.ResourceStatus.ACTIVE.value,
                             path=None, allowed_cleanup_root=None, pid=123456789)
    owner.ledger.upsert(process_record)
    monkeypatch.setattr(resources, '_process_exists', lambda pid: False)
    before = tree(tmp_path)
    receipt = owner.retire_proven_absent_process(process_record.resource_id, apply=False)
    assert receipt.resources_reclaimed == 0 and receipt.dry_run
    assert tree(tmp_path) == before
    assert owner.ledger.observe()[-1].active is True


def test_status_with_storage_does_not_write_a_reader_lease(tmp_path):
    owner, _record = fixture(tmp_path)
    before = tree(tmp_path)
    report = resources.resource_status(owner.ledger.path, storage_path=tmp_path)
    assert report['resource_count'] == 1
    assert 'storage' in report
    assert tree(tmp_path) == before


@pytest.mark.parametrize('kind', ['duplicate', 'invalid_activity'])
def test_observation_fails_closed_on_invalid_identity_or_activity(tmp_path, kind):
    owner, _record = fixture(tmp_path)
    value = json.loads(owner.ledger.path.read_bytes())
    if kind == 'duplicate':
        value['resources'].append(value['resources'][0])
    else:
        value['resources'][0]['active'] = 'false'
    owner.ledger.path.write_text(json.dumps(value), encoding='utf-8')
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        owner.ledger.observe()
    assert tree(tmp_path) == before


def test_retention_wrapper_and_public_gate_remain_observational(tmp_path):
    owner, record = fixture(tmp_path)
    retention = resources.RetentionManager(owner, allowed_root=tmp_path, wal_root=tmp_path / 'wal')
    current = owner.ledger.observe()[0]
    before = tree(tmp_path)
    allowed, blockers = owner.reclamation_gate(current)
    assert allowed and not blockers
    assert retention.reclaim_transient(record.resource_id, reason='plan', apply=False).dry_run
    assert tree(tmp_path) == before


def test_concurrent_replacement_cannot_return_an_unchecked_image(tmp_path, monkeypatch):
    owner, _record = fixture(tmp_path)
    original = wal.read_file_image
    def replaced(path, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(b'{"schema_version":"1.0","resources":[]}')
        replacement.replace(path)
        return raw
    monkeypatch.setattr(wal, 'read_file_image', replaced)
    with pytest.raises(wal.WalIntegrityError, match='changed during acquisition'):
        owner.ledger.observe()


def test_observation_accepts_the_retained_record_denominator(tmp_path):
    owner, _record = fixture(tmp_path)
    value = json.loads(owner.ledger.path.read_bytes())
    example = value['resources'][0]
    value['resources'] = [dict(example, resource_id=f'path-{index:032x}',
                               path=str(tmp_path / f'workspace-{index}'))
                          for index in range(19_700)]
    owner.ledger.path.write_text(json.dumps(value, indent=2), encoding='utf-8')
    raw = owner.ledger.path.read_bytes()
    assert len(raw) > 10 * 1024 * 1024
    observed = owner.ledger.observe()
    assert len(observed) == 19_700
    assert len({record.resource_id for record in observed}) == 19_700
    assert owner.ledger.path.read_bytes() == raw
