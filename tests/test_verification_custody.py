"""Bounded real-child and deterministic setup/cancellation proofs on owned roots."""
import os
from pathlib import Path
import sys
from threading import Event
from time import monotonic

import pytest

from runtime.resource_lifecycle import ResourceManager
from runtime.test_runner import run_test_command
from runtime.process_supervisor import ProcessSupervisor


def run(root, manager, *, command=None, **options):
    return run_test_command(command or [sys.executable, '-c', 'print("owned child")'],
        cwd=root, environment={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        resource_manager=manager, timeout_seconds=options.pop('timeout_seconds', 15),
        run_id='vr01-owned-deadline-fixture', lane_id='vr01-custody',
        manage_process_temp=True, **options)


@pytest.mark.parametrize('deadline', [True, '10', float('nan'), float('inf'), -1])
def test_invalid_deadline_does_not_create_workspace(tmp_path, deadline):
    manager = ResourceManager(tmp_path / 'ledger.json')
    with pytest.raises(ValueError):
        run(tmp_path, manager, deadline=deadline)
    assert not manager.ledger.load()


def test_already_cancelled_run_never_creates_resource(tmp_path):
    manager = ResourceManager(tmp_path / 'ledger.json')
    cancel = Event()
    cancel.set()
    result = run(tmp_path, manager, cancel_event=cancel)
    assert result['valid'] is False and result['execution_started'] is False
    assert result['process_tree_terminated'] is True and not result['timed_out']
    assert not manager.ledger.load()


def test_cancellation_after_workspace_registration_reclaims_without_spawn(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    cancel = Event()
    original = manager.create_workspace
    def create(*args, **kwargs):
        record = original(*args, **kwargs)
        cancel.set()
        return record
    monkeypatch.setattr(manager, 'create_workspace', create)
    monkeypatch.setattr(manager, 'spawn_owned_process', lambda *a, **k: pytest.fail('cancelled setup spawned a child'))
    result = run(tmp_path, manager, cancel_event=cancel)
    assert result['valid'] is False and result['execution_started'] is False
    assert result['test_workspace']['reclaimed'] is True
    assert all(not record.active for record in manager.ledger.load())


def test_setup_exception_reclaims_workspace_once_and_preserves_original(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    original_mkdir = Path.mkdir
    original_reclaim = manager.reclaim
    reclaimed = []
    def mkdir(path, *args, **kwargs):
        if path.name == 'process-temp' and path.parent.name.startswith('pacify-x-process-'):
            raise RuntimeError('fixture setup failure')
        return original_mkdir(path, *args, **kwargs)
    def reclaim(*args, **kwargs):
        reclaimed.append(args[0])
        return original_reclaim(*args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(manager, 'reclaim', reclaim)
    with pytest.raises(RuntimeError, match='fixture setup failure'):
        run(tmp_path, manager)
    assert len(reclaimed) == 1
    assert all(not row.active and row.status == 'reclaimed' for row in manager.ledger.load())


def test_cleanup_error_does_not_mask_original_setup_failure(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    original_mkdir = Path.mkdir
    original_reclaim = manager.reclaim
    def mkdir(path, *args, **kwargs):
        if path.name == 'process-temp' and path.parent.name.startswith('pacify-x-process-'):
            raise RuntimeError('original fixture error')
        return original_mkdir(path, *args, **kwargs)
    def reclaim(*args, **kwargs):
        original_reclaim(*args, **kwargs)
        raise OSError('fixture report error after actual reclaim')
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(manager, 'reclaim', reclaim)
    with pytest.raises(RuntimeError, match='original fixture error') as caught:
        run(tmp_path, manager)
    assert any('closure also failed' in note for note in caught.value.__notes__)
    assert all(not row.active and row.status == 'reclaimed' for row in manager.ledger.load())


def test_cancellation_during_authorization_prevents_spawn(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    cancel = Event()
    original = ProcessSupervisor._authorize
    def authorize(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        cancel.set()
        return result
    monkeypatch.setattr(ProcessSupervisor, '_authorize', authorize)
    monkeypatch.setattr(manager, 'spawn_owned_process', lambda *a, **k: pytest.fail('cancelled authorization spawned a child'))
    result = run(tmp_path, manager, cancel_event=cancel)
    assert result['valid'] is False and result['execution_started'] is False
    assert 'after authorization' in result['refusal_reason']
    assert result['test_workspace']['reclaimed'] is True
    assert all(not row.active for row in manager.ledger.load())


def test_cancel_after_spawn_physically_closes_owned_child(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    cancel = Event()
    original = manager.spawn_owned_process
    processes = []
    def spawn(*args, **kwargs):
        record, process = original(*args, **kwargs)
        processes.append(process)
        cancel.set()
        return record, process
    monkeypatch.setattr(manager, 'spawn_owned_process', spawn)
    result = run(tmp_path, manager, command=[sys.executable, '-c', 'import time; time.sleep(30)'], cancel_event=cancel)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert result['valid'] is False and result['process_tree_terminated'] is True
    assert result['supervision_status'] == 'cancelled'
    assert result['test_workspace']['reclaimed'] is True
    assert all(not row.active for row in manager.ledger.load())


def test_parent_deadline_terminates_sleeping_child_and_reclaims(tmp_path):
    manager = ResourceManager(tmp_path / 'ledger.json')
    result = run(tmp_path, manager, command=[sys.executable, '-c', 'import time; time.sleep(30)'], deadline=monotonic() + 2)
    assert result['valid'] is False and result['timed_out'] is True
    assert result['process_tree_terminated'] is True
    assert result['test_workspace']['reclaimed'] is True
    assert result['duration_seconds'] < 15
    assert all(not row.active for row in manager.ledger.load())


def test_natural_owned_success_retains_closed_custody(tmp_path):
    manager = ResourceManager(tmp_path / 'ledger.json')
    result = run(tmp_path, manager)
    assert result['valid'] is True and result['timed_out'] is False
    assert result['process_tree_terminated'] is True
    assert result['test_workspace']['reclaimed'] is True
    assert 'owned child' in result['stdout']
    assert all(not row.active for row in manager.ledger.load())


def test_cancelled_setup_reports_time_spent_closing_workspace(tmp_path, monkeypatch):
    import time
    clock = [100.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    manager = ResourceManager(tmp_path / 'ledger.json')
    cancel = Event()
    original_create = manager.create_workspace
    original_reclaim = manager.reclaim
    def create(*args, **kwargs):
        record = original_create(*args, **kwargs)
        cancel.set()
        return record
    def reclaim(*args, **kwargs):
        result = original_reclaim(*args, **kwargs)
        clock[0] += 2.0
        return result
    monkeypatch.setattr(manager, 'create_workspace', create)
    monkeypatch.setattr(manager, 'reclaim', reclaim)
    result = run(tmp_path, manager, cancel_event=cancel)
    assert result['valid'] is False and result['execution_started'] is False
    assert result['test_workspace']['reclaimed'] is True
    assert result['duration_seconds'] == 2.0
