from pathlib import Path
import threading
import pytest
import runtime.file_lock as locks


def test_registry_reservation_survives_owner_retirement(tmp_path):
    path = tmp_path / "control.lock"
    path.write_bytes(b"0")
    key = locks._process_lock_key(path)
    first = locks._enter_process_entry(key)
    waiter = locks._enter_process_entry(key)
    try:
        assert first is waiter
        locks._retire_if_unused(key, first)
        newcomer = locks._enter_process_entry(key)
        try:
            assert newcomer is waiter, "a reserved waiter must not split into an orphan mutex"
        finally:
            locks._retire_if_unused(key, newcomer)
    finally:
        locks._retire_if_unused(key, waiter)
    assert key not in locks._PROCESS_LOCKS


def test_first_creation_uses_the_open_file_identity(tmp_path):
    path = tmp_path / "new.lock"
    with locks.FileLock(path) as owner:
        key, _ = owner._process_entry
        assert key == locks._process_lock_key(path)


def test_thread_timeout_releases_only_its_reservation(tmp_path):
    path = tmp_path / "control.lock"
    path.write_bytes(b"0")
    errors = []
    contender = locks.FileLock(path, timeout_seconds=0.04)
    def compete():
        try:
            with contender:
                errors.append("entered")
        except locks.FileLockTimeout:
            pass
        except BaseException as error:
            errors.append(repr(error))
    with locks.FileLock(path) as owner:
        key, entry = owner._process_entry
        thread = threading.Thread(target=compete, daemon=True)
        thread.start(); thread.join(2)
        assert not thread.is_alive()
        assert not errors
        assert contender._process_entry is None
        assert contender._stream is None
        assert locks._PROCESS_LOCKS[key] is entry
    assert key not in locks._PROCESS_LOCKS


def test_same_instance_reentry_cannot_lose_owner(tmp_path):
    owner = locks.FileLock(tmp_path / "control.lock", timeout_seconds=0.03)
    with owner:
        record = owner._process_entry
        with pytest.raises(RuntimeError, match="already"):
            owner.__enter__()
        assert owner._process_entry is record
    assert record[0] not in locks._PROCESS_LOCKS


def test_heartbeat_start_failure_releases_lease_and_registry(tmp_path, monkeypatch):
    path = tmp_path / "control.lock"
    owner = locks.FileLock(path)
    def fail():
        raise RuntimeError("thread unavailable")
    monkeypatch.setattr(owner, "_start_heartbeat", fail)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        owner.__enter__()
    assert owner._stream is None
    assert owner._process_entry is None
    with locks.FileLock(path, timeout_seconds=0.2):
        pass


def test_hardlink_alias_uses_one_mutex_and_timeout_does_not_unlock_owner(tmp_path):
    import os
    path = tmp_path / "control.lock"
    path.write_bytes(b"0")
    alias = tmp_path / "alias.lock"
    os.link(path, alias)
    with locks.FileLock(path):
        with pytest.raises(locks.FileLockTimeout):
            with locks.FileLock(alias, timeout_seconds=0.03):
                pytest.fail("alias entered")
        probe = locks.FileLock(path)
        probe._stream = path.open("r+b")
        try:
            with pytest.raises(OSError):
                probe._lock_stream()
        finally:
            probe._abandon_attempt()
    assert not locks._PROCESS_LOCKS


def test_rapid_thread_handoffs_leave_no_split_mutex_or_registry_leak(tmp_path):
    import time
    path = tmp_path / "control.lock"
    active = 0
    errors = []
    count = 0
    guard = threading.Lock()
    def run():
        nonlocal active, count
        try:
            for _ in range(12):
                with locks.FileLock(path, timeout_seconds=3):
                    with guard:
                        active += 1
                        assert active == 1
                    time.sleep(0.001)
                    with guard:
                        count += 1
                        active -= 1
        except BaseException as error:
            errors.append(repr(error))
    threads = [threading.Thread(target=run, daemon=True) for _ in range(6)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(8)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert count == 72
    assert not locks._PROCESS_LOCKS


def test_close_failure_still_releases_process_registry_after_kernel_unlock(tmp_path):
    owner=locks.FileLock(tmp_path/'control.lock');owner.__enter__();record=owner._process_entry
    original=owner._stream
    class ClosingError:
        def __getattr__(self,name):return getattr(original,name)
        def close(self):original.close();raise OSError('controlled close failure')
    owner._stream=ClosingError()
    try:
        with pytest.raises(OSError,match='controlled close'):owner.__exit__(None,None,None)
        assert owner._stream is None
        assert owner._process_entry is None
        assert record[0] not in locks._PROCESS_LOCKS
    finally:
        owner._stream=None;owner._release_process_ownership()


def test_fstat_failure_closes_opened_handle_before_registry_admission(tmp_path,monkeypatch):
    owner=locks.FileLock(tmp_path/'control.lock');actual=locks.os.fstat;failed=False
    def fail(fd):
        nonlocal failed
        if not failed and owner._stream is not None and fd==owner._stream.fileno():
            failed=True;raise OSError('controlled identity query failure')
        return actual(fd)
    monkeypatch.setattr(locks.os,'fstat',fail)
    try:
        with pytest.raises(OSError,match='identity query'):owner.__enter__()
        assert owner._stream is None and owner._process_entry is None
    finally:
        if owner._stream is not None:owner._stream.close();owner._stream=None


def test_unsettled_heartbeat_retains_lease_until_writer_really_stops(tmp_path,monkeypatch):
    owner=locks.FileLock(tmp_path/'control.lock',heartbeat_interval_seconds=.01)
    owner.__enter__();actual=owner._write_record;entered=threading.Event();release=threading.Event()
    def stalled(record):
        if threading.current_thread() is owner._heartbeat_thread:
            entered.set();release.wait(4)
        return actual(record)
    monkeypatch.setattr(owner,'_write_record',stalled)
    try:
        assert entered.wait(2)
        with pytest.raises(RuntimeError,match='heartbeat unsettled'):owner.__exit__(None,None,None)
        assert owner._stream is not None and owner._process_entry is not None
    finally:
        release.set();owner._heartbeat_thread.join(2)
        assert not owner._heartbeat_thread.is_alive()
        owner.__exit__(None,None,None)
    assert owner._stream is None and owner._process_entry is None
