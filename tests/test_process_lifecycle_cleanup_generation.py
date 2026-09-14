"""Shared cleanup effect-boundary and acknowledgment failures, owned fixtures only."""
from pathlib import Path

import pytest

from runtime import resource_lifecycle as lifecycle


def resource(root):
    manager = lifecycle.ResourceManager(root / 'state/ledger.json')
    record = manager.create_workspace(root, project_id='fixture', run_id='run',
                                      lane_id='lane', creator='test')
    target = Path(record.path)
    (target / 'payload.txt').write_bytes(b'fixture-data')
    manager.update(record.resource_id, active=False, run_state='completed', status='reclaimable')
    return manager, record, target


@pytest.mark.parametrize('change', ['replacement', 'retention', 'active', 'dependent'])
def test_cleanup_rechecks_shared_authority_after_inventory(tmp_path, monkeypatch, change):
    manager, record, target = resource(tmp_path)
    original = manager.inventory
    changed = False
    def inventory(path):
        nonlocal changed
        result = original(path)
        if not changed:
            changed = True
            if change == 'replacement':
                target.rename(tmp_path / 'retained-original')
                target.mkdir()
                (target / 'replacement.txt').write_bytes(b'different-owned-fixture')
            elif change == 'retention':
                manager.update(record.resource_id, retention_required=True)
            elif change == 'active':
                manager.update(record.resource_id, active=True, run_state='active')
            else:
                child = target / 'child'
                child.mkdir()
                manager.register_path(child, allowed_cleanup_root=target,
                    project_id='fixture', run_id='run', lane_id='lane', creator='test',
                    parent_resource_id=record.resource_id)
        return result
    monkeypatch.setattr(manager, 'inventory', inventory)
    receipt = manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert target.exists()
    assert receipt.resources_reclaimed == 0


@pytest.mark.parametrize('apply', [1, 'yes', [], None])
def test_cleanup_apply_requires_actual_boolean_without_effect(tmp_path, apply):
    manager, record, target = resource(tmp_path)
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    with pytest.raises(ValueError):
        manager.reclaim(record.resource_id, reason='fixture', apply=apply)
    assert target.exists()
    assert before == {path.relative_to(tmp_path).as_posix(): path.read_bytes()
                      for path in tmp_path.rglob('*') if path.is_file()}


def test_cleanup_receipt_failure_retains_recoverable_effect(tmp_path, monkeypatch):
    manager, record, target = resource(tmp_path)
    original = manager._write_receipt
    def reject(receipt):
        raise OSError('receipt publication rejected')
    monkeypatch.setattr(manager, '_write_receipt', reject)
    with pytest.raises(OSError, match='receipt publication rejected'):
        manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert not target.exists()
    assert manager.ledger.get(record.resource_id).status != 'reclaimed'
    monkeypatch.setattr(manager, '_write_receipt', original)
    receipt = manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert receipt.resources_reclaimed == 1
    assert receipt.files_removed == 1
    assert receipt.bytes_reclaimed == len(b'fixture-data')
    assert manager.ledger.get(record.resource_id).status == 'reclaimed'


@pytest.mark.parametrize('backend', ['legacy', 'indexed'])
def test_cleanup_ledger_failure_does_not_erase_effect_accounting(tmp_path, monkeypatch, backend):
    manager, record, target = resource(tmp_path)
    if backend == 'indexed':
        import hashlib
        from scripts.migrate_resource_ledger import migrate
        migrate(manager.ledger.path, expected_legacy_sha256=hashlib.sha256(manager.ledger.path.read_bytes()).hexdigest())
    original = manager.ledger._upsert_unlocked
    failed = False
    def reject(row):
        nonlocal failed
        if not failed and row.resource_id == record.resource_id and row.status == 'reclaimed':
            failed = True
            raise OSError('ledger publication rejected')
        return original(row)
    monkeypatch.setattr(manager.ledger, '_upsert_unlocked', reject)
    with pytest.raises(OSError, match='ledger publication rejected'):
        manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert not target.exists()
    receipt = manager.reclaim(record.resource_id, reason='fixture', apply=True)
    assert receipt.resources_reclaimed == 1
    assert receipt.files_removed == 1
    assert receipt.bytes_reclaimed == len(b'fixture-data')
