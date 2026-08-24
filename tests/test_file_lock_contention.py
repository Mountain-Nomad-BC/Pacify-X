from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

from runtime.file_lock import (
    FileLock,
    FileLockTimeout,
    _process_exists,
    _process_start_fingerprint,
    _bsd_process_start,
)


def _hold_lock(path: str, ready, release) -> None:
    with FileLock(Path(path), timeout_seconds=2):
        ready.set()
        release.wait(15)


def test_file_lock_exponential_backoff() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        sleeps: list[float] = []
        clock = [0.0]

        def sleep(value: float) -> None:
            sleeps.append(value)
            clock[0] += value

        with FileLock(path):
            with (
                patch("runtime.file_lock.time.monotonic", side_effect=lambda: clock[0]),
                patch("runtime.file_lock.time.sleep", side_effect=sleep),
                patch("runtime.file_lock.random.uniform", return_value=1.0),
            ):
                with pytest.raises(FileLockTimeout):
                    with FileLock(
                        path,
                        timeout_seconds=0.04,
                        minimum_sleep_seconds=0.005,
                        maximum_sleep_seconds=0.02,
                    ):
                        pass
        assert sleeps[:3] == [0.005, 0.01, 0.02]
        assert max(sleeps) <= 0.02


def test_file_lock_times_out_without_busy_spin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        with FileLock(path):
            contender = FileLock(
                path,
                timeout_seconds=0.05,
                minimum_sleep_seconds=0.005,
                maximum_sleep_seconds=0.02,
            )
            with pytest.raises(FileLockTimeout):
                contender.__enter__()
        assert contender.attempts < 20
        # On a loaded host the first filesystem/lease inspection can itself
        # consume the 50 ms budget.  One bounded attempt is not a busy spin;
        # repeated attempts must demonstrate backoff sleep.
        assert contender.attempts == 1 or contender.slept_seconds > 0


def test_file_lock_high_contention_processes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_lock,
            args=(str(Path(directory) / "control.lock"), ready, release),
        )
        process.start()
        try:
            assert ready.wait(15)
            with pytest.raises(FileLockTimeout):
                with FileLock(Path(directory) / "control.lock", timeout_seconds=0.05):
                    pass
        finally:
            release.set()
            process.join(15)
        assert process.exitcode == 0


def test_file_lock_stream_cleanup_on_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        with FileLock(path):
            contender = FileLock(path, timeout_seconds=0.02)
            with pytest.raises(FileLockTimeout):
                contender.__enter__()
        assert contender._stream is None


def test_file_lock_windows_permission_race_retries() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        original = Path.open
        attempts = {"initialize": 0}

        def raced(self: Path, mode: str = "r", *args, **kwargs):
            if self == path and mode == "xb" and attempts["initialize"] == 0:
                attempts["initialize"] += 1
                path.touch()
                raise PermissionError("simulated creator race")
            return original(self, mode, *args, **kwargs)

        with patch.object(Path, "open", raced):
            with FileLock(path, timeout_seconds=1) as acquired:
                assert acquired._stream is not None
        assert attempts["initialize"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows process-state regression")
def test_file_lock_windows_process_probe_distinguishes_exited_process() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _process_exists(process.pid)
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert not _process_exists(process.pid)


def _write_lease(path: Path, value: dict[str, object]) -> None:
    path.write_bytes(
        b"0" + json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    )


def _read_lease(path: Path) -> dict[str, object]:
    return json.loads(path.read_bytes()[1:].decode("ascii"))


def test_file_lock_heartbeat_refreshes_after_thirty_seconds_without_sleep() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        acquired_ns = 1_700_000_000_000_000_000
        with patch("runtime.file_lock.time.time_ns", return_value=acquired_ns):
            lock = FileLock(path, heartbeat_interval_seconds=3600)
            lock.__enter__()
        try:
            assert lock._lease is not None
            original = dict(lock._lease)
            after_31_seconds = acquired_ns + 31_000_000_000
            with patch("runtime.file_lock.time.time_ns", return_value=after_31_seconds):
                lock._heartbeat_once()
            refreshed = dict(lock._lease)
            assert refreshed["token"] == original["token"]
            assert refreshed["heartbeat_unix_ns"] == after_31_seconds
            assert (
                refreshed["heartbeat_unix_ns"] - original["heartbeat_unix_ns"]
                > 30_000_000_000
            )
        finally:
            lock.__exit__(None, None, None)
        persisted = _read_lease(path)
        assert persisted["heartbeat_unix_ns"] == after_31_seconds


def test_file_lock_refuses_free_byte_lock_with_live_owner_lease() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        fingerprint = _process_start_fingerprint(os.getpid())
        assert fingerprint is not None
        retained = {
            "schema_version": "1.0",
            "state": "held",
            "token": "retained-live-owner",
            "pid": os.getpid(),
            "hostname": "test",
            "process_start_fingerprint": fingerprint,
            "acquired_unix_ns": 1,
            "heartbeat_unix_ns": 2,
        }
        _write_lease(path, retained)
        contender = FileLock(
            path,
            timeout_seconds=0.02,
            minimum_sleep_seconds=0.005,
            maximum_sleep_seconds=0.01,
            heartbeat_interval_seconds=3600,
        )
        with pytest.raises(FileLockTimeout, match="retained-live-owner"):
            contender.__enter__()
        assert _read_lease(path) == retained
        assert contender.recovery_receipt_path is None


def test_bsd_process_birth_identity_uses_bounded_native_ps() -> None:
    completed = subprocess.CompletedProcess(
        ["ps"], 0, stdout="Mon Aug 13 12:34:56 2026\n", stderr=""
    )
    with (
        patch("runtime.file_lock.sys.platform", "darwin"),
        patch("runtime.file_lock.subprocess.run", return_value=completed) as run,
    ):
        assert _bsd_process_start(42) == "bsd-ps-lstart:Mon Aug 13 12:34:56 2026"
    run.assert_called_once()
    assert run.call_args.kwargs["timeout"] == 2
    assert run.call_args.kwargs["shell"] is False


def test_file_lock_recovers_dead_owner_and_retains_receipt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        retained = {
            "schema_version": "1.0",
            "state": "held",
            "token": "retained-dead-owner",
            "pid": 2_147_483_647,
            "hostname": "test",
            "process_start_fingerprint": "0" * 64,
            "acquired_unix_ns": 1,
            "heartbeat_unix_ns": 2,
        }
        _write_lease(path, retained)
        with FileLock(path, heartbeat_interval_seconds=3600) as acquired:
            assert acquired.recovery_receipt_path is not None
            receipt_path = acquired.recovery_receipt_path
            assert receipt_path.is_file()
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt["receipt_type"] == "dead_file_lock_owner_recovery"
            assert receipt["reason"] == "recorded_owner_not_live"
            assert receipt["previous_lease"] == retained
            assert acquired._lease is not None
            assert receipt["recovered_by"]["token"] == acquired._lease["token"]
        assert receipt_path.is_file()
        assert _read_lease(path)["state"] == "released"
