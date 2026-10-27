"""Containment outcomes must be independently established, never inferred."""
import ctypes
from types import SimpleNamespace

import pytest

from runtime.gremlin import host_enforcement_backend as owner
from runtime.gremlin import host_process_observer as observer


def backend(monkeypatch, snapshots):
    supervisor = SimpleNamespace(handle=1, terminate=lambda code: None)
    value = owner.ProcessSupervisorEnforcementBackend(supervisor_lookup=lambda key: supervisor)
    images = iter(snapshots)
    monkeypatch.setattr(value, "_job_process_pids", lambda handle: next(images))
    return value


def test_partial_suspend_cannot_claim_frozen(monkeypatch):
    value = backend(monkeypatch, [[100, 101], [100, 101]])
    monkeypatch.setattr(value, "_suspend_pid", lambda pid, **k: pid == 100)
    result = value.freeze({"job_object_id": "job", "pid": 100})
    assert result["frozen"] is False
    assert result["expected_pids"] == [100, 101]
    assert result["failed_pids"] == [101]


def test_membership_growth_during_suspend_is_unconfirmed(monkeypatch):
    value = backend(monkeypatch, [[100], [100, 101]])
    monkeypatch.setattr(value, "_suspend_pid", lambda pid, **k: True)
    assert value.freeze({"job_object_id": "job", "pid": 100})["frozen"] is False


def test_all_members_suspended_and_stable_is_confirmed(monkeypatch):
    value = backend(monkeypatch, [[100, 101], [100, 101]])
    monkeypatch.setattr(value, "_suspend_pid", lambda pid, **k: True)
    assert value.freeze({"job_object_id": "job", "pid": 100})["frozen"] is True


@pytest.mark.parametrize("remaining", [[100], []])
def test_termination_requires_empty_job_postcondition(monkeypatch, remaining):
    value = backend(monkeypatch, [[100], remaining])
    # Keep the deterministic postcondition probe bounded in unit fixtures.
    monkeypatch.setattr(value, "_termination_wait_seconds", 0, raising=False)
    result = value.terminate_tree({"job_object_id": "job", "pid": 100})
    assert result["terminated"] is (not remaining)


def test_wrong_pid_cannot_suspend_another_job(monkeypatch):
    value = backend(monkeypatch, [[100]])
    suspended = []
    monkeypatch.setattr(value, "_suspend_pid", lambda pid, **k: suspended.append(pid) or True)
    assert value.freeze({"job_object_id": "job", "pid": 999})["frozen"] is False
    assert suspended == []


class Function:
    def __init__(self, call):
        self.call = call
    def __call__(self, *args):
        return self.call(*args)


def test_job_query_resizes_beyond_64_and_preserves_pointer_width(monkeypatch):
    pids = list(range(100, 170))
    capacities = []
    def query(handle, kind, output, size, returned):
        length = size.value if hasattr(size, "value") else size
        capacity = (length - 8) // ctypes.sizeof(ctypes.c_size_t)
        capacities.append(capacity)
        header = ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))
        header[0] = len(pids)
        header[1] = min(capacity, len(pids))
        values = ctypes.cast(ctypes.addressof(output._obj) + 8, ctypes.POINTER(ctypes.c_size_t))
        for i, pid in enumerate(pids[:capacity]):
            values[i] = pid
        if capacity < len(pids):
            ctypes.set_last_error(234)
            return 0
        return 1
    api = SimpleNamespace(QueryInformationJobObject=Function(query))
    monkeypatch.setattr(owner.ctypes, "WinDLL", lambda *a, **k: api)
    assert owner.ProcessSupervisorEnforcementBackend()._job_process_pids(1) == pids
    assert len(capacities) >= 2 and capacities[-1] >= 70


def test_query_failure_is_not_empty_job_proof(monkeypatch):
    def fail(*args):
        ctypes.set_last_error(5)
        return 0
    monkeypatch.setattr(owner.ctypes, "WinDLL", lambda *a, **k: SimpleNamespace(
        QueryInformationJobObject=Function(fail)))
    with pytest.raises(OSError):
        owner.ProcessSupervisorEnforcementBackend()._job_process_pids(1)


@pytest.mark.parametrize("member", [False, True])
def test_suspend_pins_process_handle_and_rechecks_job_membership(monkeypatch, member):
    suspended, closed = [], []
    def membership(handle, job, output):
        ctypes.cast(output, ctypes.POINTER(owner.wintypes.BOOL))[0] = member
        return True
    api = SimpleNamespace(
        OpenProcess=Function(lambda *a: 123),
        CloseHandle=Function(lambda handle: closed.append(handle)),
        IsProcessInJob=Function(membership),
    )
    native = SimpleNamespace(NtSuspendProcess=Function(lambda handle: suspended.append(handle) or 0))
    monkeypatch.setattr(owner.ctypes, "WinDLL", lambda name, **k: api if name == "kernel32" else native)
    assert owner.ProcessSupervisorEnforcementBackend._suspend_pid(100, job_handle=1) is member
    assert bool(suspended) is member
    assert closed == [123]


def test_real_windows_process_snapshot_includes_current_process():
    import os
    assert any(row["pid"] == os.getpid() for row in observer._snapshot_rows())


def test_observation_includes_grandchildren_without_cycles(monkeypatch):
    rows = [
        {"pid": 11, "parent_pid": 10, "image": "child"},
        {"pid": 12, "parent_pid": 11, "image": "grandchild"},
        {"pid": 13, "parent_pid": 12, "image": "great-grandchild"},
        {"pid": 99, "parent_pid": 98, "image": "unrelated"},
        {"pid": 10, "parent_pid": 13, "image": "cycle"},
    ]
    monkeypatch.setattr(observer, "_snapshot_rows", lambda: rows)
    assert {row["pid"] for row in observer.observe_host_children(host_pid=10)} == {11, 12, 13}
