"""Retained native ownership must remain visible and retryable after faults."""
import os
import json
import subprocess
import sys
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime import process_supervisor as supervisor_module
from runtime.process_supervisor import ProcessSupervisor, ProcessBudgets
from runtime.resource_lifecycle import ResourceManager, RunState
from tests.test_process_supervisor import _action

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows retained handle custody')


@pytest.mark.parametrize('fault', ['registration', 'handle', 'receipt'])
def test_failed_creation_recovery_preserves_then_closes_exact_owner(tmp_path, monkeypatch, fault):
    manager = ResourceManager(tmp_path / 'ledger.json')
    failure = RuntimeError('registration failure')
    original_upsert = manager.ledger.upsert
    calls = 0
    def upsert(record):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise failure
        original_upsert(record)
    class RefusingClose(subprocess.Handle):
        def Close(self):
            raise OSError('handle closure refused')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(manager.ledger, 'upsert', upsert)
            if fault == 'handle':
                patch.setattr(supervisor_module._WindowsContainedPopen, '_wrap_created_handle', staticmethod(RefusingClose))
            with pytest.raises(RuntimeError) as caught:
                manager.spawn_owned_process([sys.executable, '-c', 'import time;time.sleep(60)'],
                    cwd=tmp_path, project_id='fixture', run_id='recovery', lane_id='fixture', creator='fixture',
                    ownership='supervised', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert caught.value is failure
        assert len(manager._failed_creation_custody) == 1
        owner = next(iter(manager._failed_creation_custody.values()))
        before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        dry = manager.reconcile_retained_custody()
        assert not dry['valid'] and dry['pending']
        assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        if fault == 'handle':
            denied = manager.reconcile_retained_custody(apply=True)
            assert not denied['valid'] and denied['pending']
            monkeypatch.setattr(RefusingClose, 'Close', subprocess.Handle.Close)
        if fault == 'receipt':
            def fail_receipt(receipt):
                raise OSError('receipt publication failed')
            with monkeypatch.context() as patch:
                patch.setattr(manager, '_write_receipt', fail_receipt)
                denied = manager.reconcile_retained_custody(apply=True)
                assert not denied['valid'] and denied['pending']
        recovered = manager.reconcile_retained_custody(apply=True)
        assert recovered['valid'] and not recovered['pending']
        assert owner._handle.closed and owner.returncode is not None
        assert not manager._process_jobs and not manager._processes
        assert all(not record.active for record in manager.ledger.observe())
        receipts = [json.loads(path.read_bytes()) for path in manager.receipt_dir.glob('*.json')]
        assert len(receipts) == 1
        assert receipts[0]['reason'].startswith('retained_custody_recovered:process-')
        assert receipts[0]['resources_reclaimed'] == 1
    finally:
        monkeypatch.setattr(RefusingClose, 'Close', subprocess.Handle.Close)
        manager.reconcile_retained_custody(apply=True)


def test_liveness_close_failure_stays_visible_until_recovered(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    calls = 0
    class Liveness:
        closed = False
        def alive(self):
            return True
        def close(self):
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise OSError('liveness close failed')
            self.closed = True
    owner = Liveness()
    monkeypatch.setattr(supervisor_module, '_open_owner_liveness', lambda pid: owner)
    with pytest.raises(OSError):
        ProcessSupervisor(manager).run([sys.executable, '-c', 'pass'], cwd=tmp_path,
            action=_action(tmp_path), project_id='fixture', run_id='liveness', lane_id='fixture', creator='fixture')
    assert manager._supervision_failures and not owner.closed
    assert not manager.reconcile()['valid']
    result = manager.reconcile_retained_custody(apply=True)
    assert result['valid'] and owner.closed
    assert not manager._supervision_failures
    assert len(list(manager.receipt_dir.glob('*.json'))) == 1


@pytest.mark.parametrize('indirect', [False, True])
def test_unacknowledged_recovery_blocks_parent_workspace_cleanup(tmp_path, monkeypatch, indirect):
    manager = ResourceManager(tmp_path / 'ledger.json')
    workspace = manager.create_workspace(tmp_path, project_id='fixture', run_id='recovery',
        lane_id='fixture', creator='fixture')
    parent_id = workspace.resource_id
    if indirect:
        from pathlib import Path
        child_path = Path(workspace.path) / 'intermediate'
        child_path.mkdir()
        child = manager.register_path(child_path, allowed_cleanup_root=Path(workspace.path),
            project_id='fixture', run_id='recovery', lane_id='fixture', creator='fixture',
            parent_resource_id=workspace.resource_id)
        parent_id = child.resource_id
    original = manager.ledger.upsert
    calls = 0
    def fail_registration(record):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError('registration unavailable')
        return original(record)
    with monkeypatch.context() as patch:
        patch.setattr(manager.ledger, 'upsert', fail_registration)
        with pytest.raises(OSError):
            manager.spawn_owned_process([sys.executable, '-c', 'pass'], cwd=tmp_path,
                project_id='fixture', run_id='recovery', lane_id='fixture', creator='fixture',
                ownership='supervised', parent_resource_id=parent_id,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def deny_receipt(receipt):
        raise OSError('recovery receipt unavailable')
    if indirect:
        manager.update(child.resource_id, active=False, run_state=RunState.FAILED.value, status='reclaimable')
    with monkeypatch.context() as patch:
        patch.setattr(manager, '_write_receipt', deny_receipt)
        assert not manager.reconcile_retained_custody(apply=True)['valid']
    manager.update(workspace.resource_id, active=False, run_state=RunState.FAILED.value, status='reclaimable')
    refused = manager.reclaim(workspace.resource_id, reason='test-recovery', apply=True)
    assert refused.resources_reclaimed == 0
    assert 'active child resources still reference the target' in refused.errors
    assert manager.reconcile_retained_custody(apply=True)['valid']
    reclaimed = manager.reclaim(workspace.resource_id, reason='test-recovery-acknowledged', apply=True)
    assert reclaimed.resources_reclaimed == 1


def test_job_only_constructor_failure_remains_visible_and_recovers(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    job_type = supervisor_module._WindowsJob
    initialize = job_type.__init__
    retained = []
    failure = RuntimeError('constructor failed after native acquisition')
    def constructor(job, *args, **kwargs):
        initialize(job, *args, **kwargs)
        retained.append(job)
        raise failure
    def close(job):
        raise OSError('Job close refused')
    with monkeypatch.context() as patch:
        patch.setattr(job_type, '__init__', constructor)
        patch.setattr(job_type, 'close', close)
        with pytest.raises(RuntimeError) as caught:
            manager.spawn_owned_process([sys.executable, '-c', 'pass'], cwd=tmp_path,
                project_id='fixture', run_id='job-only', lane_id='fixture', creator='fixture', ownership='supervised')
        assert caught.value is failure
    assert retained[0].handle and not manager._failed_creation_custody
    assert not manager.reconcile_retained_custody()['valid']
    result = manager.reconcile_retained_custody(apply=True)
    assert result['valid'] and retained[0].handle is None
    assert not manager._process_jobs


def test_recovery_waits_before_closing_newly_proven_process_handle(tmp_path):
    manager = ResourceManager(tmp_path / 'ledger.json')
    record, process = manager.spawn_owned_process([sys.executable, '-c', 'import time;time.sleep(60)'],
        cwd=tmp_path, project_id='fixture', run_id='wait-order', lane_id='fixture', creator='fixture',
        ownership='supervised', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    manager._failed_creation_custody[record.resource_id] = process
    assert process.returncode is None and not process._px_tree_closed
    try:
        result = manager.reconcile_retained_custody(apply=True)
        assert result['valid']
        assert process.returncode is not None and process._handle.closed
    finally:
        manager.reconcile_retained_custody(apply=True)


@pytest.mark.parametrize('alias', [False, True])
def test_recovery_retries_publication_once_per_physical_owner(tmp_path, monkeypatch, alias):
    manager = ResourceManager(tmp_path / 'ledger.json')
    failure = RuntimeError('capture construction failed')
    original_update = manager.update
    def update(resource_id, **changes):
        if changes.get('cleanup_result') == 'supervision_failed_closed':
            raise OSError('failed-state publication unavailable')
        return original_update(resource_id, **changes)
    def capture(*args, **kwargs):
        raise failure
    with monkeypatch.context() as patch:
        patch.setattr(manager, 'update', update)
        patch.setattr(supervisor_module, '_BoundedCapture', capture)
        with pytest.raises(RuntimeError) as caught:
            ProcessSupervisor(manager).run([sys.executable, '-c', 'pass'], cwd=tmp_path,
                action=_action(tmp_path), project_id='fixture', run_id='publication', lane_id='fixture', creator='fixture')
        assert caught.value is failure
    custody = next(iter(manager._supervision_failures.values()))
    assert custody['physical_completed'] and custody['pending_publication']
    if alias:
        manager._supervision_failures['second-key-for-same-owner'] = custody
    result = manager.reconcile_retained_custody(apply=True)
    assert result['valid'] and not manager._supervision_failures
    record = manager.ledger.get(custody['record'].resource_id)
    assert record.run_state == 'failed' and record.status == 'reclaimed'
    receipts = [json.loads(path.read_bytes()) for path in manager.receipt_dir.glob('*.json')]
    assert len(receipts) == 1 and len(result['outcomes']) == 1


def test_remaining_recovery_deadline_reaches_each_blocking_wait(tmp_path, monkeypatch):
    manager = ResourceManager(tmp_path / 'ledger.json')
    clock = [100.0]
    waits = []
    class Job:
        handle = 1
        def terminate(self):
            pass
        def wait_closed(self, timeout, interval):
            waits.append(('job', timeout))
            clock[0] += timeout
            return False
    class Process:
        pid = 99999
        def wait(self, timeout):
            waits.append(('process', timeout))
            raise subprocess.TimeoutExpired(['fixture'], timeout)
    class Drain:
        ident = 1
        def join(self, timeout):
            waits.append(('drain', timeout))
        def is_alive(self):
            return True
    record = SimpleNamespace(resource_id='logical-deadline-case')
    manager._process_jobs[record.resource_id] = Job()
    monkeypatch.setattr(manager, 'update', lambda *args, **kwargs: None)
    monkeypatch.setattr(supervisor_module.time, 'monotonic', lambda: clock[0])
    budget = replace(ProcessBudgets.from_mapping(_action(tmp_path)['budget']), force_shutdown_seconds=100)
    custody = {'id': 'deadline', 'process': Process(), 'record': record, 'budget': budget, 'threads': [Drain()]}
    ProcessSupervisor(manager)._settle_failed_supervision(custody, RuntimeError('original'), deadline=100.25)
    assert waits == [('job', 0.25), ('process', 0.0), ('drain', 0.0)]
    assert custody['settlement']['custody_retained']


@pytest.mark.parametrize('terminal', ['failed', 'cancelled'])
def test_normal_terminal_publication_is_retained_for_recovery(tmp_path, monkeypatch, terminal):
    manager = ResourceManager(tmp_path / 'ledger.json')
    original_update = manager.update
    failure = OSError('terminal publication failed')
    def update(resource_id, **changes):
        if changes.get('run_state') == terminal:
            raise failure
        return original_update(resource_id, **changes)
    cancel = threading.Event()
    original_spawn = manager.spawn_owned_process
    def spawn(*args, **kwargs):
        result = original_spawn(*args, **kwargs)
        if terminal == 'cancelled':
            cancel.set()
        return result
    code = 'import sys;sys.exit(7)' if terminal == 'failed' else 'import time;time.sleep(60)'
    with monkeypatch.context() as patch:
        patch.setattr(manager, 'update', update)
        patch.setattr(manager, 'spawn_owned_process', spawn)
        with pytest.raises(OSError) as caught:
            ProcessSupervisor(manager).run([sys.executable, '-c', code], cwd=tmp_path,
                action=_action(tmp_path, graceful_shutdown_seconds=0.05),
                project_id='fixture', run_id='terminal', lane_id='fixture', creator='fixture', cancel_event=cancel)
        assert caught.value is failure
    custody = next(iter(manager._supervision_failures.values()))
    assert custody['pending_publication']['run_state'] == terminal
    assert manager.reconcile_retained_custody(apply=True)['valid']
    record = manager.ledger.get(custody['record'].resource_id)
    assert record.run_state == terminal and record.status == 'reclaimed'
    assert not manager._supervision_failures


@pytest.mark.parametrize('value', [True, '1', float('inf'), float('nan'), -1, 0])
def test_completion_deadline_rejects_invalid_values_before_owner_access(tmp_path, value):
    manager = ResourceManager(tmp_path / 'ledger.json')
    class ForbiddenOwners(dict):
        def get(self, *args):
            pytest.fail('owner accessed before deadline admission')
    manager._processes = ForbiddenOwners()
    with pytest.raises(ValueError, match='completion deadline'):
        manager.complete_process('unacquired', deadline=value)
    assert not manager.ledger.path.exists()


@pytest.mark.parametrize('value', [1, 'false', None, []])
def test_recovery_apply_requires_an_actual_boolean(tmp_path, value):
    manager = ResourceManager(tmp_path / 'ledger.json')
    with pytest.raises(ValueError, match='actual boolean'):
        manager.reconcile_retained_custody(apply=value)
    assert not manager.ledger.path.exists()
