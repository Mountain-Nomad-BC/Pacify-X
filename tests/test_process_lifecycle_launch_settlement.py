"""Caller fault matrix: real owned roots, inert payloads, exact original errors."""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime import studio_worker_launch as studio
from runtime.resource_lifecycle import ResourceManager
from scripts.run_release_candidate import AutomationBlocked, SubprocessOwners
from tests.test_release_candidate_driver import config


@pytest.mark.parametrize('phase', ['sign', 'write', 'observer', 'state'])
def test_studio_launch_failure_settles_request_after_workers(tmp_path, monkeypatch, phase):
    manager = ResourceManager(tmp_path / 'resources.json')
    processes = []
    failure = RuntimeError('injected-' + phase)
    real_spawn = manager.spawn_owned_process
    def inert_spawn(command, **kwargs):
        assert kwargs['ownership'] == 'durable'
        record, process = real_spawn([sys.executable, '-c', 'import time;time.sleep(60)'], **kwargs)
        processes.append(process)
        return record, process
    monkeypatch.setattr(manager, 'spawn_owned_process', inert_spawn)
    calls = 0
    def read(run_id):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise failure
        return {'state': 'queued'}
    def sign(value):
        if phase == 'sign':
            raise failure
        return value
    real_write = studio.write_json_atomic
    def write(path, value):
        real_write(path, value)
        if phase == 'write':
            raise failure
    monkeypatch.setattr(studio, 'write_json_atomic', write)
    def observer(**kwargs):
        if phase == 'observer':
            raise failure
        record, process = inert_spawn([], cwd=tmp_path, project_id=tmp_path.name,
            run_id='observer', lane_id='fixture', creator='fixture', ownership='durable',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return record.resource_id, process.pid, 'observer'
    monkeypatch.setattr(studio, '_launch_terminal_observer', observer)
    try:
        with pytest.raises(RuntimeError) as caught:
            studio.launch_studio_worker(project_root=tmp_path, state_root=tmp_path / 'state',
                manager=manager, authority=SimpleNamespace(sign_receipt=sign),
                run_control=SimpleNamespace(read=read), kind='agent', run_id='fixture', payload={})
        assert caught.value is failure
        assert processes and all(process.returncode is not None for process in processes)
        if sys.platform == 'win32':
            assert all(process._handle.closed for process in processes)
        assert all(not record.active for record in manager.ledger.observe())
        assert not (tmp_path / 'state/worker-requests/fixture.json').exists()
    finally:
        for resource_id in list(manager._processes):
            manager.terminate_owned_process(resource_id)


@pytest.mark.parametrize('failure_kind', ['ledger', 'receipt'])
def test_release_timeout_preserves_original_and_settles_when_cleanup_fails(tmp_path, failure_kind):
    value = config(tmp_path)
    timeout = subprocess.TimeoutExpired(['owner'], 1)
    events = []
    class Process:
        def wait(self, **kwargs):
            raise timeout
    class Manager:
        def spawn_owned_process(self, command, **kwargs):
            assert kwargs['ownership'] == 'supervised'
            return SimpleNamespace(resource_id='process-fixture', pid=123), Process()
        def terminate_owned_process(self, resource_id):
            events.append(('cleanup', resource_id, failure_kind))
            raise OSError('injected-' + failure_kind)
        def settle_failed_launch(self, resource_id, original):
            assert original is timeout
            events.append(('settle', resource_id))
            return {'tree_closed': False, 'custody_retained': True}
    with pytest.raises(AutomationBlocked) as caught:
        SubprocessOwners(value, Manager()).run('archive_clear', (('owner', 'archive_clear'),))
    assert caught.value.__cause__ is timeout
    assert events == [('cleanup', 'process-fixture', failure_kind), ('settle', 'process-fixture')]
