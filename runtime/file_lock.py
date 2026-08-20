"""Cross-platform advisory locks with an auditable process-bound lease."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Mapping


LEASE_SCHEMA_VERSION = "1.0"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0
_SELF_START_NONCE = f"{os.getpid()}:{time.time_ns()}:{time.monotonic_ns()}"


class FileLockTimeout(RuntimeError):
    """Raised after a bounded lock-acquisition deadline expires."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _linux_process_start(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        # The executable name is parenthesized and may contain spaces. Fields
        # after its final ')' begin at proc-stat field 3; starttime is field 22.
        fields = value[value.rfind(")") + 2 :].split()
        return f"linux-proc-start-ticks:{fields[19]}"
    except (IndexError, OSError, UnicodeError):
        return None


def _windows_process_start(pid: int) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return f"windows-filetime:{ticks}"
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _bsd_process_start(pid: int) -> str | None:
    """Read kernel-reported birth time on macOS/BSD without Linux /proc."""
    if sys.platform not in {"darwin", "freebsd", "openbsd", "netbsd"}:
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return f"bsd-ps-lstart:{value}" if value else None


def _windows_process_exists(pid: int) -> bool:
    """Query process state without relying on os.kill(pid, 0) on Windows.

    Python's Windows ``os.kill(..., 0)`` can report success for a PID after the
    process has exited.  That leaves a dead lease looking live forever.  A
    process handle plus its exit code gives the lease authority the required
    live/dead distinction; an access-denied result remains conservatively live.
    """
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return int(exit_code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return True


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Lack of inspection authority proves neither death nor PID reuse.
        return True
    except OSError:
        return False
    return True


def _process_start_fingerprint(pid: int) -> str | None:
    source = (
        _windows_process_start(pid) if os.name == "nt" else _linux_process_start(pid)
    )
    if source is None:
        source = _bsd_process_start(pid)
    if source is None and pid == os.getpid():
        source = f"process-local-start-nonce:{_SELF_START_NONCE}"
    return _sha256_text(source) if source is not None else None


class FileLock:
    """Acquire an exclusive byte lock and maintain its process-bound lease.

    The operating-system byte lock remains authoritative. The JSON lease adds a
    unique token, PID-generation fingerprint, heartbeat, and immutable recovery
    evidence. A free byte lock is not taken over when its retained lease still
    identifies a live process; this conservative check prevents lock theft when
    a filesystem or platform supplies weaker advisory-lock semantics.
    """

    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float = 5.0,
        minimum_sleep_seconds: float = 0.005,
        maximum_sleep_seconds: float = 0.1,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        if (
            timeout_seconds <= 0
            or minimum_sleep_seconds <= 0
            or maximum_sleep_seconds < minimum_sleep_seconds
            or heartbeat_interval_seconds <= 0
        ):
            raise ValueError("file-lock timing values must be positive and ordered")
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.minimum_sleep_seconds = minimum_sleep_seconds
        self.maximum_sleep_seconds = maximum_sleep_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stream = None
        self._token: str | None = None
        self._lease: dict[str, object] | None = None
        self._heartbeat_stop: threading.Event | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_error: OSError | None = None
        self._metadata_guard = threading.Lock()
        self.recovery_receipt_path: Path | None = None
        self.attempts = 0
        self.slept_seconds = 0.0

    @staticmethod
    def _decode_record(raw: bytes) -> dict[str, object] | None:
        payload = raw[1:].strip(b"\x00\r\n ") if raw else b""
        if not payload:
            return None
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return {
                "state": "unparseable",
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
            }
        return dict(value) if isinstance(value, Mapping) else {"state": "unparseable"}

    def _read_record(self) -> dict[str, object] | None:
        try:
            # Byte zero is the advisory lock region. Starting at byte one lets
            # observers inspect lease health even while Windows denies reads of
            # the locked byte itself.
            with self.path.open("rb") as stream:
                stream.seek(1)
                return self._decode_record(b"0" + stream.read())
        except OSError:
            return None

    def _owner_diagnostic(self) -> str:
        record = self._read_record()
        if record is None:
            return "owner unavailable"
        if record.get("state") == "unparseable":
            return f"owner metadata unparseable sha256={record.get('raw_sha256', 'unknown')}"
        return (
            f"owner pid={record.get('pid', 'unknown')} "
            f"token={record.get('token', 'unknown')} "
            f"heartbeat_utc={record.get('heartbeat_utc', 'unknown')}"
        )

    @staticmethod
    def _owner_is_live(record: Mapping[str, object]) -> bool:
        if record.get("state") != "held":
            return False
        try:
            pid = int(record["pid"])
        except (KeyError, TypeError, ValueError):
            # Malformed held metadata is not sufficient evidence of a live owner.
            return False
        if not _process_exists(pid):
            return False
        expected = record.get("process_start_fingerprint")
        actual = _process_start_fingerprint(pid)
        if not isinstance(expected, str) or not expected:
            # A live PID with legacy/incomplete identity is conservatively held.
            return True
        if actual is None:
            # Inspection can be unavailable across users; do not steal in doubt.
            return True
        return secrets.compare_digest(expected, actual)

    def _write_record(self, record: Mapping[str, object]) -> None:
        if self._stream is None:
            raise OSError("cannot write lease metadata without an acquired stream")
        payload = json.dumps(
            dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        with self._metadata_guard:
            self._stream.seek(1)
            self._stream.truncate()
            self._stream.write(payload)
            self._stream.flush()
            os.fsync(self._stream.fileno())

    def _record_recovery(self, previous: Mapping[str, object]) -> Path:
        if self._token is None:
            raise OSError("recovery requires an allocated lease token")
        receipt_dir = self.path.parent / ".lock-recovery-receipts" / self.path.name
        receipt_dir.mkdir(parents=True, exist_ok=True)
        recovered_ns = time.time_ns()
        receipt: dict[str, object] = {
            "schema_version": LEASE_SCHEMA_VERSION,
            "receipt_type": "dead_file_lock_owner_recovery",
            "lock_path": str(self.path.resolve()),
            "recovered_utc": datetime.fromtimestamp(
                recovered_ns / 1_000_000_000, timezone.utc
            ).isoformat(),
            "recovered_unix_ns": recovered_ns,
            "reason": (
                "unparseable_owner_metadata"
                if previous.get("state") == "unparseable"
                else "recorded_owner_not_live"
            ),
            "previous_lease": dict(previous),
            "recovered_by": {
                "token": self._token,
                "pid": os.getpid(),
                "process_start_fingerprint": _process_start_fingerprint(os.getpid()),
            },
        }
        canonical = json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        receipt["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
        target = receipt_dir / f"{recovered_ns}-{self._token}.json"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return target

    def _lock_stream(self) -> None:
        assert self._stream is not None
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_stream(self) -> None:
        if self._stream is None:
            return
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)

    def _abandon_attempt(self) -> None:
        if self._stream is None:
            return
        try:
            self._unlock_stream()
        except OSError:
            pass
        self._stream.close()
        self._stream = None

    def _acquire_once(self) -> None:
        if self._stream is None:
            self._stream = self.path.open("r+b")
        self._lock_stream()
        try:
            previous = self._decode_record(self._stream.read())
            if previous is not None and self._owner_is_live(previous):
                raise BlockingIOError("retained lease identifies a live process owner")
            self._token = secrets.token_hex(16)
            if previous is not None and previous.get("state") != "released":
                self.recovery_receipt_path = self._record_recovery(previous)
            acquired_ns = time.time_ns()
            fingerprint = _process_start_fingerprint(os.getpid())
            if fingerprint is None:
                raise OSError("current process start fingerprint is unavailable")
            self._lease = {
                "schema_version": LEASE_SCHEMA_VERSION,
                "state": "held",
                "token": self._token,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "process_start_fingerprint": fingerprint,
                "acquired_utc": datetime.fromtimestamp(
                    acquired_ns / 1_000_000_000, timezone.utc
                ).isoformat(),
                "acquired_unix_ns": acquired_ns,
                "heartbeat_utc": datetime.fromtimestamp(
                    acquired_ns / 1_000_000_000, timezone.utc
                ).isoformat(),
                "heartbeat_unix_ns": acquired_ns,
            }
            self._write_record(self._lease)
        except BaseException:
            self._abandon_attempt()
            raise

    def _heartbeat_once(self) -> None:
        if self._lease is None or self._stream is None:
            return
        heartbeat_ns = time.time_ns()
        self._lease["heartbeat_utc"] = datetime.fromtimestamp(
            heartbeat_ns / 1_000_000_000, timezone.utc
        ).isoformat()
        self._lease["heartbeat_unix_ns"] = heartbeat_ns
        self._write_record(self._lease)

    def _heartbeat_loop(self) -> None:
        assert self._heartbeat_stop is not None
        while not self._heartbeat_stop.wait(self.heartbeat_interval_seconds):
            try:
                self._heartbeat_once()
            except OSError as error:
                self._heartbeat_error = error
                return

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"file-lock-heartbeat-{self.path.name}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Initialize exactly once. Writing through every contender races with
        # an already-held Windows byte-range lock and can raise PermissionError.
        try:
            with self.path.open("xb") as initializer:
                initializer.write(b"0")
                initializer.flush()
                os.fsync(initializer.fileno())
        except (FileExistsError, PermissionError):
            self._stream = None
        deadline = time.monotonic() + self.timeout_seconds
        delay = self.minimum_sleep_seconds
        while True:
            self.attempts += 1
            try:
                self._acquire_once()
                break
            except OSError as error:
                now = time.monotonic()
                if now >= deadline:
                    owner = self._owner_diagnostic()
                    self._abandon_attempt()
                    raise FileLockTimeout(
                        f"control state is locked by another process: {self.path}; {owner}; attempts={self.attempts}"
                    ) from error
                remaining = deadline - now
                sleep_for = min(remaining, delay * random.uniform(0.8, 1.2))
                time.sleep(sleep_for)
                self.slept_seconds += sleep_for
                delay = min(self.maximum_sleep_seconds, delay * 2)
        self._start_heartbeat()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._stream is None:
            return
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1.0)
        release_error: OSError | None = self._heartbeat_error
        if self._lease is not None:
            released_ns = time.time_ns()
            self._lease["state"] = "released"
            self._lease["released_utc"] = datetime.fromtimestamp(
                released_ns / 1_000_000_000, timezone.utc
            ).isoformat()
            self._lease["released_unix_ns"] = released_ns
            try:
                self._write_record(self._lease)
            except OSError as error:
                release_error = release_error or error
        try:
            self._unlock_stream()
        finally:
            self._stream.close()
            self._stream = None
        if release_error is not None and exc_type is None:
            raise release_error
