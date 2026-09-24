"""Bounded restart accounting and unhealthy-server quarantine."""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time

from .semantic_lsp_types import ServerHealthSnapshot, ServerState


class ServerQuarantinedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    max_restarts: int = 3
    window_seconds: float = 300.0
    consecutive_failure_limit: int = 3

    def __post_init__(self) -> None:
        if type(self.max_restarts) is not int or not 0 <= self.max_restarts <= 100:
            raise ValueError("max_restarts outside supported bounds")
        if (
            isinstance(self.window_seconds, bool)
            or not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(float(self.window_seconds))
            or self.window_seconds <= 0
            or self.window_seconds > 86400
        ):
            raise ValueError("window_seconds must be finite, positive and <= 86400")
        if type(self.consecutive_failure_limit) is not int or not 1 <= self.consecutive_failure_limit <= 100:
            raise ValueError("consecutive_failure_limit outside supported bounds")


class ServerHealth:
    def __init__(self, server_id: str, policy: RestartPolicy = RestartPolicy()):
        self.server_id = server_id
        self.policy = policy
        self._lock = RLock()
        self._state = ServerState.NEW
        self._starts = 0
        self._failures = 0
        self._consecutive = 0
        self._last_error: str | None = None
        self._quarantined: str | None = None
        self._restart_times: list[float] = []

    def mark_starting(self) -> None:
        with self._lock:
            if self._quarantined:
                raise ServerQuarantinedError(self._quarantined)
            now = time.monotonic()
            self._restart_times = [t for t in self._restart_times if now - t <= self.policy.window_seconds]
            is_restart = self._starts > 0
            if is_restart and len(self._restart_times) >= self.policy.max_restarts:
                self._quarantine("restart budget exhausted")
                raise ServerQuarantinedError(self._quarantined or "quarantined")
            if is_restart:
                self._restart_times.append(now)
            self._starts += 1
            self._state = ServerState.STARTING

    def mark_running(self) -> None:
        with self._lock:
            if not self._quarantined:
                self._state = ServerState.RUNNING
                self._consecutive = 0

    def mark_failure(self, error: BaseException | str) -> None:
        with self._lock:
            self._failures += 1
            self._consecutive += 1
            self._last_error = str(error)[:2048]
            self._state = ServerState.DEGRADED
            if self._consecutive >= self.policy.consecutive_failure_limit:
                self._quarantine("consecutive failure limit reached")

    def mark_stopping(self) -> None:
        with self._lock:
            if not self._quarantined:
                self._state = ServerState.STOPPING

    def mark_stopped(self) -> None:
        with self._lock:
            if not self._quarantined:
                self._state = ServerState.STOPPED

    def _quarantine(self, reason: str) -> None:
        self._state = ServerState.QUARANTINED
        self._quarantined = reason

    def clear_quarantine(self) -> None:
        with self._lock:
            self._quarantined = None
            self._consecutive = 0
            self._restart_times.clear()
            self._state = ServerState.STOPPED

    def snapshot(self) -> ServerHealthSnapshot:
        with self._lock:
            return ServerHealthSnapshot(
                self.server_id,
                self._state,
                self._starts,
                self._failures,
                self._consecutive,
                self._last_error,
                self._quarantined,
            )
