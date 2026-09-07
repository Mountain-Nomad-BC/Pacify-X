"""Fail-closed native input server for one PACIFY-X-owned disposable VS Code host."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import time
from ctypes import Structure, Union, WINFUNCTYPE, WinDLL, byref, c_int, c_long, c_ulong, c_ushort, c_void_p, c_wchar, get_last_error, sizeof, wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

SCHEMA_REQUEST = "px.owned-native-input-request/1.0"
SCHEMA_RESULT = "px.owned-native-input-result/1.0"
REQUEST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,40}$", re.IGNORECASE)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone missing")
    return parsed.astimezone(timezone.utc)


def is_owned_process(pid: int, root_pid: int, parents: Mapping[int, int]) -> bool:
    current, seen = pid, set()
    for _ in range(128):
        if current == root_pid:
            return True
        if current <= 0 or current in seen:
            return False
        seen.add(current)
        current = int(parents.get(current, 0))
    return False


def select_owned_window(windows: list[tuple[int, int, bool, bool]], root_pid: int, parents: Mapping[int, int]) -> tuple[int, int] | None:
    owned = [(hwnd, pid, visible) for hwnd, pid, visible, enabled in windows
             if hwnd > 0 and pid > 0 and is_owned_process(pid, root_pid, parents)]
    # EnumWindows returns top-level windows in top-to-bottom Z order.  Every
    # retained candidate is already process-tree-bound to the one disposable
    # VS Code host. Prefer its topmost visible window. The isolated Electron
    # host is launched hidden, however, so a hidden owned top-level window is a
    # valid recovery target: activate() restores it with ShowWindow and the
    # caller re-verifies the foreground PID before sending input. Enabled state
    # cannot define ownership because a native modal disables its owner.
    candidate = next(((hwnd, pid) for hwnd, pid, visible in owned if visible), None)
    return candidate or ((owned[0][0], owned[0][1]) if owned else None)


def activation_thread_ids(current_thread: int, foreground_thread: int, target_thread: int) -> tuple[int, ...]:
    result: list[int] = []
    for thread_id in (foreground_thread, target_thread):
        if thread_id > 0 and thread_id != current_thread and thread_id not in result:
            result.append(thread_id)
    return tuple(result)


def resolve_owned_foreground(native: object, root_pid: int, timeout_seconds: float = 0.75) -> tuple[int, int, bool]:
    parents = native.parents()
    hwnd, pid = native.foreground()
    if is_owned_process(pid, root_pid, parents):
        return hwnd, pid, False
    windows = native.windows()
    candidate = select_owned_window(windows, root_pid, parents)
    if candidate is None:
        owned_processes = sum(1 for process_pid in parents if is_owned_process(process_pid, root_pid, parents))
        raise PermissionError(f"foreground outside owned tree;no owned window:root={root_pid}:foreground={pid}:owned_processes={owned_processes}:windows={len(windows)}")
    if not native.activate(candidate[0]):
        raise PermissionError("owned VS Code window activation was refused")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        hwnd, pid = native.foreground()
        if is_owned_process(pid, root_pid, native.parents()):
            return hwnd, pid, True
        time.sleep(0.025)
    raise PermissionError("owned VS Code window did not become foreground")


def validate_request(request: object, config: Mapping[str, object], last_sequence: int, now: datetime | None = None) -> dict[str, object]:
    if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_REQUEST:
        raise ValueError("request schema invalid")
    if not hmac.compare_digest(str(request.get("secret", "")), str(config.get("secret", ""))):
        raise ValueError("request authentication failed")
    sequence = request.get("sequence")
    if not isinstance(sequence, int) or sequence <= last_sequence:
        raise ValueError("request sequence stale")
    if request.get("vscode_pid") != config.get("vscode_pid"):
        raise ValueError("request VS Code identity mismatch")
    if not REQUEST_ID.fullmatch(str(request.get("request_id", ""))):
        raise ValueError("request id invalid")
    action, key = request.get("action"), request.get("key")
    if (action, key) not in {("cancel", "escape"), ("approve", "enter"), ("approve", "tab-enter"), ("approve", "tab-tab-enter")}:
        raise ValueError("request action invalid")
    correlation = request.get("correlation")
    if not isinstance(correlation, dict) or not str(correlation.get("request_type", "")) or not str(correlation.get("action_label", "")):
        raise ValueError("request correlation missing")
    issued, expires = _utc(str(request.get("issued_utc", ""))), _utc(str(request.get("expires_utc", "")))
    current = now or datetime.now(timezone.utc)
    if expires <= issued or (expires - issued).total_seconds() > 10 or current < issued or current > expires:
        raise ValueError("request time boundary invalid")
    return request


class _KEYBDINPUT(Structure):
    _fields_ = [("wVk", c_ushort), ("wScan", c_ushort), ("dwFlags", c_ulong), ("time", c_ulong), ("dwExtraInfo", c_void_p)]


class _MOUSEINPUT(Structure):
    _fields_ = [("dx", c_long), ("dy", c_long), ("mouseData", c_ulong), ("dwFlags", c_ulong),
                ("time", c_ulong), ("dwExtraInfo", c_void_p)]


class _HARDWAREINPUT(Structure):
    _fields_ = [("uMsg", c_ulong), ("wParamL", c_ushort), ("wParamH", c_ushort)]


class _INPUTUNION(Union):
    # INPUT is sized by its largest Win32 union member. Omitting MOUSEINPUT
    # produces a 32-byte structure on Win64 and makes SendInput reject cbSize.
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", c_ulong), ("u", _INPUTUNION)]


class _PROCESSENTRY32W(Structure):
    _fields_ = [("dwSize", c_ulong), ("cntUsage", c_ulong), ("th32ProcessID", c_ulong), ("th32DefaultHeapID", c_void_p),
                ("th32ModuleID", c_ulong), ("cntThreads", c_ulong), ("th32ParentProcessID", c_ulong), ("pcPriClassBase", c_long),
                ("dwFlags", c_ulong), ("szExeFile", c_wchar * 260)]


class WindowsInput:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows native input is unavailable")
        self.user32 = WinDLL("user32", use_last_error=True)
        self.kernel32 = WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, c_void_p]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._enum_windows_proc = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self._enum_windows_proc, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self.user32.BringWindowToTop.restype = wintypes.BOOL
        self.user32.SetActiveWindow.argtypes = [wintypes.HWND]
        self.user32.SetActiveWindow.restype = wintypes.HWND
        self.user32.SetFocus.argtypes = [wintypes.HWND]
        self.user32.SetFocus.restype = wintypes.HWND
        self.user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        self.user32.AttachThreadInput.restype = wintypes.BOOL
        self.user32.SendInput.argtypes = [wintypes.UINT, c_void_p, c_int]
        self.user32.SendInput.restype = wintypes.UINT
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, c_void_p]
        self.kernel32.Process32NextW.argtypes = [wintypes.HANDLE, c_void_p]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, c_void_p, c_void_p, c_void_p, c_void_p]
        self.kernel32.GetProcessTimes.restype = wintypes.BOOL
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def foreground(self) -> tuple[int, int]:
        # ctypes represents a null HWND as None.  A transient lack of a
        # foreground window is normal while VS Code opens or closes a native
        # modal; normalize it so the caller can recover an owned window.
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        if not hwnd:
            return 0, 0
        pid = c_ulong(0)
        if not self.user32.GetWindowThreadProcessId(c_void_p(hwnd), byref(pid)):
            raise OSError("foreground window unavailable")
        return hwnd, int(pid.value)

    def windows(self) -> list[tuple[int, int, bool, bool]]:
        result: list[tuple[int, int, bool, bool]] = []

        @self._enum_windows_proc
        def visit(hwnd: int, _parameter: int) -> bool:
            pid = c_ulong(0)
            if self.user32.GetWindowThreadProcessId(hwnd, byref(pid)):
                result.append((int(hwnd), int(pid.value), bool(self.user32.IsWindowVisible(hwnd)), bool(self.user32.IsWindowEnabled(hwnd))))
            return True

        if not self.user32.EnumWindows(visit, 0):
            raise OSError("top-level window enumeration unavailable")
        return result

    def activate(self, hwnd: int) -> bool:
        foreground = self.user32.GetForegroundWindow()
        foreground_thread = self.user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        target_thread = self.user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = self.kernel32.GetCurrentThreadId()
        attached: list[int] = []
        try:
            for thread_id in activation_thread_ids(current_thread, foreground_thread, target_thread):
                if not self.user32.AttachThreadInput(current_thread, thread_id, True):
                    return False
                attached.append(thread_id)
            self.user32.ShowWindow(hwnd, 9)
            self.user32.BringWindowToTop(hwnd)
            self.user32.SetActiveWindow(hwnd)
            self.user32.SetFocus(hwnd)
            return bool(self.user32.SetForegroundWindow(hwnd))
        finally:
            for thread_id in reversed(attached):
                self.user32.AttachThreadInput(current_thread, thread_id, False)

    def parents(self) -> dict[int, int]:
        snapshot = self.kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot in (0, -1, c_void_p(-1).value):
            raise OSError("process snapshot unavailable")
        result: dict[int, int] = {}
        entry = _PROCESSENTRY32W(); entry.dwSize = sizeof(entry)
        try:
            ok = self.kernel32.Process32FirstW(snapshot, byref(entry))
            while ok:
                result[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = self.kernel32.Process32NextW(snapshot, byref(entry))
        finally:
            self.kernel32.CloseHandle(snapshot)
        return result

    def process_identity(self, pid: int) -> tuple[int, int]:
        handle = self.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError("owned VS Code process unavailable")
        creation, exit_time, kernel, user = (wintypes.FILETIME() for _ in range(4))
        try:
            if not self.kernel32.GetProcessTimes(handle, byref(creation), byref(exit_time), byref(kernel), byref(user)):
                raise OSError("owned VS Code identity unavailable")
            return int(creation.dwHighDateTime), int(creation.dwLowDateTime)
        finally:
            self.kernel32.CloseHandle(handle)

    def send(self, key: str) -> int:
        keys = (0x09, 0x09, 0x0D) if key == "tab-tab-enter" else (0x09, 0x0D) if key == "tab-enter" else ({"escape": 0x1B, "enter": 0x0D}[key],)
        inputs = (_INPUT * (len(keys) * 2))()
        for index, vk in enumerate(keys):
            inputs[index * 2].type = inputs[index * 2 + 1].type = 1
            inputs[index * 2].ki = _KEYBDINPUT(vk, 0, 0, 0, None)
            inputs[index * 2 + 1].ki = _KEYBDINPUT(vk, 0, 0x0002, 0, None)
        expected = len(inputs)
        sent = int(self.user32.SendInput(expected, inputs, sizeof(_INPUT)))
        if sent != expected:
            error = get_last_error()
            raise OSError(error, f"SendInput incomplete:{sent}/{expected}")
        return sent


def _atomic_json(target: Path, payload: Mapping[str, object]) -> None:
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, separators=(",", ":")); stream.write("\n")
    os.replace(temporary, target)


def serve(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root_input = Path(str(config["root"]))
    if root_input.is_symlink():
        raise PermissionError("native input configuration boundary invalid")
    root = root_input.resolve(strict=True)
    if config_path.resolve().parent != root:
        raise PermissionError("native input configuration boundary invalid")
    requests, results = root / "requests", root / "results"
    if any(not item.is_dir() or item.is_symlink() for item in (requests, results)):
        raise PermissionError("native input directory boundary invalid")
    native = WindowsInput()
    root_identity = native.process_identity(int(config["vscode_pid"]))
    _atomic_json(root / "ready.json", {"schema_version": "px.owned-native-input-ready/1.0", "pid": os.getpid(), "vscode_pid": config["vscode_pid"]})
    last_sequence = 0
    while not (root / "stop.json").exists():
        for request_path in sorted(requests.glob("*.json"), key=lambda item: item.name):
            result_path = results / request_path.name
            if result_path.exists():
                continue
            request_id, sequence = "", -1
            try:
                raw = json.loads(request_path.read_text(encoding="utf-8"))
                request_id, sequence = str(raw.get("request_id", "")), int(raw.get("sequence", -1))
                request = validate_request(raw, config, last_sequence)
                if native.process_identity(int(config["vscode_pid"])) != root_identity:
                    raise PermissionError("owned VS Code process identity changed")
                hwnd, foreground_pid, focus_recovered = resolve_owned_foreground(native, int(config["vscode_pid"]))
                sent = native.send(str(request["key"])); last_sequence = sequence
                result = {"schema_version": SCHEMA_RESULT, "request_id": request_id, "sequence": sequence, "status": "sent",
                          "foreground_pid": foreground_pid, "foreground_hwnd": str(hwnd), "owned_process": True, "input_count": sent,
                          "focus_recovered": focus_recovered,
                          "observed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            except Exception as error:
                result = {"schema_version": SCHEMA_RESULT, "request_id": request_id, "sequence": sequence, "status": "refused",
                          "reason": f"{type(error).__name__}:{error}"[:240], "observed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            _atomic_json(result_path, result)
        time.sleep(0.025)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", type=Path, required=True)
    parser.add_argument("--px-owned-token", required=True)
    args = parser.parse_args()
    config = json.loads(args.serve.read_text(encoding="utf-8"))
    if not hmac.compare_digest(str(config.get("ownership_token", "")), args.px_owned_token):
        raise PermissionError("owned process token mismatch")
    return serve(args.serve)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        sys.stderr.write(f"{type(error).__name__}:{error}\n")
        raise SystemExit(1)
