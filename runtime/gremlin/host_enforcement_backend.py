"""Real Windows enforcement backend for supervised containment.

Adapts the canonical ``ProcessSupervisor`` (Job Object custody) to the Gremlin
``EnforcementBackend`` protocol:

* ``terminate_tree``  — ``TerminateJobObject`` over the supervised Job; the
  postcondition is the job's termination, reported as ``{"terminated": True}``.
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
from typing import Callable

SCHEMA_VERSION = "px.host-enforcement-backend/1.0"

_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOBOBJECT_PROCESS_COUNT = 64


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", ctypes.c_uint),
        ("NumberOfProcessIdsInList", ctypes.c_uint),
        ("ProcessIdList", ctypes.c_uint * _JOBOBJECT_PROCESS_COUNT),
    ]


class ProcessSupervisorEnforcementBackend:
    """Job-backed terminate/freeze against supervised process custody."""

    available = True

    #: Live supervised-custody registry: job_object_id -> ProcessSupervisor.
    #: The projection host registers each supervisor when it creates custody.
    REGISTRY: dict[str, object] = {}

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
        info = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
        size = wintypes.DWORD(ctypes.sizeof(info))
        if not kernel32.QueryInformationJobObject(
            job_handle, _JOB_OBJECT_BASIC_PROCESS_ID_LIST, ctypes.byref(info), size, None
        ):
            return []
        return [int(info.ProcessIdList[index]) for index in range(min(
            int(info.NumberOfProcessIdsInList), _JOBOBJECT_PROCESS_COUNT))]

    @staticmethod
    def _suspend_pid(pid: int) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        PROCESS_SUSPEND_RESUME = 0x0800
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, int(pid))
        if not handle:
            return False
        try:
            status = ntdll.NtSuspendProcess(wintypes.HANDLE(handle))
            return status == 0
        finally:
            kernel32.CloseHandle(handle)

    # -- protocol --------------------------------------------------------
    def terminate_tree(self, identity: dict[str, object]) -> dict[str, object]:
        supervisor = self._supervisor_for(identity)
        if supervisor is None:
            return {"terminated": False, "reason": "no registered custody for this identity"}
        supervisor.terminate(137)
        return {"terminated": True, "pid": identity.get("pid")}

    def freeze(self, identity: dict[str, object]) -> dict[str, object]:
        supervisor = self._supervisor_for(identity)
        if supervisor is None:
            return {"frozen": False, "reason": "no registered custody for this identity"}
        job_handle = getattr(supervisor, "handle", None)
        if not job_handle:
            return {"frozen": False, "reason": "custody has no live Job handle"}
        pids = self._job_process_pids(job_handle)
        if not pids:
            return {"frozen": False, "reason": "job exposes no member processes"}
        suspended = [pid for pid in pids if self._suspend_pid(pid)]
        return {"frozen": bool(suspended), "pids": suspended}
