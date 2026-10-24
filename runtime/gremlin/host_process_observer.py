"""Real host process-tree observation for supervised children (Windows).

The canonical projection host spawns its reconciliation workers as direct
children. This observer reports the *actual* live child-process tree of the
host process through the Win32 Toolhelp32 snapshot API — a real observation,
not a stub. Every snapshot row carries the pid, parent pid and image name, so
containment can join it against enrolled process identities (pid +
process-start identity).

On non-Windows hosts this module raises at import: the host must supply its own
platform-true observer rather than silently claiming coverage.
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
    finally:
        kernel32.CloseHandle(handle)
    return rows


def observe_host_children(*, host_pid: int | None = None) -> tuple[dict[str, object], ...]:
    """Return the live direct children of ``host_pid`` (default: this process)."""
    parent = int(host_pid if host_pid is not None else os.getpid())
    rows = tuple(
        row for row in _snapshot_rows() if int(row["parent_pid"]) == parent
    )
    return rows


def make_process_tree_poller(*, host_pid: int | None = None):
    """The ObserverSet poll callable: real child-process snapshots."""
    def poll() -> tuple[object, ...]:
        return observe_host_children(host_pid=host_pid)
    return poll
