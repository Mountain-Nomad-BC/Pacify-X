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
import signal
import subprocess
import threading
import time
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from .assurance_controls import supervise_action
from .file_lock import _process_exists, _process_start_fingerprint
from .resource_lifecycle import ResourceManager, ResourceStatus, RunState


MAX_TIMEOUT_SECONDS = 86_400.0
MAX_CAPTURE_BYTES = 64 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class ProcessBudgets:
    startup_timeout_seconds: float
    idle_timeout_seconds: float
    total_timeout_seconds: float
    graceful_shutdown_seconds: float
    force_shutdown_seconds: float
    stdout_limit_bytes: int
    stderr_limit_bytes: int
    poll_interval_seconds: float = 0.02

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProcessBudgets":
        expected = {
            "startup_timeout_seconds",
            "idle_timeout_seconds",
            "total_timeout_seconds",
            "graceful_shutdown_seconds",
            "force_shutdown_seconds",
            "stdout_limit_bytes",
            "stderr_limit_bytes",
        }
        missing = expected - set(value)
        if missing:
            raise ValueError(f"process budget is missing fields: {sorted(missing)}")
        budget = cls(
            startup_timeout_seconds=float(value["startup_timeout_seconds"]),
            idle_timeout_seconds=float(value["idle_timeout_seconds"]),
            total_timeout_seconds=float(value["total_timeout_seconds"]),
            graceful_shutdown_seconds=float(value["graceful_shutdown_seconds"]),
            force_shutdown_seconds=float(value["force_shutdown_seconds"]),
            stdout_limit_bytes=int(value["stdout_limit_bytes"]),
            stderr_limit_bytes=int(value["stderr_limit_bytes"]),
            poll_interval_seconds=float(value.get("poll_interval_seconds", 0.02)),
        )
        budget.validate()
        return budget

    def validate(self) -> None:
        timeouts = (
            self.startup_timeout_seconds,
            self.idle_timeout_seconds,
            self.total_timeout_seconds,
            self.graceful_shutdown_seconds,
            self.force_shutdown_seconds,
            self.poll_interval_seconds,
        )
        if any(value <= 0 or value > MAX_TIMEOUT_SECONDS for value in timeouts):
            raise ValueError("process timeout budget is outside hard bounds")
        if self.startup_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("startup timeout exceeds total timeout")
        if self.idle_timeout_seconds > self.total_timeout_seconds:
            raise ValueError("idle timeout exceeds total timeout")
        if not 1 <= self.stdout_limit_bytes <= MAX_CAPTURE_BYTES:
            raise ValueError("stdout byte budget is outside hard bounds")
        if not 1 <= self.stderr_limit_bytes <= MAX_CAPTURE_BYTES:
            raise ValueError("stderr byte budget is outside hard bounds")


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
    """Decode with replacement while distinguishing invalid bytes from valid U+FFFD."""
    parts: list[str] = []
    remaining = raw
    errors = 0
    while remaining:
        try:
            parts.append(remaining.decode("utf-8", errors="strict"))
            break
        except UnicodeDecodeError as error:
            parts.append(remaining[: error.start].decode("utf-8", errors="strict"))
            parts.append("\ufffd")
            errors += 1
            remaining = remaining[error.end :]
    return "".join(parts), errors


def _drain(stream: object, capture: _BoundedCapture) -> None:
    reader = getattr(stream, "read1", None) or getattr(stream, "read")
    try:
        while True:
            chunk = reader(8192)
            if not chunk:
                return
            capture.feed(bytes(chunk))
    except (OSError, ValueError):
        return


class _WindowsJob:
    """Small Job Object wrapper; no-op construction on non-Windows hosts."""

    def __init__(self, process: subprocess.Popen[object]) -> None:
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
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError("CreateJobObjectW failed")
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            kernel32.CloseHandle(handle)
            raise OSError("SetInformationJobObject failed")
        if not kernel32.AssignProcessToJobObject(handle, int(process._handle)):  # type: ignore[attr-defined]
            kernel32.CloseHandle(handle)
            raise OSError("AssignProcessToJobObject failed")
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self.handle = handle

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
            time.sleep(min(0.02, poll_interval))
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
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


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
    ) -> tuple[ProcessBudgets, str]:
        if (
            not isinstance(action.get("action_id"), str)
            or not str(action["action_id"]).strip()
        ):
            raise ValueError("typed action_id is required")
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
        budget = ProcessBudgets.from_mapping(dict(action.get("budget", {})))
        limits = ProcessBudgets.from_mapping(dict(action.get("limits", {})))
        for field in ProcessBudgets.__dataclass_fields__:
            if getattr(budget, field) > getattr(limits, field):
                raise PermissionError(f"process budget exceeds limit: {field}")
        return budget, str(decision.outputs["audit_record_hash"])

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
    ) -> tuple[str, bool]:
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
            process.wait(timeout=budget.graceful_shutdown_seconds)
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
                    budget.force_shutdown_seconds, budget.poll_interval_seconds
                ):
                    return "forced_failed", False
        if mode == "forced" or survivors:
            mode = "forced"
            try:
                if job is not None:
                    job.terminate()
                elif (
                    os.name == "nt"
                    and _process_start_fingerprint(process.pid) == fingerprint
                ):
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=budget.force_shutdown_seconds,
                        check=False,
                        shell=False,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    self._signal_proven_posix(tracked, signal.SIGKILL)
                process.wait(timeout=budget.force_shutdown_seconds)
            except (OSError, subprocess.SubprocessError):
                return "forced_failed", False
        if os.name != "nt":
            deadline = time.monotonic() + budget.force_shutdown_seconds
            while time.monotonic() < deadline:
                live = [
                    pid
                    for pid, value in tracked.items()
                    if pid != process.pid and _process_start_fingerprint(pid) == value
                ]
                if not live:
                    break
                time.sleep(min(0.02, budget.poll_interval_seconds))
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
    ) -> ProcessResult:
        self.command_plan(command)
        budget, audit_hash = self._authorize(action, cwd)
        action_id = str(action["action_id"])
        started_at = _now()
        started = time.monotonic()
        empty = CaptureResult("", 0, 0, 0, 0, False)
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
            )
        except (OSError, subprocess.SubprocessError) as error:
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
        job: _WindowsJob | None = None
        try:
            if os.name == "nt":
                job = _WindowsJob(process)
                job.resume_process(process.pid)
        except OSError as error:
            if job is not None:
                try:
                    job.terminate()
                finally:
                    job.close()
            else:
                self.manager.terminate_owned_process(record.resource_id)
            raise RuntimeError(
                f"process containment setup failed ({type(error).__name__})"
            ) from None

        activity_lock = threading.Lock()
        supervision_started = started
        last_activity = [supervision_started]
        observed = [False]

        def activity() -> None:
            with activity_lock:
                observed[0] = True
                last_activity[0] = time.monotonic()

        stdout_capture = _BoundedCapture(budget.stdout_limit_bytes, activity)
        stderr_capture = _BoundedCapture(budget.stderr_limit_bytes, activity)
        threads = [
            threading.Thread(
                target=_drain, args=(process.stdout, stdout_capture), daemon=True
            ),
            threading.Thread(
                target=_drain, args=(process.stderr, stderr_capture), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()

        status = "exited"
        shutdown_mode = "natural"
        tree_closed = True
        tracked = {process.pid: fingerprint}
        try:
            while process.poll() is None:
                now = time.monotonic()
                if os.name != "nt":
                    tracked.update(self._discover_posix_descendants(process.pid))
                with activity_lock:
                    has_activity, last = observed[0], last_activity[0]
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                    break
                if now - supervision_started >= budget.total_timeout_seconds:
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
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                elif (
                    time.monotonic() - supervision_started
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
            if job is not None:
                job.close()
            for thread in threads:
                thread.join(timeout=budget.force_shutdown_seconds)

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
            if status == "exited" and process.returncode not in {0, None}:
                self.manager.update(
                    record.resource_id,
                    run_state=RunState.FAILED.value,
                    cleanup_result=f"exit_{process.returncode}",
                )
            elif status != "exited":
                self.manager.update(
                    record.resource_id,
                    run_state=RunState.CANCELLED.value,
                    cleanup_result=f"{status}_{shutdown_mode}",
                )
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
