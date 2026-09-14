"""Exercise actual retention and budget callers against coordinated WAL candidates."""
import json
from pathlib import Path

import pytest

from runtime.resource_lifecycle import ResourceManager, RetentionManager
from runtime.wal_transaction import WalConflictError
from tests.test_provider_budget import _ledger, _policy_row, _reserve
from tests.test_recovery_coordinator_retention import _canonical, _history


def retention(root):
    return RetentionManager(ResourceManager(root / 'ledger.json'), allowed_root=root,
                            wal_root=root / 'wal', receipt_dir=root / 'receipts')


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def test_retention_dry_run_has_no_file_effects(tmp_path):
    owner = retention(tmp_path)
    history = tmp_path / 'history.json'
    history.write_bytes(_canonical(_history(5)))
    before = tree(tmp_path)
    report = owner.prune_operational_history(history, max_records=2)
    assert report['records_pruned'] == 3
    assert tree(tmp_path) == before


@pytest.mark.parametrize('value', [True, 2.0, '2'])
def test_retention_rejects_noninteger_bounds(tmp_path, value):
    with pytest.raises(ValueError, match='max_records'):
        retention(tmp_path).prune_operational_history(tmp_path / 'absent', max_records=value)


def test_retention_refuses_history_appended_after_planning(tmp_path, monkeypatch):
    owner = retention(tmp_path)
    history = tmp_path / 'history.json'
    history.write_bytes(_canonical(_history(5)))
    commit = owner.wal.commit
    appended = _canonical(_history(6))
    def raced(artifacts, **kwargs):
        history.write_bytes(appended)
        return commit(artifacts, **kwargs)
    monkeypatch.setattr(owner.wal, 'commit', raced)
    with pytest.raises(WalConflictError):
        owner.prune_operational_history(history, max_records=2, apply=True)
    assert history.read_bytes() == appended
    assert not owner.receipt_dir.exists()


def test_retention_does_not_overwrite_preexisting_anchor(tmp_path):
    owner = retention(tmp_path)
    history = tmp_path / 'history.json'
    original = _canonical(_history(5))
    history.write_bytes(original)
    plan = owner.prune_operational_history(history, max_records=2)
    anchor = Path(plan['anchor_path'])
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b'{"existing":true}')
    with pytest.raises(WalConflictError):
        owner.prune_operational_history(history, max_records=2, apply=True)
    assert history.read_bytes() == original
    assert anchor.read_bytes() == b'{"existing":true}'


def test_budget_recovery_cannot_overwrite_an_earlier_reservation(tmp_path, monkeypatch):
    owner = _ledger(tmp_path, _policy_row())
    commit = owner.wal.commit
    def prepared(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('reservation prepared')
    def interrupted(artifacts, **kwargs):
        return commit(artifacts, fault_injector=prepared, **kwargs)
    monkeypatch.setattr(owner.wal, 'commit', interrupted)
    with pytest.raises(RuntimeError):
        _reserve(owner, 'first')
    monkeypatch.setattr(owner.wal, 'commit', commit)
    with pytest.raises(WalConflictError) as caught:
        _reserve(owner, 'second')
    assert caught.value.wal_outcome['recovery']['completed'] == ['provider-reserve-first']
    state = owner.snapshot()
    assert set(state['invocations']) == {'first'}
    assert next(iter(state['budgets'].values()))['request_count'] == 1
    assert not (owner.root / 'receipts/second.reserved.json').exists()
    _reserve(owner, 'second')
    assert set(owner.snapshot()['invocations']) == {'first', 'second'}


def test_budget_settlement_binds_the_receipt_it_validated(tmp_path, monkeypatch):
    owner = _ledger(tmp_path, _policy_row())
    _reserve(owner)
    original = owner.state_path.read_bytes()
    receipt = owner.root / 'receipts/invocation-1.reserved.json'
    commit = owner.wal.commit
    def raced(artifacts, **kwargs):
        receipt.write_bytes(receipt.read_bytes() + b' ')
        return commit(artifacts, **kwargs)
    monkeypatch.setattr(owner.wal, 'commit', raced)
    with pytest.raises(WalConflictError, match='read dependency'):
        owner.settle('invocation-1', outcome='failure', usage=None)
    assert owner.state_path.read_bytes() == original
    assert json.loads(receipt.read_bytes())['phase'] == 'reserved'
    assert not (owner.root / 'receipts/invocation-1.settled.json').exists()
