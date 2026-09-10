"""Bounded, authority-gated supervision for PACIFY-X-owned process trees.

Commands and environment values never enter the durable receipt.  The caller may
receive bounded decoded output, while the retained record contains counters only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from .assurance_controls import supervise_action
from .file_lock import _process_exists, _process_start_fingerprint
from .resource_lifecycle import ResourceManager, ResourceStatus, RunState


class ProcessAdmissionExpired(TimeoutError):
    """Raised only when this supervisor has not invoked its spawn owner."""


MAX_TIMEOUT_SECONDS = 86_400.0
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
DEFAULT_DISK_CONSUMPTION_LIMIT_BYTES = 8 * 1024 * 1024 * 1024
MAX_DISK_CONSUMPTION_LIMIT_BYTES = 1024 * 1024 * 1024 * 1024
MIN_DISK_ACCOUNTING_INTERVAL_SECONDS = 1.0


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_consumption_bytes(path: Path) -> int:
    """Return bounded-path logical bytes without following directory symlinks."""

    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    pending = [path]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _disk_consumption_bytes(paths: Sequence[Path]) -> int:
    """Measure unique declared paths, dropping descendants of another path."""

    roots: list[Path] = []
    for candidate in sorted(
        {path.resolve(strict=False) for path in paths},
        key=lambda item: (len(item.parts), str(item).casefold()),
    ):
        if not any(_inside(candidate, root) for root in roots):
            roots.append(candidate)
    return sum(_path_consumption_bytes(path) for path in roots)


@dataclass(frozen=True, slots=True)
class ProcessBudgets:
    startup_timeout_seconds: float
    idle_timeout_seconds: float
    total_timeout_seconds: float
    graceful_shutdown_seconds: float
    force_shutdown_seconds: float
    stdout_limit_bytes: int
    stderr_limit_bytes: int
    disk_consumption_limit_bytes: int = DEFAULT_DISK_CONSUMPTION_LIMIT_BYTES
    poll_interval_seconds: float = 0.02

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProcessBudgets":
        from .numeric_inputs import bounded_mapping, bounded_integer, finite_number

        value = bounded_mapping(value, "process budgets", maximum=9)
        required = {
            "startup_timeout_seconds",
            "idle_timeout_seconds",
            "total_timeout_seconds",
            "graceful_shutdown_seconds",
            "force_shutdown_seconds",
            "stdout_limit_bytes",
            "stderr_limit_bytes",
        }
        optional = {"disk_consumption_limit_bytes", "poll_interval_seconds"}
        if required - value.keys() or value.keys() - required - optional:
            raise ValueError("process budget fields do not match the declared contract")
        normalized = {}
        for name in sorted(required | optional):
            if name in {"stdout_limit_bytes", "stderr_limit_bytes"}:
                normalized[name] = bounded_integer(
                    value[name], name, maximum=MAX_CAPTURE_BYTES
                )
            elif name == "disk_consumption_limit_bytes":
                normalized[name] = bounded_integer(
                    value.get(name, DEFAULT_DISK_CONSUMPTION_LIMIT_BYTES),
                    name,
                    maximum=MAX_DISK_CONSUMPTION_LIMIT_BYTES,
                )
            else:
                number = finite_number(
                    value.get(name, 0.02), name, minimum=0, maximum=MAX_TIMEOUT_SECONDS
                )
                if number <= 0:
                    raise ValueError("process time budget must be positive")
                normalized[name] = number
        return cls(**normalized)

    def validate(self) -> None:
        from .numeric_inputs import bounded_integer, finite_number

        for name in (
            "startup_timeout_seconds",
            "idle_timeout_seconds",
            "total_timeout_seconds",
            "graceful_shutdown_seconds",
            "force_shutdown_seconds",
            "poll_interval_seconds",
        ):
            value = finite_number(
                getattr(self, name), name, minimum=0, maximum=MAX_TIMEOUT_SECONDS
            )
            if value <= 0:
                raise ValueError("process time budget must be positive")
        if self.startup_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("startup timeout exceeds total timeout")
        if self.idle_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("idle timeout exceeds total timeout")
        bounded_integer(
            self.stdout_limit_bytes, "stdout byte budget", maximum=MAX_CAPTURE_BYTES
        )
        bounded_integer(
            self.stderr_limit_bytes, "stderr byte budget", maximum=MAX_CAPTURE_BYTES
        )
        bounded_integer(
            self.disk_consumption_limit_bytes,
            "disk-consumption byte budget",
            maximum=MAX_DISK_CONSUMPTION_LIMIT_BYTES,
        )



@dataclass(frozen=True, slots=True)
class CaptureResult:
    text: str
    total_bytes: int
    retained_bytes: int
    dropped_bytes: int
    decode_error_count: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ProcessResult:
    action_id: str
    resource_id: str | None
    status: str
    exit_code: int | None
    started_at: str
    ended_at: str
    duration_seconds: float
    stdout: CaptureResult
    stderr: CaptureResult
    shutdown_mode: str
    tree_closed: bool
    failure_type: str | None
    audit_record_hash: str
    receipt_path: str | None


class _BoundedCapture:
    def __init__(self, limit: int, activity: Callable[[], None]) -> None:
        self.limit = limit
        self.activity = activity
        self.buffer = bytearray()
        self.total = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def feed(self, value: bytes) -> None:
        if not value:
            return
        with self._lock:
            self.total += len(value)
            remaining = max(0, self.limit - len(self.buffer))
            appended = min(len(value), remaining)
            self.buffer.extend(value[:appended])
            self.dropped += len(value) - appended
        self.activity()

    def result(self) -> CaptureResult:
        with self._lock:
            raw = bytes(self.buffer)
            total = self.total
            dropped = self.dropped
        decoded, decode_errors = _decode_utf8_lossy(raw)
        return CaptureResult(
            text=decoded,
            total_bytes=total,
            retained_bytes=len(raw),
            dropped_bytes=dropped,
            decode_error_count=decode_errors,
            truncated=dropped > 0,
        )


def _decode_utf8_lossy(raw: bytes) -> tuple[str, int]:
    """Decode exact replacements without repeated malformed-suffix allocation."""
    try:
        return raw.decode("utf-8", errors="strict"), 0
    except UnicodeDecodeError:
        decoded = raw.decode("utf-8", errors="replace")
        # Valid EF BF BD encodings account for literal replacement characters.
        errors = decoded.count("\ufffd") - raw.count(b"\xef\xbf\xbd")
        return decoded, errors



class _OwnerLivenessHandle:
    """Exact kernel-owned proof that the supervising process remains alive."""

    def __init__(self, kind: str, handle: object, closer: Callable[[], None]) -> None:
        self.kind = kind
        self.handle = handle
        self._closer = closer

    def alive(self) -> bool:
        if self.kind == "windows":
            kernel32, handle = self.handle  # type: ignore[misc]
            # WAIT_TIMEOUT means the process handle is not signalled and the
            # exact process represented by the handle is still running.
            return int(kernel32.WaitForSingleObject(handle, 0)) == 0x00000102
        readable, _, _ = select.select([int(self.handle)], [], [], 0)
        return not readable

    def close(self) -> None:
        if self.handle is not None:
            self._closer()
            self.handle = None


def _open_owner_liveness(pid: int) -> _OwnerLivenessHandle | None:
    """Acquire a non-replayable OS handle for the supervising process."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return None
        def close():
            if not kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        return _OwnerLivenessHandle(
            "windows",
            (kernel32, handle),
            close,
        )
    pidfd_open = getattr(os, "pidfd_open", None)
    if pidfd_open is None:
        return None
    try:
        descriptor = int(pidfd_open(pid, 0))
    except OSError:
        return None
    return _OwnerLivenessHandle(
        "pidfd", descriptor, lambda: os.close(descriptor)
    )


def _drain(stream: object, capture: _BoundedCapture, failures=None) -> None:
    reader = getattr(stream, "read1", None) or getattr(stream, "read")
    try:
        while True:
            chunk = reader(8192)
            if not chunk:
                return
            capture.feed(bytes(chunk))
    except BaseException as error:
        if failures is not None:
            failures.append(error)
        elif not isinstance(error, (OSError, ValueError)):
            raise


class _WindowsJob:
    """Small Job Object wrapper; no-op construction on non-Windows hosts."""

    def __init__(self, process: subprocess.Popen[object] | None = None, *, custody_owner=None) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Objects are unavailable")
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self.handle = None
        self._creation_lock = threading.Lock()
        self._creation_claimed = process is not None
        if custody_owner is not None:
            custody_owner(self)
        handle = kernel32.CreateJobObjectW(None, None)
        self.handle = handle
        if not handle:
            raise OSError("CreateJobObjectW failed")
        try:
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x00002000
            if not kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise OSError("SetInformationJobObject failed")
            if process is not None and not kernel32.AssignProcessToJobObject(handle, int(process._handle)):
                raise OSError("AssignProcessToJobObject failed")
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                try:
                    error.job_creation_owner = self
                except BaseException:
                    pass
            raise

    def claim_creation(self) -> None:
        """One Job owns exactly one creation attempt, including failed attempts."""
        with self._creation_lock:
            if self._creation_claimed or not self.handle or self.active_processes():
                raise ValueError('Windows Job is not available for exclusive creation')
            self._creation_claimed = True

    def terminate(self, exit_code: int = 137) -> None:
        if not self._kernel32.TerminateJobObject(self.handle, exit_code):
            raise OSError("TerminateJobObject failed")

    def active_processes(self) -> int:
        class BASIC_ACCOUNTING(self._ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", self._ctypes.c_longlong),
                ("TotalKernelTime", self._ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", self._ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", self._ctypes.c_longlong),
                ("TotalPageFaultCount", self._ctypes.c_uint32),
                ("TotalProcesses", self._ctypes.c_uint32),
                ("ActiveProcesses", self._ctypes.c_uint32),
                ("TotalTerminatedProcesses", self._ctypes.c_uint32),
            ]

        value = BASIC_ACCOUNTING()
        if not self._kernel32.QueryInformationJobObject(
            self.handle,
            1,
            self._ctypes.byref(value),
            self._ctypes.sizeof(value),
            None,
        ):
            raise OSError("QueryInformationJobObject failed")
        return int(value.ActiveProcesses)

    def wait_closed(self, timeout: float, poll_interval: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active_processes() == 0:
                return True
            time.sleep(min(0.02, poll_interval, max(0.0, deadline - time.monotonic())))
        return self.active_processes() == 0

    def resume_process(self, pid: int) -> None:
        """Resume every initial thread after the suspended root enters the job."""
        from ctypes import wintypes

        class THREADENTRY32(self._ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        invalid_handle = self._ctypes.c_void_p(-1).value
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = self._kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if not snapshot or snapshot == invalid_handle:
            raise OSError("CreateToolhelp32Snapshot failed")
        entry = THREADENTRY32()
        entry.dwSize = self._ctypes.sizeof(entry)
        resumed = 0
        try:
            more = self._kernel32.Thread32First(snapshot, self._ctypes.byref(entry))
            while more:
                if int(entry.th32OwnerProcessID) == pid:
                    thread = self._kernel32.OpenThread(
                        0x0002, False, entry.th32ThreadID
                    )
                    if thread:
                        try:
                            if self._kernel32.ResumeThread(thread) != 0xFFFFFFFF:
                                resumed += 1
                        finally:
                            self._kernel32.CloseHandle(thread)
                more = self._kernel32.Thread32Next(snapshot, self._ctypes.byref(entry))
        finally:
            self._kernel32.CloseHandle(snapshot)
        if resumed < 1:
            raise OSError("suspended process thread could not be resumed")

    def close(self) -> None:
        if self.handle:
            if not self._kernel32.CloseHandle(self.handle):
                raise OSError('CloseHandle failed for Windows Job')
            self.handle = None


_BASE_POPEN = subprocess.Popen


class _WindowsContainedPopen(_BASE_POPEN):
    """Candidate native creation adapter; the supplied Job exists before creation.

    ResourceManager selects this adapter for supervised Windows processes.
    It registers intent before creation and owns the Job until physical closure.
    Durable handoff requires a separate ownership protocol.
    """

    @staticmethod
    def _wrap_created_handle(handle):
        return subprocess.Handle(handle)

    def __init__(self, *args, creation_job, creation_hook=None, custody_owner=None, **kwargs):
        if os.name != 'nt' or not creation_job.handle:
            raise ValueError('creation requires a live Windows Job')
        creation_job.claim_creation()
        self._px_job = creation_job
        self._px_creation_hook = creation_hook
        self._px_created = False
        self._px_initial_thread = None
        self._px_unclosed_process_handle = False
        self._px_tree_closed = False
        try:
            if custody_owner is not None:
                custody_owner(self)
            super().__init__(*args, **kwargs)
        except BaseException as error:
            closed = False
            try:
                creation_job.terminate()
                closed = creation_job.wait_closed(5.0, 0.02)
                if self._px_created:
                    self.wait(timeout=5.0)
                    self._px_unclosed_process_handle = True
                    self._handle.Close()
                    self._px_unclosed_process_handle = False
            except BaseException:
                pass
            try:
                creation_job.close()
            except BaseException:
                pass
            if self._px_initial_thread:
                try:
                    self._close_initial_thread()
                except BaseException:
                    pass
            self._px_tree_closed = closed
            try:
                error.process_creation_outcome = {'created': self._px_created, 'tree_closed': closed}
                if (creation_job.handle or not closed or self._px_initial_thread
                        or self._px_unclosed_process_handle
                        or getattr(self, '_px_unclosed_raw_handle', None)
                        or getattr(self, '_px_unclosed_raw_thread', None)):
                    error.process_creation_owner = self
            except BaseException:
                pass
            raise

    def close_retained_creation_handles(self):
        """Retry each retained native handle independently after direct exit."""
        if self._px_created and not self._px_tree_closed and getattr(self, 'returncode', None) is None:
            raise ValueError('process exit is not established for handle release')
        errors = []
        try:
            self._close_initial_thread()
        except BaseException as error:
            errors.append(error)
        for field in ('_px_unclosed_raw_handle', '_px_unclosed_raw_thread'):
            handle = getattr(self, field, None)
            if handle:
                try:
                    if not self._px_job._kernel32.CloseHandle(handle):
                        raise OSError('retained native handle close failed')
                    setattr(self, field, None)
                except BaseException as error:
                    errors.append(error)
        handle = getattr(self, '_handle', None)
        if handle is not None and not handle.closed:
            try:
                handle.Close()
                self._px_unclosed_process_handle = False
            except BaseException as error:
                errors.append(error)
        if errors:
            raise errors[0]

    def _close_initial_thread(self):
        if self._px_initial_thread:
            if not self._px_job._kernel32.CloseHandle(self._px_initial_thread):
                raise OSError('CloseHandle failed for initial process thread')
            self._px_initial_thread = None

    def resume_owned(self):
        """Resume only the exact initial thread retained at native creation."""
        from ctypes import wintypes
        if not self._px_initial_thread:
            raise ValueError('no owned suspended initial thread')
        resume = self._px_job._kernel32.ResumeThread
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = wintypes.DWORD
        previous = int(resume(self._px_initial_thread))
        if previous != 1:
            raise OSError('initial thread suspension state differs from creation contract')
        self._close_initial_thread()
        return previous

    def _execute_child(self, *args, **kwargs):
        import ctypes
        from ctypes import wintypes
        import inspect
        import sys

        values = inspect.signature(_BASE_POPEN._execute_child).bind(self, *args, **kwargs).arguments
        if (values.get('shell') or values.get('preexec_fn') is not None
                or values.get('pass_fds') or values.get('startupinfo') is not None
                or not values.get('close_fds')):
            raise ValueError('contained adapter requires shell=False, close_fds=True and default startup information')
        argv = values['args']
        if not isinstance(argv, (list, tuple)) or not argv or len(argv) > 4096:
            raise ValueError('contained command must be a bounded argv sequence')
        if any(type(arg) is not str or '\0' in arg or len(arg) > 32766 for arg in argv):
            raise ValueError('invalid contained command argument')
        command_line = subprocess.list2cmdline(argv)
        if len(command_line) >= 32767:
            raise ValueError('Windows command line exceeds its bound')
        executable = values['executable']
        cwd = values['cwd']
        executable = os.fsdecode(executable) if executable is not None else None
        cwd = os.fsdecode(cwd) if cwd is not None else None
        if any(value is not None and ('\0' in value or len(value) >= 32767)
               for value in (executable, cwd)):
            raise ValueError('invalid contained executable or working directory')
        environment = values['env']
        environment_buffer = None
        if environment is not None:
            if not isinstance(environment, Mapping) or len(environment) > 4096:
                raise ValueError('contained environment must be bounded')
            rows = []
            seen = set()
            total = 0
            for key, value in environment.items():
                if (type(key) is not str or type(value) is not str or not key
                        or '\0' in key or '\0' in value or '=' in key[1:]):
                    raise ValueError('invalid contained environment entry')
                normalized = key.upper()
                if normalized in seen:
                    raise ValueError('duplicate Windows environment identity')
                seen.add(normalized)
                total += len(key) + len(value) + 2
                if total > 1024 * 1024:
                    raise ValueError('contained environment exceeds its bound')
                rows.append((key, value))
            rendered = '\0'.join(key + '=' + value for key, value in sorted(rows, key=lambda row: row[0].upper())) + '\0\0'
            environment_buffer = ctypes.create_unicode_buffer(rendered)

        class Startup(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('reserved', wintypes.LPWSTR),
                        ('desktop', wintypes.LPWSTR), ('title', wintypes.LPWSTR),
                        ('x', wintypes.DWORD), ('y', wintypes.DWORD),
                        ('xsize', wintypes.DWORD), ('ysize', wintypes.DWORD),
                        ('xchars', wintypes.DWORD), ('ychars', wintypes.DWORD),
                        ('fill', wintypes.DWORD), ('flags', wintypes.DWORD),
                        ('show', wintypes.WORD), ('reserved_bytes', wintypes.WORD),
                        ('reserved_pointer', ctypes.c_void_p), ('stdin', wintypes.HANDLE),
                        ('stdout', wintypes.HANDLE), ('stderr', wintypes.HANDLE)]

        class ExtendedStartup(ctypes.Structure):
            _fields_ = [('startup', Startup), ('attributes', ctypes.c_void_p)]

        class Information(ctypes.Structure):
            _fields_ = [('process', wintypes.HANDLE), ('thread', wintypes.HANDLE),
                        ('pid', wintypes.DWORD), ('tid', wintypes.DWORD)]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        pointer = ctypes.c_void_p
        kernel.InitializeProcThreadAttributeList.argtypes = [pointer, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
        kernel.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel.UpdateProcThreadAttribute.argtypes = [pointer, wintypes.DWORD, ctypes.c_size_t, pointer, ctypes.c_size_t, pointer, pointer]
        kernel.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel.DeleteProcThreadAttributeList.argtypes = [pointer]
        kernel.DeleteProcThreadAttributeList.restype = None
        kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, pointer, pointer,
                                          wintypes.BOOL, wintypes.DWORD, pointer, wintypes.LPCWSTR,
                                          pointer, ctypes.POINTER(Information)]
        kernel.CreateProcessW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handles = [int(values[name]) for name in ('p2cread', 'c2pwrite', 'errwrite')]
        if -1 in handles:
            raise ValueError('contained adapter requires complete standard handles')
        inherited = self._filter_handle_list(handles)
        if not inherited:
            raise ValueError('contained adapter requires explicit inherited standard handles')
        count = ctypes.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(count))
        if not 0 < count.value <= 65536:
            raise OSError('invalid process attribute allocation size')
        attributes = ctypes.create_string_buffer(count.value)
        if not kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        information = Information()
        try:
            job_list = (wintypes.HANDLE * 1)(self._px_job.handle)
            handle_list = (wintypes.HANDLE * len(inherited))(*inherited)
            for attribute, data in ((0x0002000D, job_list), (0x00020002, handle_list)):
                if not kernel.UpdateProcThreadAttribute(attributes, 0, attribute, data,
                                                        ctypes.sizeof(data), None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            startup = ExtendedStartup()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 0x100 | 0x1
            startup.startup.show = 0
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = ctypes.cast(attributes, pointer)
            mutable_command = ctypes.create_unicode_buffer(command_line)
            sys.audit('subprocess.Popen', executable, command_line, cwd, environment)
            success = kernel.CreateProcessW(executable, mutable_command, None, None, True,
                                            int(values['creationflags']) | 0x00080000 | 0x00000400,
                                            environment_buffer, cwd, ctypes.byref(startup),
                                            ctypes.byref(information))
            if not success:
                raise ctypes.WinError(ctypes.get_last_error())
            self._px_created = True
            owned_handle = self._wrap_created_handle(information.process)
            information.process = None  # ownership transferred to the Handle object
            self._handle = owned_handle
            self._px_unclosed_process_handle = True
            self._child_created = True
            self.pid = int(information.pid)
            if int(values['creationflags']) & 0x00000004:
                self._px_initial_thread = information.thread
                information.thread = None
            if self._px_creation_hook is not None:
                self._px_creation_hook(self)
        finally:
            primary_error = sys.exception()
            cleanup_errors = []
            try:
                if information.process and not kernel.CloseHandle(information.process):
                    self._px_unclosed_raw_handle = information.process
                    raise ctypes.WinError(ctypes.get_last_error())
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                if information.thread:
                    self._px_unclosed_raw_thread = information.thread
                    if not self._px_job._kernel32.CloseHandle(information.thread):
                        raise ctypes.WinError(ctypes.get_last_error())
                    self._px_unclosed_raw_thread = None
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                kernel.DeleteProcThreadAttributeList(attributes)
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                self._close_pipe_fds(*(values[name] for name in (
                    'p2cread', 'p2cwrite', 'c2pread', 'c2pwrite', 'errread', 'errwrite')))
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                if primary_error is None:
                    raise cleanup_errors[0]
                try:
                    primary_error.process_creation_cleanup_errors = tuple(
                        type(error).__name__ for error in cleanup_errors)
                except BaseException:
                    pass


class ProcessSupervisor:
    """Execute one pre-authorized action inside a bounded owned process tree."""

    def __init__(self, manager: ResourceManager) -> None:
        self.manager = manager

    @staticmethod
    def command_plan(
        command: Sequence[str], *, platform: str | None = None
    ) -> dict[str, object]:
        active = platform or ("windows" if os.name == "nt" else "posix")
        if active not in {"windows", "posix"}:
            raise ValueError("unsupported process platform")
        if not command or any(
            not isinstance(item, str) or not item or "\0" in item for item in command
        ):
            raise ValueError("command must be a non-empty argv sequence")
        return {
            "platform": active,
            "argv_count": len(command),
            "shell": False,
            "tree_boundary": "job_object"
            if active == "windows"
            else "new_session_process_group",
        }

    def _authorize(
        self, action: Mapping[str, object], cwd: Path
    ) -> tuple[ProcessBudgets, str, tuple[Path, ...]]:
        if (
            not isinstance(action.get("action_id"), str)
            or not str(action["action_id"]).strip()
        ):
            raise ValueError("typed action_id is required")
        budget = ProcessBudgets.from_mapping(action.get("budget", {}))
        limits = ProcessBudgets.from_mapping(action.get("limits", {}))
        decision = supervise_action(action)
        if decision.decision != "allow":
            raise PermissionError(
                f"contained execution {decision.decision}: {','.join(decision.reasons)}"
            )
        effects = set(map(str, action.get("effects", ())))
        if "process" not in effects:
            raise PermissionError("process effect was not declared")
        if action.get("approval") is not True:
            raise PermissionError("explicit supplied process authority is required")
        owned = tuple(
            Path(str(item)).resolve(strict=True)
            for item in action.get("owned_paths", ())
        )
        resolved_cwd = cwd.resolve(strict=True)
        if not resolved_cwd.is_dir() or not any(
            _inside(resolved_cwd, root) for root in owned
        ):
            raise PermissionError("process cwd is outside supplied owned paths")
        for target in action.get("target_paths", ()):
            resolved_target = Path(str(target)).resolve(strict=False)
            if not any(_inside(resolved_target, root) for root in owned):
                raise PermissionError("process target is outside supplied owned paths")
        raw_disk_paths = action.get("disk_consumption_paths", ())
        if not isinstance(raw_disk_paths, (list, tuple)) or len(raw_disk_paths) > 32:
            raise ValueError("disk-consumption paths must be a bounded sequence")
        disk_paths = tuple(
            Path(str(item)).resolve(strict=False) for item in raw_disk_paths
        )
        if any(not any(_inside(path, root) for root in owned) for path in disk_paths):
            raise PermissionError(
                "disk-consumption accounting path is outside supplied owned paths"
            )
        for field in ProcessBudgets.__dataclass_fields__:
            if getattr(budget, field) > getattr(limits, field):
                raise PermissionError(f"process budget exceeds limit: {field}")
        return budget, str(decision.outputs["audit_record_hash"]), disk_paths

    def _receipt(self, result: ProcessResult) -> str:
        receipt_id = f"process-{uuid4().hex}"
        path = self.manager.receipt_dir / f"{receipt_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "px.process-supervision-receipt/1.0",
            "receipt_id": receipt_id,
            "action_id": result.action_id,
            "resource_id": result.resource_id,
            "status": result.status,
            "exit_code": result.exit_code,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "duration_seconds": result.duration_seconds,
            "stdout": {
                key: value
                for key, value in asdict(result.stdout).items()
                if key != "text"
            },
            "stderr": {
                key: value
                for key, value in asdict(result.stderr).items()
                if key != "text"
            },
            "shutdown_mode": result.shutdown_mode,
            "tree_closed": result.tree_closed,
            "failure_type": result.failure_type,
            "audit_record_hash": result.audit_record_hash,
        }
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # A failed atomic promotion deliberately retains the uniquely named
        # prepared record for normal resource-lifecycle reconciliation.
        os.replace(temporary, path)
        return str(path)

    @staticmethod
    def _discover_posix_descendants(root_pid: int) -> dict[int, str]:
        if os.name == "nt" or not Path("/proc").is_dir():
            return {}
        parents: dict[int, int] = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="ascii")
                close = stat.rfind(")")
                fields = stat[close + 2 :].split()
                parents[int(entry.name)] = int(fields[1])
            except (OSError, UnicodeError, ValueError, IndexError):
                continue
        found: set[int] = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, parent in parents.items():
                if parent in found and pid not in found:
                    found.add(pid)
                    changed = True
        return {
            pid: fingerprint
            for pid in found
            if (fingerprint := _process_start_fingerprint(pid)) is not None
        }

    @staticmethod
    def _signal_proven_posix(tracked: Mapping[int, str], sig: int) -> None:
        for pid, expected in sorted(tracked.items(), reverse=True):
            if _process_start_fingerprint(pid) != expected:
                continue
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    def _shutdown(
        self,
        process: subprocess.Popen[object],
        fingerprint: str,
        tracked: dict[int, str],
        job: _WindowsJob | None,
        budget: ProcessBudgets,
        deadline: float | None = None,
    ) -> tuple[str, bool]:
        def remaining(configured):
            return configured if deadline is None else min(configured, max(0.0, deadline - time.monotonic()))
        if job is not None and not job.handle and getattr(job, '_verified_closed', False):
            return 'already_closed', process.poll() is not None
        if (
            process.poll() is None
            and _process_start_fingerprint(process.pid) == fingerprint
        ):
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                    self._signal_proven_posix(tracked, signal.SIGTERM)
            except OSError:
                pass
        try:
            process.wait(timeout=remaining(budget.graceful_shutdown_seconds))
            mode = "graceful"
        except subprocess.TimeoutExpired:
            mode = "forced"
        if os.name != "nt":
            tracked.update(self._discover_posix_descendants(process.pid))
            survivors = {
                pid: value
                for pid, value in tracked.items()
                if pid != process.pid and _process_start_fingerprint(pid) == value
            }
        else:
            survivors = {}
            if mode != "forced" and job is not None and job.active_processes() > 0:
                job.terminate()
                if not job.wait_closed(
                    remaining(budget.force_shutdown_seconds), budget.poll_interval_seconds
                ):
                    return "forced_failed", False
        if mode == "forced" or survivors:
            mode = "forced"
            try:
                if job is not None:
                    try:
                        job.terminate()
                    except OSError:
                        # TerminateJobObject can be denied by a containing host
                        # policy even though this supervisor still owns the
                        # exact Popen process handle.  Kill that root through
                        # the retained handle; its nested kill-on-close jobs
                        # then close their own descendants.
                        if (
                            process.poll() is None
                            and _process_start_fingerprint(process.pid) == fingerprint
                        ):
                            process.kill()
                        else:
                            raise
                elif (
                    os.name == "nt"
                    and _process_start_fingerprint(process.pid) == fingerprint
                ):
                    if remaining(budget.force_shutdown_seconds) <= 0:
                        return 'forced_failed', False
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=remaining(budget.force_shutdown_seconds),
                        check=False,
                        shell=False,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    self._signal_proven_posix(tracked, signal.SIGKILL)
                process.wait(timeout=remaining(budget.force_shutdown_seconds))
                if job is not None and not job.wait_closed(
                    remaining(budget.force_shutdown_seconds), budget.poll_interval_seconds
                ):
                    return "forced_failed", False
            except (OSError, subprocess.SubprocessError):
                return "forced_failed", False
        if os.name != "nt":
            shutdown_deadline = time.monotonic() + remaining(budget.force_shutdown_seconds)
            while time.monotonic() < shutdown_deadline:
                live = [
                    pid
                    for pid, value in tracked.items()
                    if pid != process.pid and _process_start_fingerprint(pid) == value
                ]
                if not live:
                    break
                time.sleep(min(0.02, budget.poll_interval_seconds, max(0.0, shutdown_deadline - time.monotonic())))
            else:
                return "forced_failed", False
        return mode, process.poll() is not None

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        action: Mapping[str, object],
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        environment: Mapping[str, str] | None = None,
        cancel_event: threading.Event | None = None,
        deadline: float | None = None,
        parent_resource_id: str | None = None,
    ) -> ProcessResult:
        custody = {"id": uuid4().hex, "started": time.monotonic(), "threads": [],
                   "project_id": project_id, "run_id": run_id, "lane_id": lane_id}
        try:
            return self._run_with_custody(
                command, cwd=cwd, action=action, project_id=project_id, run_id=run_id,
                lane_id=lane_id, creator=creator, environment=environment,
                cancel_event=cancel_event, deadline=deadline, parent_resource_id=parent_resource_id, _custody=custody)
        except BaseException as error:
            self._settle_failed_supervision(custody, error)
            raise
        finally:
            liveness = custody.get("liveness")
            if liveness is not None:
                try:
                    liveness.close()
                except BaseException:
                    self.manager._supervision_failures[custody['id']] = custody
                    if sys.exception() is not None:
                        # The caught closer error is current here; distinguish
                        # it from an earlier failure recorded by settlement.
                        if not custody.get('primary_failed'):
                            raise

    def _settle_failed_supervision(self, custody, original, *, deadline=None):
        def remaining(configured):
            return configured if deadline is None else min(configured, max(0.0, deadline - time.monotonic()))
        custody['primary_failed'] = True
        process, record = custody.get("process"), custody.get("record")
        errors = []
        creation = custody.get('creation', {})
        closed = process is None and creation.get('tree_closed', True)
        if process is None and creation.get('custody_retained'):
            errors.extend(creation.get('cleanup_errors', []))
            self.manager._supervision_failures[custody['id']] = custody
            if not errors:
                errors.append('CreationCustodyRetained')
        already_closed = bool(custody.get('physical_completed'))
        if process is not None and not already_closed:
            budget = custody["budget"]
            try:
                job = self.manager._process_jobs.get(record.resource_id)
                if os.name == 'nt' and job is not None:
                    if job.handle:
                        job.terminate()
                        closed = job.wait_closed(remaining(budget.force_shutdown_seconds), budget.poll_interval_seconds)
                        job._verified_closed = closed
                    else:
                        closed = bool(getattr(job, '_verified_closed', False))
                    process.wait(timeout=remaining(budget.force_shutdown_seconds))
                else:
                    fingerprint = _process_start_fingerprint(process.pid)
                    _, closed = self._shutdown(process, fingerprint, {process.pid: fingerprint}, job, budget, deadline=deadline)
            except BaseException as error:
                errors.append(type(error).__name__)
            for thread in custody["threads"]:
                try:
                    if thread.ident is not None:
                        thread.join(timeout=remaining(budget.force_shutdown_seconds))
                    if thread.is_alive():
                        errors.append("OutputDrainStillAlive")
                except BaseException as error:
                    errors.append(type(error).__name__)
            if closed and not errors:
                try:
                    if deadline is None:
                        self.manager.complete_process(record.resource_id)
                    else:
                        self.manager.complete_process(record.resource_id, deadline=deadline)
                    custody['physical_completed'] = True
                    custody['pending_publication'] = dict(active=False, status=ResourceStatus.RECLAIMED.value,
                        run_state=RunState.FAILED.value, cleanup_result='supervision_failed_closed', retained_reason=None)
                except BaseException as error:
                    errors.append(type(error).__name__)
            if not closed or errors:
                self.manager._supervision_failures[record.resource_id] = custody
                try:
                    self.manager.update(record.resource_id, status=ResourceStatus.CLEANUP_FAILED.value,
                                        cleanup_result="supervision_failed_custody_retained")
                except BaseException as error:
                    errors.append(type(error).__name__)
        if custody.get('physical_completed') and custody.get('pending_publication'):
            try:
                self.manager.update(record.resource_id, **custody['pending_publication'])
                custody.pop('pending_publication')
            except BaseException as publication_error:
                errors.append(type(publication_error).__name__)
                self.manager._supervision_failures[record.resource_id] = custody
        try:
            outcome = {"tree_closed": closed or already_closed, "cleanup_errors": errors,
                                            "post_closure_failure": already_closed,
                                            "custody_retained": not (closed or already_closed) or bool(errors)}
            custody['settlement'] = outcome
            original.supervision_outcome = outcome
        except BaseException:
            pass

    def _run_with_custody(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        action: Mapping[str, object],
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        environment: Mapping[str, str] | None = None,
        cancel_event: threading.Event | None = None,
        deadline: float | None = None,
        parent_resource_id: str | None = None,
        _custody: dict,
    ) -> ProcessResult:
        import math
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0):
            raise ValueError("process deadline must be finite and positive")
        def parent_expired():
            return deadline is not None and time.monotonic() >= deadline
        if parent_expired() or cancel_event is not None and cancel_event.is_set():
            raise ProcessAdmissionExpired("process admission expired before authorization")
        self.command_plan(command)
        budget, audit_hash, disk_paths = self._authorize(action, cwd)
        _custody["budget"] = budget
        deadline = min(deadline if deadline is not None else float("inf"),
                       _custody["started"] + budget.total_timeout_seconds)
        # ``run`` executes in the process that owns and supervises the child.
        # Its own PID is the custody identity.  Using getppid() binds the child
        # to the supervisor's launcher, which is intentionally short-lived for
        # durable Studio workers and therefore creates false owner-loss kills.
        if parent_expired() or cancel_event is not None and cancel_event.is_set():
            raise ProcessAdmissionExpired("process admission expired after authorization")
        owner_pid = os.getpid()
        owner_fingerprint = _process_start_fingerprint(owner_pid)
        owner_liveness = _open_owner_liveness(owner_pid)
        _custody["liveness"] = owner_liveness
        if owner_fingerprint is None and owner_liveness is None:
            raise RuntimeError("supervising process identity cannot be proven")
        disk_root = Path(cwd.resolve(strict=True).anchor or cwd.resolve(strict=True))
        initial_disk_free = shutil.disk_usage(disk_root).free
        initial_owned_consumption = (
            _disk_consumption_bytes(disk_paths) if disk_paths else None
        )
        if parent_expired() or cancel_event is not None and cancel_event.is_set():
            raise ProcessAdmissionExpired("process admission expired before spawn")
        action_id = str(action["action_id"])
        started_at = _now()
        started = time.monotonic()
        empty = CaptureResult("", 0, 0, 0, 0, False)
        _custody['creation'] = {}
        try:
            record, process = self.manager.spawn_owned_process(
                command,
                cwd=cwd.resolve(strict=True),
                project_id=project_id,
                run_id=run_id,
                lane_id=lane_id,
                creator=creator,
                environment=environment,
                text=False,
                start_suspended=os.name == "nt",
                ownership="supervised",
                parent_resource_id=parent_resource_id,
                creation_outcome=_custody['creation'],
            )
            _custody.update(record=record, process=process)
        except (OSError, subprocess.SubprocessError) as error:
            creation = _custody['creation']
            if not creation or creation.get('created') or not creation.get('tree_closed') or creation.get('custody_retained'):
                raise
            preliminary = ProcessResult(
                action_id,
                None,
                "spawn_failed",
                None,
                started_at,
                _now(),
                time.monotonic() - started,
                empty,
                empty,
                "not_started",
                True,
                type(error).__name__,
                audit_hash,
                None,
            )
            receipt = self._receipt(preliminary)
            return ProcessResult(
                **{
                    **asdict(preliminary),
                    "stdout": preliminary.stdout,
                    "stderr": preliminary.stderr,
                    "receipt_path": receipt,
                }
            )

        fingerprint = _process_start_fingerprint(process.pid)
        if fingerprint is None:
            # The live Popen handle remains exact in this process. Persist a
            # deliberately non-replayable identity so restart reconciliation
            # retains rather than killing an unproven PID.
            process_identity = f"owned-handle:{uuid4().hex}"
        else:
            process_identity = f"process-start:{fingerprint}"
        self.manager.update(record.resource_id, process_identity=process_identity)
        job = self.manager._process_jobs.get(record.resource_id)
        _custody["job"] = job
        if os.name == "nt" and job is None:
            raise RuntimeError("supervised Windows creation has no owned Job")

        activity_lock = threading.Lock()
        supervision_started = time.monotonic()
        last_activity = [supervision_started]
        observed = [False]

        def activity() -> None:
            with activity_lock:
                observed[0] = True
                last_activity[0] = time.monotonic()

        stdout_capture = _BoundedCapture(budget.stdout_limit_bytes, activity)
        stderr_capture = _BoundedCapture(budget.stderr_limit_bytes, activity)
        drain_failures = []
        threads = [
            threading.Thread(
                target=_drain, args=(process.stdout, stdout_capture, drain_failures), daemon=True
            ),
            threading.Thread(
                target=_drain, args=(process.stderr, stderr_capture, drain_failures), daemon=True
            ),
        ]
        _custody["threads"] = threads
        for thread in threads:
            thread.start()
        setup_status = (
            "cancelled" if cancel_event is not None and cancel_event.is_set()
            else "total_timeout" if parent_expired() else None
        )
        if os.name == "nt" and setup_status is None:
            process.resume_owned()

        status = setup_status or "exited"
        shutdown_mode = "natural"
        tree_closed = True
        tracked = {process.pid: fingerprint}
        next_safety_check = supervision_started
        next_disk_check = supervision_started

        def terminal_safety_status(*, check_disk: bool) -> str | None:
            if owner_liveness is not None:
                owner_alive = owner_liveness.alive()
            elif owner_fingerprint is not None:
                owner_alive = (
                    _process_start_fingerprint(owner_pid) == owner_fingerprint
                )
            else:
                owner_alive = False
            if not owner_alive:
                return "owner_lost"
            if not check_disk:
                return None
            if initial_owned_consumption is not None:
                current_owned_consumption = _disk_consumption_bytes(disk_paths)
                if (
                    current_owned_consumption - initial_owned_consumption
                    > budget.disk_consumption_limit_bytes
                ):
                    return "disk_budget_exceeded"
            else:
                current_disk_free = shutil.disk_usage(disk_root).free
                if (
                    initial_disk_free - current_disk_free
                    > budget.disk_consumption_limit_bytes
                ):
                    return "disk_budget_exceeded"
            return None

        try:
            while status == "exited" and process.poll() is None:
                if drain_failures:
                    raise drain_failures[0]
                now = time.monotonic()
                if os.name != "nt":
                    tracked.update(self._discover_posix_descendants(process.pid))
                with activity_lock:
                    has_activity, last = observed[0], last_activity[0]
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                    break
                if now >= next_safety_check:
                    next_safety_check = now + max(
                        0.25, budget.poll_interval_seconds
                    )
                    check_disk = now >= next_disk_check
                    if check_disk:
                        next_disk_check = now + max(
                            MIN_DISK_ACCOUNTING_INTERVAL_SECONDS,
                            budget.poll_interval_seconds,
                        )
                    safety_status = terminal_safety_status(check_disk=check_disk)
                    if safety_status is not None:
                        status = safety_status
                        break
                if parent_expired() or now - supervision_started >= budget.total_timeout_seconds:
                    status = "total_timeout"
                    break
                if (
                    not has_activity
                    and now - supervision_started >= budget.startup_timeout_seconds
                ):
                    status = "startup_timeout"
                    break
                if has_activity and now - last >= budget.idle_timeout_seconds:
                    status = "idle_timeout"
                    break
                time.sleep(budget.poll_interval_seconds)
            # The child can exit while this supervisor thread is descheduled.
            # Reconcile hard terminal controls after poll() observes that exit;
            # otherwise an over-budget or cancelled process can be published as
            # a successful natural exit under host contention.
            if status == "exited":
                # A final unconditional disk measurement preserves the hard
                # ceiling for fast-exit commands while avoiding a recursive
                # full-tree walk on every 20 ms supervision poll.
                safety_status = terminal_safety_status(check_disk=True)
                if safety_status is not None:
                    status = safety_status
                elif cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                elif (
                    parent_expired() or time.monotonic() - supervision_started
                    >= budget.total_timeout_seconds
                ):
                    status = "total_timeout"
            if status != "exited":
                shutdown_mode, tree_closed = self._shutdown(
                    process, fingerprint, tracked, job, budget
                )
            elif os.name == "nt" and job is not None:
                # Closing a kill-on-close Job ensures descendants cannot outlive a
                # successfully exited root process.
                try:
                    job.terminate()
                    tree_closed = job.wait_closed(
                        budget.force_shutdown_seconds, budget.poll_interval_seconds
                    )
                except OSError:
                    tree_closed = False
            elif os.name != "nt":
                tracked.update(self._discover_posix_descendants(process.pid))
                survivors = {
                    pid: value for pid, value in tracked.items() if pid != process.pid
                }
                if survivors:
                    shutdown_mode, tree_closed = self._shutdown(
                        process, fingerprint, tracked, job, budget
                    )
        finally:
            if sys.exception() is None:
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(timeout=budget.force_shutdown_seconds)
                if any(thread.is_alive() for thread in threads):
                    raise RuntimeError("owned output drain has not closed")
                if drain_failures:
                    raise drain_failures[0]

        failure_type = None if tree_closed else "ProcessTreeClosureError"
        if not tree_closed:
            status = "shutdown_failed"
            self.manager.update(
                record.resource_id,
                active=True,
                status=ResourceStatus.CLEANUP_FAILED.value,
                cleanup_result="process_tree_not_verified",
                retained_reason="process tree closure could not be proven",
            )
        else:
            self.manager.complete_process(record.resource_id)
            _custody['physical_completed'] = True
            if status == "exited" and process.returncode not in {0, None}:
                _custody['pending_publication'] = dict(
                    run_state=RunState.FAILED.value,
                    cleanup_result=f"exit_{process.returncode}",
                )
            elif status != "exited":
                _custody['pending_publication'] = dict(
                    run_state=RunState.CANCELLED.value,
                    cleanup_result=f"{status}_{shutdown_mode}",
                )
            if _custody.get('pending_publication'):
                self.manager.update(record.resource_id, **_custody['pending_publication'])
                _custody.pop('pending_publication')
        if owner_liveness is not None:
            owner_liveness.close()
        preliminary = ProcessResult(
            action_id=action_id,
            resource_id=record.resource_id,
            status=status,
            exit_code=process.returncode,
            started_at=started_at,
            ended_at=_now(),
            duration_seconds=time.monotonic() - started,
            stdout=stdout_capture.result(),
            stderr=stderr_capture.result(),
            shutdown_mode=shutdown_mode,
            tree_closed=tree_closed,
            failure_type=failure_type,
            audit_record_hash=audit_hash,
            receipt_path=None,
        )
        receipt = self._receipt(preliminary)
        return ProcessResult(
            **{
                **asdict(preliminary),
                "stdout": preliminary.stdout,
                "stderr": preliminary.stderr,
                "receipt_path": receipt,
            }
        )


    def reconcile_persisted(
        self,
        resource_id: str,
        *,
        supplied_authority: bool,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        """Reap only a persisted PID whose start identity is still provable."""
        if supplied_authority is not True:
            raise PermissionError(
                "explicit supplied reconciliation authority is required"
            )
        record = self.manager.ledger.get(resource_id)
        if record.resource_type != "process" or not record.pid or not record.active:
            raise ValueError("resource is not an active persisted process")
        prefix = "process-start:"
        if not record.process_identity or not record.process_identity.startswith(
            prefix
        ):
            return {
                "status": "retained_unproven",
                "resource_id": resource_id,
                "tree_closed": False,
            }
        expected = record.process_identity[len(prefix) :]
        if not _process_exists(record.pid):
            self.manager.update(
                resource_id,
                active=False,
                run_state=RunState.ABANDONED.value,
                status=ResourceStatus.RECLAIMED.value,
                cleanup_result="persisted_process_already_absent",
            )
            return {
                "status": "already_absent",
                "resource_id": resource_id,
                "tree_closed": True,
            }
        if _process_start_fingerprint(record.pid) != expected:
            return {
                "status": "retained_unproven",
                "resource_id": resource_id,
                "tree_closed": False,
            }
        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["taskkill", "/PID", str(record.pid), "/T", "/F"],
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                    shell=False,
                )
                if completed.returncode not in {0, 128}:
                    diagnostic = (completed.stderr or completed.stdout).strip()
                    raise OSError(
                        f"taskkill exit {completed.returncode}: {diagnostic[:160]}"
                    )
            else:
                if os.getpgid(record.pid) != record.pid:
                    return {
                        "status": "retained_unproven",
                        "resource_id": resource_id,
                        "tree_closed": False,
                    }
                os.killpg(record.pid, signal.SIGKILL)
            deadline = time.monotonic() + timeout_seconds
            while _process_exists(record.pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            if _process_exists(record.pid):
                raise OSError("verified process identity remains active")
        except (OSError, subprocess.SubprocessError) as error:
            self.manager.update(
                resource_id,
                status=ResourceStatus.CLEANUP_FAILED.value,
                retained_reason=f"reconciliation failed ({type(error).__name__})",
            )
            return {
                "status": "reconcile_failed",
                "resource_id": resource_id,
                "tree_closed": False,
                "failure_type": type(error).__name__,
                "failure_detail": str(error)[:256],
            }
        self.manager.update(
            resource_id,
            active=False,
            run_state=RunState.ABANDONED.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result="persisted_verified_process_tree_terminated",
        )
        return {"status": "reaped", "resource_id": resource_id, "tree_closed": True}
