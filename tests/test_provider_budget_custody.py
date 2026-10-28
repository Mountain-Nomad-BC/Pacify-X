from pathlib import Path
import pytest
from runtime.provider_budget import BudgetIntegrityError, ProviderBudgetLedger, ProviderUsage
from tests.test_provider_budget import _ledger, _policy_row, _reserve


def symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f'native symlink creation unavailable: {error}')


@pytest.mark.parametrize('phase', ['reserve', 'settle'])
def test_replaced_root_refuses_before_lock_writes(tmp_path, phase):
    ledger = _ledger(tmp_path, _policy_row())
    if phase == 'settle':
        _reserve(ledger)
        ledger.root.rename(tmp_path / 'preserved-budget')
    outside = tmp_path / 'outside'
    outside.mkdir()
    symlink(ledger.root, outside)
    with pytest.raises(BudgetIntegrityError):
        if phase == 'reserve': _reserve(ledger)
        else: ledger.settle('invocation-1', outcome='success', usage=ProviderUsage('actual', 1, 1, 1))
    assert list(outside.iterdir()) == []


def test_replaced_allowed_root_identity_refuses_before_write(tmp_path):
    ledger = _ledger(tmp_path, _policy_row())
    ledger.allowed_root.rename(tmp_path / 'preserved-state')
    ledger.allowed_root.mkdir()
    with pytest.raises(BudgetIntegrityError, match='identity'):
        _reserve(ledger)
    assert list(ledger.allowed_root.iterdir()) == []


def test_constructor_rejects_nominal_root_link(tmp_path):
    ledger = _ledger(tmp_path, _policy_row())
    destination = ledger.allowed_root / 'other-budget'
    destination.mkdir()
    symlink(ledger.root, destination)
    with pytest.raises(BudgetIntegrityError):
        ProviderBudgetLedger(ledger.engine_root, ledger.root, ledger.allowed_root)
    assert list(destination.iterdir()) == []


def test_replaced_existing_budget_directory_identity_refuses(tmp_path):
    ledger = _ledger(tmp_path, _policy_row())
    _reserve(ledger)
    ledger.root.rename(tmp_path / 'preserved-budget')
    ledger.root.mkdir()
    with pytest.raises(BudgetIntegrityError, match='identity'):
        _reserve(ledger, 'invocation-2')
    assert list(ledger.root.iterdir()) == []


def test_read_snapshot_refuses_replaced_authority(tmp_path):
    ledger = _ledger(tmp_path, _policy_row())
    _reserve(ledger)
    ledger.root.rename(tmp_path / 'preserved-budget')
    ledger.root.mkdir()
    with pytest.raises(BudgetIntegrityError, match='identity'):
        ledger.snapshot()


def test_lock_link_refuses_before_target_mutation(tmp_path):
    ledger = _ledger(tmp_path, _policy_row())
    ledger.root.mkdir()
    target = tmp_path / 'unrelated-control'
    target.write_bytes(b'preserve')
    try:
        (ledger.root / '.budget.lock').symlink_to(target)
    except OSError as error:
        pytest.skip(f'native symlink creation unavailable: {error}')
    with pytest.raises(BudgetIntegrityError):
        _reserve(ledger)
    assert target.read_bytes() == b'preserve'


def test_native_gateway_denies_before_adapter_call_on_stale_budget_root(tmp_path):
    from tests.test_provider_gateway import _project, _gateway, _request, FakeAdapter
    root = _project(str(tmp_path), mode='remote', billing_state='actual')
    allowed = tmp_path / 'state'
    allowed.mkdir()
    gateway = _gateway(root, allowed)
    allowed.rename(tmp_path / 'preserved-state')
    allowed.mkdir()
    adapter = FakeAdapter('fixture-adapter')
    with pytest.raises(BudgetIntegrityError):
        gateway.invoke(_request(), adapter)
    assert adapter.calls == 0


def test_replaced_intermediate_ancestor_refuses_before_write(tmp_path):
    fixture = _ledger(tmp_path, _policy_row())
    parent = fixture.allowed_root / 'provider'
    parent.mkdir()
    ledger = ProviderBudgetLedger(fixture.engine_root, parent / 'budget', fixture.allowed_root)
    parent.rename(tmp_path / 'preserved-provider')
    parent.mkdir()
    with pytest.raises(BudgetIntegrityError, match='identity'):
        _reserve(ledger)
    assert list(parent.iterdir()) == []


def test_concurrent_directory_change_after_mkdir_refuses_before_lock(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path, _policy_row())
    native_mkdir = Path.mkdir
    replaced = False
    def replace_on_create(path, *args, **kwargs):
        nonlocal replaced
        result = native_mkdir(path, *args, **kwargs)
        if path == ledger.root and not replaced:
            replaced = True
            ledger.allowed_root.rename(tmp_path / 'preserved-state')
            native_mkdir(ledger.allowed_root)
        return result
    monkeypatch.setattr(Path, 'mkdir', replace_on_create)
    with pytest.raises(BudgetIntegrityError, match='identity'):
        _reserve(ledger)
    assert list(ledger.allowed_root.iterdir()) == []
