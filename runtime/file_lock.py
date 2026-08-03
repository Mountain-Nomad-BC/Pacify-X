"""Small cross-platform advisory file lock used by persistent control projections."""
from __future__ import annotations

from pathlib import Path
import time


class FileLock:
    """Acquire one non-blocking exclusive byte lock; preserve the lock file."""

    def __init__(self, path: Path, *, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._stream = None

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
        while True:
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
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    if self._stream is not None:
                        self._stream.close()
                    self._stream = None
                    raise RuntimeError(f"control state is locked by another process: {self.path}") from error
                time.sleep(0.01)
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
