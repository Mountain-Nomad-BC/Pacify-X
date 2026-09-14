"""Retained cleanup protocol, restart, dependent ownership and exact receipts."""
from dataclasses import replace
from pathlib import Path

import pytest

from runtime import resource_lifecycle as lifecycle


def pending(root, monkeypatch):
    manager = lifecycle.ResourceManager(root / 'state/ledger.json')
    record = manager.create_workspace(root, project_id='fixture', run_id='run', lane_id='lane', creator='test')
    (Path(record.path) / 'data').write_bytes(b'123')
    manager.update(record.resource_id, active=False, run_state='completed', status='reclaimable')
    def reject(receipt):
        raise OSError('fixture receipt rejection')
    with monkeypatch.context() as patch:
        patch.setattr(manager, '_write_receipt', reject)
        with pytest.raises(OSError, match='fixture receipt rejection'):
            manager.reclaim(record.resource_id, reason='fixture', apply=True)
    return manager, record


def test_fresh_manager_reconciles_completed_cleanup_receipt(tmp_path, monkeypatch):
    manager, record = pending(tmp_path, monkeypatch)
    fresh = lifecycle.ResourceManager(manager.ledger.path)
    result = fresh.reconcile(apply=True)
    assert result['valid']
    closed = fresh.ledger.get(record.resource_id)
    assert closed.status == 'reclaimed'
    assert (fresh.receipt_dir / f'{closed.cleanup_receipt_id}.json').is_file()
    assert result['receipts'][0]['bytes_reclaimed'] == 3


def test_fresh_manager_resumes_abandoned_process_workspace_reconciliation(tmp_path):
    manager = lifecycle.ResourceManager(tmp_path / 'state/ledger.json')
    workspace = manager.create_workspace(
        tmp_path,
        project_id='fixture',
        run_id='interrupted-reconcile',
        lane_id='lane',
        creator='test',
    )
    process = replace(
        workspace,
        resource_id='process-fixture',
        resource_type='process',
        path=None,
        allowed_cleanup_root=None,
        pid=123456789,
        active=False,
        run_state=lifecycle.RunState.ABANDONED.value,
        status=lifecycle.ResourceStatus.RECLAIMED.value,
        cleanup_result='persisted_process_proven_absent',
    )
    manager.ledger.upsert(process)

    fresh = lifecycle.ResourceManager(manager.ledger.path)
    result = fresh.reconcile(apply=True)

    assert result['valid'] is True
    closed = fresh.ledger.get(workspace.resource_id)
    assert closed.active is False
    assert closed.run_state == lifecycle.RunState.ABANDONED.value
    assert closed.status == lifecycle.ResourceStatus.RECLAIMED.value
    assert closed.cleanup_result == 'reclaimed'
    assert not Path(workspace.path).exists()


def test_completed_process_record_does_not_abandon_active_workspace(tmp_path):
    manager = lifecycle.ResourceManager(tmp_path / 'state/ledger.json')
    workspace = manager.create_workspace(
        tmp_path,
        project_id='fixture',
        run_id='completed-process',
        lane_id='lane',
        creator='test',
    )
    process = replace(
        workspace,
        resource_id='process-fixture',
        resource_type='process',
        path=None,
        allowed_cleanup_root=None,
        pid=123456789,
        active=False,
        run_state=lifecycle.RunState.COMPLETED.value,
        status=lifecycle.ResourceStatus.RECLAIMED.value,
        cleanup_result='exit_0',
    )
    manager.ledger.upsert(process)

    fresh = lifecycle.ResourceManager(manager.ledger.path)
    result = fresh.reconcile(apply=True)

    assert result['valid'] is False
    assert fresh.ledger.get(workspace.resource_id).active is True
    assert Path(workspace.path).exists()


def test_pending_child_cleanup_blocks_parent_reclamation(tmp_path, monkeypatch):
    manager = lifecycle.ResourceManager(tmp_path / 'state/ledger.json')
    parent = manager.create_workspace(tmp_path, project_id='fixture', run_id='run', lane_id='lane', creator='test')
    child_path = Path(parent.path) / 'child'
    child_path.mkdir()
    child = manager.register_path(child_path, allowed_cleanup_root=Path(parent.path),
        project_id='fixture', run_id='child', lane_id='lane', creator='test', parent_resource_id=parent.resource_id)
    manager.mark_run_ended('child', lifecycle.RunState.COMPLETED)
    with monkeypatch.context() as patch:
        patch.setattr(manager, '_write_receipt', lambda receipt: (_ for _ in ()).throw(OSError('receipt')))
        with pytest.raises(OSError):
            manager.reclaim(child.resource_id, reason='fixture', apply=True)
    manager.mark_run_ended('run', lifecycle.RunState.COMPLETED)
    fresh = lifecycle.ResourceManager(manager.ledger.path)
    receipt = fresh.reclaim(parent.resource_id, reason='fixture', apply=True)
    assert receipt.resources_reclaimed == 0
    assert Path(parent.path).exists()


@pytest.mark.parametrize('change', ['schema', 'id', 'counter', 'scope'])
def test_invalid_retained_cleanup_protocol_refuses_before_acknowledgment(tmp_path, monkeypatch, change):
    manager, record = pending(tmp_path, monkeypatch)
    retained = manager.ledger.get(record.resource_id)
    operation = retained.cleanup_intent
    if change == 'schema':
        operation['schema_version'] = 'unknown'
    elif change == 'id':
        operation['cleanup_id'] = '../escaped'
        operation['receipt']['cleanup_id'] = '../escaped'
    elif change == 'counter':
        operation['inventory']['bytes'] = True
        operation['receipt']['bytes_reclaimed'] = True
    else:
        operation['receipt']['project_id'] = 'other'
    manager.update(record.resource_id, cleanup_intent=operation)
    fresh = lifecycle.ResourceManager(manager.ledger.path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and p.suffix != '.lock'}
    with pytest.raises(ValueError):
        fresh.reclaim(record.resource_id, reason='fixture', apply=True)
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and p.suffix != '.lock'}
    assert before == after


def test_receipt_writer_rejects_noncanonical_id(tmp_path, monkeypatch):
    manager, record = pending(tmp_path, monkeypatch)
    receipt = lifecycle.CleanupReceipt(**manager.ledger.get(record.resource_id).cleanup_intent['receipt'])
    with pytest.raises(ValueError):
        manager._write_receipt(replace(receipt, cleanup_id='../escaped'))
    assert not (manager.receipt_dir.parent / 'escaped.json').exists()


@pytest.mark.parametrize('status', ['cleanup_pending', 'retained'])
def test_unacknowledged_cleanup_remains_in_legacy_closure_denominator(tmp_path, monkeypatch, status):
    manager, record = pending(tmp_path, monkeypatch)
    manager.update(record.resource_id, status=status)
    result = lifecycle.resource_status(manager.ledger.path)
    assert result['reclaimable_paths'] == 1
    assert result['cleanup_pending'] == 1
    observed = manager.reconcile(apply=False)
    assert not observed['valid']
    assert not observed['resource_ledger_reconciled']


@pytest.mark.parametrize('failure', ['ledger', 'receipt'])
@pytest.mark.parametrize('backend', ['legacy', 'indexed'])
def test_secondary_publication_cannot_replace_deletion_failure(tmp_path, monkeypatch, failure, backend):
    manager = lifecycle.ResourceManager(tmp_path / 'state/ledger.json')
    record = manager.create_workspace(tmp_path, project_id='fixture', run_id='run', lane_id='lane', creator='test')
    manager.mark_run_ended('run', lifecycle.RunState.COMPLETED)
    if backend == 'indexed':
        import hashlib
        from scripts.migrate_resource_ledger import migrate
        migrate(manager.ledger.path, expected_legacy_sha256=hashlib.sha256(manager.ledger.path.read_bytes()).hexdigest())
    cause = OSError('original deletion failure')
    def remove(target):
        raise cause
    monkeypatch.setattr(lifecycle, '_remove_owned_target', remove)
    if failure == 'receipt':
        monkeypatch.setattr(manager, '_write_receipt', lambda receipt: (_ for _ in ()).throw(OSError('secondary receipt')))
    else:
        original = manager.ledger._upsert_unlocked
        def write(row):
            if row.status == 'cleanup_failed':
                raise OSError('secondary ledger')
            return original(row)
        monkeypatch.setattr(manager.ledger, '_upsert_unlocked', write)
    with pytest.raises(OSError) as caught:
        manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert caught.value is cause
    assert Path(record.path).exists()
    assert manager.ledger.get(record.resource_id).cleanup_intent['phase'] == 'effect_pending'


def test_restart_without_confirmed_effect_refuses_ambiguous_absence(tmp_path, monkeypatch):
    manager, record = pending(tmp_path, monkeypatch)
    current = manager.ledger.get(record.resource_id)
    operation = {key: value for key, value in current.cleanup_intent.items() if key != 'receipt'}
    operation['phase'] = 'effect_pending'
    manager.update(record.resource_id, cleanup_intent=operation)
    fresh = lifecycle.ResourceManager(manager.ledger.path)
    with pytest.raises(ValueError, match='ambiguous after restart'):
        fresh.reclaim(record.resource_id, reason='fixture', apply=True)
    assert fresh.ledger.get(record.resource_id).status == 'cleanup_pending'
