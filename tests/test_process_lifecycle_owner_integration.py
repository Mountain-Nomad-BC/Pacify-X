"""One causal matrix across intent, creation, setup, drains and publication."""
import os
import subprocess
import sys

import pytest

from runtime import process_supervisor as supervisor_module
from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager
from tests.test_process_supervisor import _action

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows integrated ownership')


@pytest.fixture
def manager(tmp_path):
    value = ResourceManager(tmp_path / 'resources.json')
    try:
        yield value
    finally:
        for job in list(value._process_jobs.values()):
            if job.handle:
                job.terminate()
                assert job.wait_closed(5, 0.02)
                job.close()
        for process in list(value._processes.values()):
            process.wait(timeout=5)
            value._close_process_handles(process)
        for owner in value._failed_creation_custody.values():
            owner.close_retained_creation_handles()


def spawn(manager, root):
    return manager.spawn_owned_process(
        [sys.executable, '-c', 'import time;time.sleep(60)'], cwd=root,
        project_id='fixture', run_id='owner-integration', lane_id='matrix', creator='fixture',
        ownership='supervised', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_intent_publication_failure_prevents_native_creation(manager, tmp_path, monkeypatch):
    failure = OSError('intent storage unavailable')

    def fail(record):
        raise failure

    monkeypatch.setattr(manager.ledger, 'upsert', fail)
    monkeypatch.setattr(supervisor_module, '_WindowsJob', lambda: pytest.fail('native creation preceded intent'))
    with pytest.raises(OSError) as caught:
        spawn(manager, tmp_path)
    assert caught.value is failure
    assert not manager._processes and not manager._process_jobs


@pytest.mark.parametrize('persistent,hostile', [(False, False), (True, False), (True, True)])
def test_registration_failure_keeps_physical_custody(manager, tmp_path, monkeypatch, persistent, hostile):
    class Hostile(RuntimeError):
        def __setattr__(self, name, value):
            raise RuntimeError('exception attributes refused')

    failure = Hostile('registration') if hostile else RuntimeError('registration')
    original = manager.ledger.upsert
    calls = 0

    def publication(record):
        nonlocal calls
        calls += 1
        if calls == 2 or persistent and calls > 1:
            raise failure
        original(record)

    with monkeypatch.context() as patch:
        patch.setattr(manager.ledger, 'upsert', publication)
        with pytest.raises(RuntimeError) as caught:
            spawn(manager, tmp_path)
        assert caught.value is failure
    assert all(process.returncode is not None for process in manager._processes.values())
    assert all(not job.handle for job in manager._process_jobs.values())
    if persistent:
        assert manager._failed_creation_custody
        assert manager.ledger.observe()[0].cleanup_result == 'creation_pending'
    else:
        assert not manager._processes and not manager._failed_creation_custody
        assert not manager.ledger.observe()[0].active


@pytest.mark.parametrize('fault', ['identity', 'capture', 'first_thread', 'second_thread', 'resume', 'receipt', 'disk', 'drain'])
def test_supervisor_failure_matrix_closes_tree_and_drains(manager, tmp_path, monkeypatch, fault):
    supervisor = ProcessSupervisor(manager)
    retained = {}
    real_spawn = manager.spawn_owned_process
    def retain_spawn(*args, **kwargs):
        record, process = real_spawn(*args, **kwargs)
        retained.update(process=process, job=manager._process_jobs[record.resource_id])
        return record, process
    monkeypatch.setattr(manager, 'spawn_owned_process', retain_spawn)
    real_run = supervisor._run_with_custody
    def retain_custody(*args, **kwargs):
        retained['custody'] = kwargs['_custody']
        return real_run(*args, **kwargs)
    monkeypatch.setattr(supervisor, '_run_with_custody', retain_custody)
    failure = RuntimeError('injected-' + fault)
    if fault == 'identity':
        original = supervisor_module._process_start_fingerprint
        calls = 0

        def identity(pid):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise failure
            return original(pid)
        monkeypatch.setattr(supervisor_module, '_process_start_fingerprint', identity)
    elif fault == 'capture':
        def capture(*args, **kwargs):
            raise failure
        monkeypatch.setattr(supervisor_module, '_BoundedCapture', capture)
    elif fault in {'first_thread', 'second_thread'}:
        original = supervisor_module.threading.Thread.start
        calls = 0

        def start(thread):
            nonlocal calls
            if thread._target is supervisor_module._drain:
                calls += 1
                if calls == (1 if fault == 'first_thread' else 2):
                    raise failure
            return original(thread)
        monkeypatch.setattr(supervisor_module.threading.Thread, 'start', start)
    elif fault == 'resume':
        def resume(process):
            raise failure
        monkeypatch.setattr(supervisor_module._WindowsContainedPopen, 'resume_owned', resume)
    elif fault == 'receipt':
        def receipt(result):
            raise failure
        monkeypatch.setattr(supervisor, '_receipt', receipt)
    elif fault == 'disk':
        calls = 0
        def disk(paths):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise failure
            return 0
        monkeypatch.setattr(supervisor_module, '_disk_consumption_bytes', disk)
    else:
        def feed(self, chunk):
            raise failure
        monkeypatch.setattr(supervisor_module._BoundedCapture, 'feed', feed)
    code = 'print("normal")' if fault == 'receipt' else 'import time;print("ready",flush=True);time.sleep(60)'
    action = _action(tmp_path)
    if fault == 'disk':
        action['disk_consumption_paths'] = [str(tmp_path)]
    with pytest.raises(RuntimeError) as caught:
        supervisor.run([sys.executable, '-c', code], cwd=tmp_path, action=action,
                       project_id='fixture', run_id='matrix', lane_id='fixture', creator='fixture')
    assert caught.value is failure
    assert retained['process'].returncode is not None
    assert retained['process']._handle.closed
    assert retained['job'].handle is None
    assert retained['process'].stdout.closed and retained['process'].stderr.closed
    assert all(not thread.is_alive() for thread in retained['custody']['threads'])
    assert all(process.returncode is not None for process in manager._processes.values())
    assert all(not job.handle for job in manager._process_jobs.values())
    assert all(not record.active for record in manager.ledger.observe())
    assert failure.supervision_outcome['custody_retained'] is False
    if fault == 'receipt':
        assert failure.supervision_outcome['post_closure_failure'] is True


def test_successful_supervision_uses_creation_time_job(manager, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('late thread enumeration used instead of exact creation handle')
    monkeypatch.setattr(supervisor_module._WindowsJob, 'resume_process', forbidden)
    result = ProcessSupervisor(manager).run(
        [sys.executable, '-c', 'print("integrated")'], cwd=tmp_path, action=_action(tmp_path),
        project_id='fixture', run_id='success', lane_id='fixture', creator='fixture')
    assert result.exit_code == 0 and result.tree_closed
    assert result.stdout.text.strip() == 'integrated'
    assert not manager._processes and not manager._process_jobs


@pytest.mark.parametrize('hostile', [False, True])
def test_registration_oserror_is_not_reported_as_unstarted(manager, tmp_path, monkeypatch, hostile):
    original = manager.ledger.upsert
    class Hostile(OSError):
        def __setattr__(self, name, value):
            raise RuntimeError('exception attributes refused')
    failure = (Hostile if hostile else OSError)('registration failed after creation')
    calls = 0
    def upsert(record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise failure
        original(record)
    monkeypatch.setattr(manager.ledger, 'upsert', upsert)
    with pytest.raises(OSError) as caught:
        ProcessSupervisor(manager).run([sys.executable, '-c', 'pass'], cwd=tmp_path,
            action=_action(tmp_path), project_id='fixture', run_id='oserror', lane_id='fixture', creator='fixture')
    assert caught.value is failure
    if not hostile:
        assert failure.resource_creation_outcome['created'] is True
        assert failure.resource_creation_outcome['tree_closed'] is True
    assert not manager._processes and not manager._process_jobs


def test_durable_root_cleanup_precedes_failed_ledger_read(manager, tmp_path, monkeypatch):
    record, process = manager.spawn_owned_process(
        [sys.executable, '-c', 'import time;time.sleep(60)'], cwd=tmp_path,
        project_id='fixture', run_id='durable', lane_id='fixture', creator='fixture',
        ownership='durable', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failure = RuntimeError('readiness failed')
    def unreadable(*args):
        raise OSError('ledger unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(manager.ledger, 'get', unreadable)
        outcome = manager.settle_failed_launch(record.resource_id, failure)
    assert process.returncode is not None
    assert outcome['root_closed'] and not outcome['tree_closed']
    assert outcome['custody_retained'] and outcome['cleanup_errors'] == ['OSError']
    manager.terminate_owned_process(record.resource_id)


def test_cancellation_closes_job_and_owned_handles(manager, tmp_path):
    record, process = spawn(manager, tmp_path)
    job = manager._process_jobs[record.resource_id]
    receipt = manager.terminate_owned_process(record.resource_id)
    assert receipt.resources_reclaimed == 1 and not receipt.errors
    assert process.returncode is not None and process._handle.closed
    assert job.handle is None
    assert not manager._processes and not manager._process_jobs


def test_active_process_prevents_workspace_reclamation(manager, tmp_path):
    from runtime.resource_lifecycle import RunState
    workspace = manager.create_workspace(tmp_path, project_id='fixture', run_id='workspace', lane_id='fixture', creator='fixture')
    record, process = manager.spawn_owned_process([sys.executable, '-c', 'import time;time.sleep(60)'],
        cwd=tmp_path, project_id='fixture', run_id='workspace', lane_id='fixture', creator='fixture',
        ownership='supervised', parent_resource_id=workspace.resource_id)
    manager.update(workspace.resource_id, active=False, run_state=RunState.FAILED.value)
    receipt = manager.reclaim(workspace.resource_id, reason='failure', apply=True)
    assert receipt.resources_reclaimed == 0
    manager.terminate_owned_process(record.resource_id)
    assert process.returncode is not None


def test_failed_native_liveness_close_keeps_handle(monkeypatch):
    owner = supervisor_module._open_owner_liveness(os.getpid())
    kernel, handle = owner.handle
    try:
        with monkeypatch.context() as patch:
            patch.setattr(kernel, 'CloseHandle', lambda value: 0)
            with pytest.raises(OSError):
                owner.close()
            assert owner.handle == (kernel, handle)
    finally:
        owner.close()
