"""Native creation proof with durable fixture intent before every child."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from runtime.process_supervisor import _WindowsContainedPopen, _WindowsJob
from runtime.resource_lifecycle import ResourceLedger, ResourceRecord

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows creation contract')


@pytest.fixture
def custody(tmp_path):
    ledger = ResourceLedger(tmp_path / 'resources.json')
    record = ResourceRecord(
        resource_id='process-' + uuid4().hex, resource_type='process',
        project_id='native-fixture', run_id='native-creation', lane_id='fixture',
        creator='test_windows_creation', classification='ephemeral',
        created_at='2026-09-10T00:00:00Z', last_activity_at='2026-09-10T00:00:00Z',
        expected_cleanup_event='fixture_finally', retention_required=False,
        status='creation_pending')
    ledger.upsert(record)
    job = _WindowsJob()
    processes = []

    def retain(process):
        processes.append(process)
        ledger.upsert(replace(record, pid=process.pid, status='active'))

    try:
        yield job, retain, ledger, record
    finally:
        if job.handle:
            job.terminate()
            assert job.wait_closed(5.0, 0.02)
            job.close()
        for process in processes:
            process.wait(timeout=5)
            process._close_initial_thread()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        ledger.upsert(replace(record, active=False, status='reclaimed',
                              cleanup_result='fixture_job_closed'))


@pytest.mark.parametrize('text', [True, False])
def test_native_stdio_environment_and_path(custody, tmp_path, text):
    job, retain, ledger, record = custody
    environment = dict(os.environ, PX_NATIVE_VALUE='native-value')
    process = _WindowsContainedPopen(
        [sys.executable, '-c', 'import os,sys;print(os.environ["PX_NATIVE_VALUE"]);sys.stderr.write("error-line")'],
        creation_job=job, creation_hook=retain, cwd=Path(tmp_path),
        executable=Path(sys.executable), env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=text, close_fds=True)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0
    assert stdout.strip() == ('native-value' if text else b'native-value')
    assert stderr == ('error-line' if text else b'error-line')
    assert ledger.get(record.resource_id).pid == process.pid
    assert job.wait_closed(5.0, 0.02)


def test_release_style_file_output_and_merged_stderr(custody, tmp_path):
    job, retain, _, _ = custody
    output = tmp_path / 'owned-output.log'
    with output.open('w', encoding='utf-8') as stream:
        process = _WindowsContainedPopen(
            [sys.executable, '-c', 'import sys;print("stdout");sys.stderr.write("stderr");sys.exit(7)'],
            creation_job=job, creation_hook=retain, stdin=None,
            stdout=stream, stderr=subprocess.STDOUT, text=True, close_fds=True)
        assert process.wait(timeout=10) == 7
    assert set(output.read_text().split()) == {'stdout', 'stderr'}
    assert job.wait_closed(5.0, 0.02)


def test_creation_flag_new_process_group(custody):
    job, retain, _, _ = custody
    process = _WindowsContainedPopen(
        [sys.executable, '-c', 'print("group")'], creation_job=job,
        creation_hook=retain, stdin=None, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, close_fds=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    assert process.communicate(timeout=10) == ('group\n', '')
    assert process.returncode == 0
    assert job.wait_closed(5.0, 0.02)


def test_failed_second_creation_cannot_kill_existing_member(custody):
    job, retain, _, _ = custody
    process = _WindowsContainedPopen(
        [sys.executable, '-c', 'import time;time.sleep(60)'], creation_job=job,
        creation_hook=retain, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)
    with pytest.raises(ValueError):
        _WindowsContainedPopen([], creation_job=job, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               close_fds=True)
    assert process.poll() is None, 'failed second launch must not terminate the first'
    assert job.handle is not None


def test_suspended_creation_resumes_exact_owned_thread(custody):
    job, retain, _, _ = custody
    process = _WindowsContainedPopen(
        [sys.executable, '-c', 'print("resumed")'], creation_job=job,
        creation_hook=retain, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, close_fds=True, creationflags=0x00000004)
    assert process.poll() is None
    assert job.active_processes() == 1
    assert process.resume_owned() == 1
    assert process.communicate(timeout=10) == ('resumed\n', '')
    assert process.returncode == 0
    with pytest.raises(ValueError, match='no owned suspended'):
        process.resume_owned()


def test_failed_job_handle_close_retains_custody(custody, monkeypatch):
    job, _, _, _ = custody
    handle = job.handle
    with monkeypatch.context() as patch:
        patch.setattr(job._kernel32, 'CloseHandle', lambda value: 0)
        with pytest.raises(OSError, match='CloseHandle'):
            job.close()
        assert job.handle == handle
        assert job.active_processes() == 0
    job.close()
    assert job.handle is None


def test_raw_process_handle_closed_if_transfer_fails(custody, monkeypatch):
    import ctypes
    from ctypes import wintypes

    job, _, _, _ = custody
    raw = []
    failure = MemoryError('handle wrapper allocation failed')

    def fail(handle):
        raw.append(handle)
        raise failure

    monkeypatch.setattr(_WindowsContainedPopen, '_wrap_created_handle', staticmethod(fail))
    with pytest.raises(MemoryError) as caught:
        _WindowsContainedPopen(
            [sys.executable, '-c', 'import time;time.sleep(60)'], creation_job=job,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
    assert caught.value is failure
    assert failure.process_creation_outcome == {'created': True, 'tree_closed': True}
    assert len(raw) == 1
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    flags = wintypes.DWORD()
    assert not kernel.GetHandleInformation(raw[0], ctypes.byref(flags))
    assert ctypes.get_last_error() == 6


def test_failed_installed_process_handle_close_retains_owner(custody, monkeypatch):
    job, retain, _, _ = custody
    failure = RuntimeError('registration primary')

    class RefusingClose(subprocess.Handle):
        def Close(self):
            raise OSError('native process handle close refused')

    def fail(process):
        retain(process)
        raise failure

    monkeypatch.setattr(_WindowsContainedPopen, '_wrap_created_handle', staticmethod(RefusingClose))
    with pytest.raises(RuntimeError) as caught:
        _WindowsContainedPopen(
            [sys.executable, '-c', 'import time;time.sleep(60)'], creation_job=job,
            creation_hook=fail, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
    assert caught.value is failure
    owner = failure.process_creation_owner
    assert owner._px_unclosed_process_handle
    assert not owner._handle.closed
    assert failure.process_creation_outcome['tree_closed']
    subprocess.Handle.Close(owner._handle)
    owner._px_unclosed_process_handle = False
    assert owner._handle.closed


def test_failed_nonsuspended_thread_close_retains_owner(custody, monkeypatch):
    from ctypes import wintypes

    job, retain, _, _ = custody
    failure = RuntimeError('registration primary')
    kernel = job._kernel32
    kernel.GetThreadId.argtypes = [wintypes.HANDLE]
    kernel.GetThreadId.restype = wintypes.DWORD
    original_close = kernel.CloseHandle

    def refuse_thread(handle):
        if kernel.GetThreadId(handle):
            return 0
        return original_close(handle)

    def fail(process):
        retain(process)
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(kernel, 'CloseHandle', refuse_thread)
        with pytest.raises(RuntimeError) as caught:
            _WindowsContainedPopen(
                [sys.executable, '-c', 'import time;time.sleep(60)'], creation_job=job,
                creation_hook=fail, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True)
        assert caught.value is failure
        owner = failure.process_creation_owner
        assert kernel.GetThreadId(owner._px_unclosed_raw_thread)
        assert failure.process_creation_outcome['tree_closed']
    assert original_close(owner._px_unclosed_raw_thread)
    owner._px_unclosed_raw_thread = None


def test_failed_wait_retains_installed_process_handle(custody, monkeypatch):
    job, retain, _, _ = custody
    failure = RuntimeError('registration primary')

    def fail(process):
        retain(process)
        raise failure

    def refuse_wait(self, *args, **kwargs):
        raise OSError('wait unavailable')

    with monkeypatch.context() as patch:
        patch.setattr(_WindowsContainedPopen, 'wait', refuse_wait)
        with pytest.raises(RuntimeError) as caught:
            _WindowsContainedPopen(
                [sys.executable, '-c', 'import time;time.sleep(60)'], creation_job=job,
                creation_hook=fail, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True)
        assert caught.value is failure
        owner = failure.process_creation_owner
        assert not owner._handle.closed
    owner.wait(timeout=5)
    owner._handle.Close()
    owner._px_unclosed_process_handle = False


def test_post_creation_registration_error_closes_child(custody):
    job, retain, _, _ = custody
    error = RuntimeError('registration unavailable')

    def fail(process):
        retain(process)
        raise error

    with pytest.raises(RuntimeError) as caught:
        _WindowsContainedPopen(
            [sys.executable, '-c', 'import time;time.sleep(60)'],
            creation_job=job, creation_hook=fail, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    assert caught.value is error
    assert error.process_creation_outcome == {'created': True, 'tree_closed': True}
    assert job.handle is None


def test_native_creation_failure_reports_no_child(custody, tmp_path):
    job, retain, _, _ = custody
    with pytest.raises(OSError) as caught:
        _WindowsContainedPopen(
            [str(tmp_path / 'nonexistent.exe')], creation_job=job,
            creation_hook=retain, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True)
    assert caught.value.process_creation_outcome == {'created': False, 'tree_closed': True}
    assert job.handle is None


def test_cleanup_error_does_not_replace_registration_error(custody, monkeypatch):
    job, retain, _, _ = custody
    error = RuntimeError('registration primary')
    original_close = _WindowsContainedPopen._close_pipe_fds

    def close_then_fail(self, *args):
        original_close(self, *args)
        raise OSError('pipe closure diagnostic')

    def fail(process):
        retain(process)
        raise error

    monkeypatch.setattr(_WindowsContainedPopen, '_close_pipe_fds', close_then_fail)
    with pytest.raises(RuntimeError) as caught:
        _WindowsContainedPopen(
            [sys.executable, '-c', 'import time;time.sleep(60)'],
            creation_job=job, creation_hook=fail, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    assert caught.value is error
    assert error.process_creation_outcome['tree_closed'] is True
    assert error.process_creation_cleanup_errors == ('OSError',)


def _owner_dies_during_creation(root, descendant=False):
    ledger = ResourceLedger(root / 'inner-resources.json')
    record = ResourceRecord(
        resource_id='process-inner', resource_type='process', project_id='fixture',
        run_id='owner-death', lane_id='fixture', creator='native-owner',
        classification='ephemeral', created_at='2026-09-10T00:00:00Z',
        last_activity_at='2026-09-10T00:00:00Z',
        expected_cleanup_event='owner_death', retention_required=False,
        status='creation_pending')
    ledger.upsert(record)
    job = _WindowsJob()

    def die_after_observer_has_handle(process):
        ledger.upsert(replace(record, pid=process.pid, status='active'))
        if descendant:
            deadline = time.monotonic() + 10
            while not (root / 'descendant-ready').exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('descendant readiness deadline exceeded')
                time.sleep(0.01)
        temporary = root / 'ready.tmp'
        temporary.write_text(str(process.pid), encoding='ascii')
        temporary.replace(root / 'ready')
        deadline = time.monotonic() + 10
        while not (root / 'ack').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('observer did not acknowledge child handle')
            time.sleep(0.01)
        os._exit(91)

    command = ([sys.executable, '-m', 'tests.test_process_lifecycle_windows_creation', '--descendant', str(root)]
               if descendant else [sys.executable, '-c', 'import time;time.sleep(60)'])
    _WindowsContainedPopen(
        command, cwd=Path(__file__).resolve().parents[1], creation_job=job,
        creation_hook=die_after_observer_has_handle, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


@pytest.mark.parametrize('descendant', [False, True])
def test_hard_owner_death_during_creation_without_outer_cleanup(custody, tmp_path, descendant):
    import ctypes
    from ctypes import wintypes

    outer_job, retain, _, _ = custody
    owner = _WindowsContainedPopen(
        [sys.executable, '-m', 'tests.test_process_lifecycle_windows_creation', '--owner', str(tmp_path), str(int(descendant))],
        cwd=Path(__file__).resolve().parents[1], creation_job=outer_job, creation_hook=retain, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, close_fds=True)
    deadline = time.monotonic() + 15
    while not (tmp_path / 'ready').exists():
        assert owner.poll() is None, 'owner exited before child observation'
        assert time.monotonic() < deadline, 'child readiness deadline exceeded'
        time.sleep(0.01)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        for ready in (['ready', 'descendant-ready'] if descendant else ['ready']):
            handle = kernel.OpenProcess(0x00100000, False, int((tmp_path / ready).read_text()))
            assert handle, 'retain exact child identity before allowing owner death'
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        (tmp_path / 'ack').write_text('observer owns exact child handle', encoding='ascii')
        assert owner.wait(timeout=10) == 91
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
        # This Job is deliberately still open: it has not terminated any child.
        assert outer_job.handle is not None
        assert outer_job.active_processes() == 0
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


def _descendant(root):
    ledger = ResourceLedger(root / 'grandchild-resources.json')
    record = ResourceRecord(
        resource_id='process-grandchild', resource_type='process', project_id='fixture',
        run_id='owner-death', lane_id='fixture', creator='descendant',
        classification='ephemeral', created_at='2026-09-10T00:00:00Z',
        last_activity_at='2026-09-10T00:00:00Z',
        expected_cleanup_event='inherited_job_closure', retention_required=False,
        status='creation_pending')
    ledger.upsert(record)
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time;time.sleep(60)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True)
    ledger.upsert(replace(record, pid=process.pid, status='active'))
    temporary = root / 'descendant-ready.tmp'
    temporary.write_text(str(process.pid), encoding='ascii')
    temporary.replace(root / 'descendant-ready')
    process.wait(timeout=60)


if __name__ == '__main__' and sys.argv[1:2] == ['--owner']:
    _owner_dies_during_creation(Path(sys.argv[2]), bool(int(sys.argv[3])))
elif __name__ == '__main__' and sys.argv[1:2] == ['--descendant']:
    _descendant(Path(sys.argv[2]))
