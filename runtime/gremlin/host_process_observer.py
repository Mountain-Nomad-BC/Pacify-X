"""Real host process-tree observation for supervised children (Windows).

The canonical projection host spawns its reconciliation workers as supervised
children. This observer reports the observed descendant process tree of the
host process through the Win32 Toolhelp32 snapshot API — a real observation,
not a stub. Every snapshot row carries the pid, parent pid and image name, so
containment can join it against enrolled process identities (pid +
process-start identity).

On non-Windows hosts snapshot acquisition is unavailable: the host must supply
its own platform-true observer rather than silently claiming coverage. A PID
snapshot is observation only, not a process-start identity or authority grant.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

SCHEMA_VERSION = "px.host-process-tree-observation/1.0"

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _snapshot_rows() -> list[dict[str, object]]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel32, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        function.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError("process snapshot is unavailable")
    rows: list[dict[str, object]] = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows.append({
                "pid": int(entry.th32ProcessID),
                "parent_pid": int(entry.th32ParentProcessID),
                "image": str(entry.szExeFile),
            })
            ok = kernel32.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
    return rows


def observe_host_children(*, host_pid: int | None = None) -> tuple[dict[str, object], ...]:
    """Return all observed descendants of ``host_pid``, excluding unrelated trees."""
    parent = int(host_pid if host_pid is not None else os.getpid())
    children: dict[int, list[dict[str, object]]] = {}
    for row in _snapshot_rows():
        children.setdefault(int(row["parent_pid"]), []).append(row)
    seen = {parent}
    pending = [parent]
    descendants = []
    while pending:
        current = pending.pop()
        for row in children.get(current, ()):
            pid = int(row["pid"])
            if pid not in seen:
                seen.add(pid)
                descendants.append(row)
                pending.append(pid)
    return tuple(descendants)


def make_process_tree_poller(*, host_pid: int | None = None):
    """The ObserverSet poll callable: real child-process snapshots."""
    def poll() -> tuple[object, ...]:
        return observe_host_children(host_pid=host_pid)
    return poll
