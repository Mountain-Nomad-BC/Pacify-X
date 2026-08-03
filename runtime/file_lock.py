"""Small cross-platform advisory file lock used by persistent control projections."""
from __future__ import annotations

from pathlib import Path
import os
import random
import time


class FileLockTimeout(RuntimeError):
    """Raised after a bounded lock-acquisition deadline expires."""


class FileLock:
    """Acquire one non-blocking exclusive byte lock; preserve the lock file."""

    def __init__(
        self, path: Path, *, timeout_seconds: float = 5.0,
        minimum_sleep_seconds: float = 0.005, maximum_sleep_seconds: float = 0.1,
    ) -> None:
        if timeout_seconds <= 0 or minimum_sleep_seconds <= 0 or maximum_sleep_seconds < minimum_sleep_seconds:
            raise ValueError("file-lock timing values must be positive and ordered")
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.minimum_sleep_seconds = minimum_sleep_seconds
        self.maximum_sleep_seconds = maximum_sleep_seconds
        self._stream = None
        self.attempts = 0
        self.slept_seconds = 0.0

    def _owner_diagnostic(self) -> str:
        try:
            value = self.path.read_text(encoding="ascii", errors="replace").strip("\x00\r\n ")
            return value or "owner unavailable"
        except OSError:
            return "owner unavailable"

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Initialize exactly once. Writing through every contender races with
        # an already-held Windows byte-range lock and can raise PermissionError.
        try:
            with self.path.open("xb") as initializer:
                initializer.write(b"0")
                initializer.flush()
        except (FileExistsError, PermissionError):
            # On Windows, a contender can observe PermissionError while the
            # winning thread is still creating/flushing the one-byte lock.
            # The acquisition loop below distinguishes that transient race
            # from a persistent permission failure through its timeout.
            self._stream = None
        deadline = time.monotonic() + self.timeout_seconds
        delay = self.minimum_sleep_seconds
        while True:
            self.attempts += 1
            try:
                if self._stream is None:
                    self._stream = self.path.open("r+b")
                self._stream.seek(0)
                if __import__("os").name == "nt":
                    import msvcrt
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._stream.seek(1)
                self._stream.truncate()
                self._stream.write(f"pid={os.getpid()} acquired={time.time_ns()}".encode("ascii"))
                self._stream.flush()
                break
            except OSError as error:
                now = time.monotonic()
                if now >= deadline:
                    owner = self._owner_diagnostic()
                    if self._stream is not None:
                        self._stream.close()
                    self._stream = None
                    raise FileLockTimeout(
                        f"control state is locked by another process: {self.path}; {owner}; attempts={self.attempts}"
                    ) from error
                remaining = deadline - now
                sleep_for = min(remaining, delay * random.uniform(0.8, 1.2))
                time.sleep(sleep_for)
                self.slept_seconds += sleep_for
                delay = min(self.maximum_sleep_seconds, delay * 2)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._stream is None:
            return
        self._stream.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None
