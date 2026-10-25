"""Real Windows enforcement backend for supervised containment.

Adapts the canonical ``ProcessSupervisor`` (Job Object custody) to the Gremlin
``EnforcementBackend`` protocol:

* ``terminate_tree``  — ``TerminateJobObject`` over the supervised Job, followed
  by a bounded independent empty-Job postcondition probe.
* ``freeze``          — suspend every process currently in the Job
  (``NtSuspendProcess``), reported as ``{"frozen": True}``.

The backend resolves the owning supervisor from the identity's ``job_object_id``
through a registry the projection host populates when it creates each supervised
custody. An unknown identity is reported unconfirmed (fail closed) — the
containment facade treats that as an enforcement failure, never as success.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
from typing import Callable

SCHEMA_VERSION = "px.host-enforcement-backend/1.0"

_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOBOBJECT_PROCESS_COUNT = 64
_MAX_JOB_PROCESSES = 65_536


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", ctypes.c_uint),
        ("NumberOfProcessIdsInList", ctypes.c_uint),
        ("ProcessIdList", ctypes.c_size_t * _JOBOBJECT_PROCESS_COUNT),
    ]


class ProcessSupervisorEnforcementBackend:
    """Job-backed terminate/freeze against supervised process custody."""

    available = True

    #: Live supervised-custody registry: job_object_id -> ProcessSupervisor.
    #: The projection host registers each supervisor when it creates custody.
    REGISTRY: dict[str, object] = {}
    _termination_wait_seconds = 1.0

    def __init__(self, *, supervisor_lookup: Callable[[str], object] | None = None) -> None:
        self._lookup = supervisor_lookup or self.REGISTRY.get

    # -- helpers ---------------------------------------------------------
    def _supervisor_for(self, identity: dict[str, object]):
        job_id = identity.get("job_object_id")
        if not job_id:
            return None
        supervisor = self._lookup(str(job_id))
        if supervisor is None or not hasattr(supervisor, "terminate"):
            return None
        return supervisor

    def _job_process_pids(self, job_handle: wintypes.HANDLE) -> list[int]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel32.QueryInformationJobObject
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        capacity = _JOBOBJECT_PROCESS_COUNT
        while capacity <= _MAX_JOB_PROCESSES:
            class ProcessList(ctypes.Structure):
                _fields_ = [
                    ("NumberOfAssignedProcesses", ctypes.c_uint32),
                    ("NumberOfProcessIdsInList", ctypes.c_uint32),
                    ("ProcessIdList", ctypes.c_size_t * capacity),
                ]
            info = ProcessList()
            ok = query(job_handle, _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                       ctypes.byref(info), ctypes.sizeof(info), None)
            error = 0 if ok else ctypes.get_last_error()
            if not ok and error != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(error)
            assigned = int(info.NumberOfAssignedProcesses)
            count = int(info.NumberOfProcessIdsInList)
            if count > capacity or count > assigned:
                raise ValueError("job process inventory is inconsistent")
            if ok and count == assigned:
                pids = [int(info.ProcessIdList[i]) for i in range(count)]
                if any(pid <= 0 for pid in pids) or len(set(pids)) != len(pids):
                    raise ValueError("job process inventory contains invalid identities")
                return pids
            capacity = max(capacity * 2, assigned)
        raise ValueError("job process inventory exceeds containment budget")

    @staticmethod
    def _suspend_pid(pid: int, *, job_handle: wintypes.HANDLE) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        PROCESS_SUSPEND_RESUME = 0x0800
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.BOOL)]
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtSuspendProcess.restype = ctypes.c_long
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            return False
        handle = kernel32.OpenProcess(
            PROCESS_SUSPEND_RESUME | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            in_job = wintypes.BOOL()
            if (not kernel32.IsProcessInJob(handle, job_handle, ctypes.byref(in_job))
                    or not in_job.value):
                return False
            status = ntdll.NtSuspendProcess(wintypes.HANDLE(handle))
            return status == 0
        finally:
            kernel32.CloseHandle(handle)

    # -- protocol --------------------------------------------------------
    def terminate_tree(self, identity: dict[str, object]) -> dict[str, object]:
        supervisor = self._supervisor_for(identity)
        if supervisor is None:
            return {"terminated": False, "reason": "no registered custody for this identity"}
        handle = getattr(supervisor, "handle", None)
        if not handle:
            return {"terminated": False, "reason": "custody has no live Job handle"}
        try:
            pids = self._job_process_pids(handle)
            if type(identity.get("pid")) is not int or identity["pid"] not in pids:
                return {"terminated": False, "reason": "requested process is not in the registered Job"}
            supervisor.terminate(137)
            deadline = time.monotonic() + self._termination_wait_seconds
            while True:
                remaining = self._job_process_pids(handle)
                if not remaining or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            return {"terminated": not remaining, "pid": identity["pid"],
                    "expected_pids": pids, "remaining_pids": remaining}
        except (OSError, ValueError) as error:
            return {"terminated": False, "reason": f"Job termination unconfirmed: {error}"}

    def freeze(self, identity: dict[str, object]) -> dict[str, object]:
        supervisor = self._supervisor_for(identity)
        if supervisor is None:
            return {"frozen": False, "reason": "no registered custody for this identity"}
        job_handle = getattr(supervisor, "handle", None)
        if not job_handle:
            return {"frozen": False, "reason": "custody has no live Job handle"}
        try:
            pids = self._job_process_pids(job_handle)
        except (OSError, ValueError) as error:
            return {"frozen": False, "reason": f"Job inventory unconfirmed: {error}"}
        if not pids:
            return {"frozen": False, "reason": "job exposes no member processes"}
        if type(identity.get("pid")) is not int or identity["pid"] not in pids:
            return {"frozen": False, "reason": "requested process is not in the registered Job"}
        suspended = [pid for pid in pids if self._suspend_pid(pid, job_handle=job_handle)]
        failed = [pid for pid in pids if pid not in suspended]
        try:
            remaining = self._job_process_pids(job_handle)
        except (OSError, ValueError) as error:
            return {"frozen": False, "pids": suspended, "expected_pids": pids,
                    "failed_pids": failed, "reason": f"post-suspend inventory unconfirmed: {error}"}
        return {"frozen": not failed and set(remaining) == set(pids),
                "pids": suspended, "expected_pids": pids,
                "failed_pids": failed, "observed_pids": remaining}
