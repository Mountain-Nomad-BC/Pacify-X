from __future__ import annotations

import multiprocessing
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from runtime.file_lock import FileLock, FileLockTimeout


def _hold_lock(path: str, ready, release) -> None:
    with FileLock(Path(path), timeout_seconds=2):
        ready.set(); release.wait(5)


def test_file_lock_exponential_backoff() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        sleeps: list[float] = []
        clock = [0.0]
        def sleep(value: float) -> None:
            sleeps.append(value); clock[0] += value
        with FileLock(path):
            with patch("runtime.file_lock.time.monotonic", side_effect=lambda: clock[0]), patch("runtime.file_lock.time.sleep", side_effect=sleep), patch("runtime.file_lock.random.uniform", return_value=1.0):
                with pytest.raises(FileLockTimeout):
                    with FileLock(path, timeout_seconds=0.04, minimum_sleep_seconds=0.005, maximum_sleep_seconds=0.02):
                        pass
        assert sleeps[:3] == [0.005, 0.01, 0.02]
        assert max(sleeps) <= 0.02


def test_file_lock_times_out_without_busy_spin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.lock"
        with FileLock(path):
            contender = FileLock(path, timeout_seconds=0.05, minimum_sleep_seconds=0.005, maximum_sleep_seconds=0.02)
            with pytest.raises(FileLockTimeout):
                contender.__enter__()
        assert contender.attempts < 20 and contender.slept_seconds > 0


def test_file_lock_high_contention_processes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        context = multiprocessing.get_context("spawn")
        ready = context.Event(); release = context.Event()
        process = context.Process(target=_hold_lock, args=(str(Path(directory) / "control.lock"), ready, release))
        process.start()
        try:
            assert ready.wait(5)
            with pytest.raises(FileLockTimeout):
                with FileLock(Path(directory) / "control.lock", timeout_seconds=0.05):
                    pass
        finally:
            release.set(); process.join(5)
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
