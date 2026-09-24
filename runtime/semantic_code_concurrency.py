"""Per-project serialization and single-flight helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Callable, Generic, Iterator, TypeVar


T = TypeVar("T")


class ProjectLockPool:
    """Return stable re-entrant locks keyed by canonical project identity."""

    def __init__(self) -> None:
        self._guard = RLock()
        self._locks: dict[str, RLock] = {}

    def get(self, project_key: str) -> RLock:
        if not project_key:
            raise ValueError("project key must be non-empty")
        with self._guard:
            return self._locks.setdefault(project_key, RLock())

    @contextmanager
    def hold(self, project_key: str) -> Iterator[None]:
        lock = self.get(project_key)
        with lock:
            yield


@dataclass
class _Flight(Generic[T]):
    condition: Condition
    running: bool = True
    result: T | None = None
    error: BaseException | None = None


class SingleFlight(Generic[T]):
    """Coalesce concurrent identical work without caching completed results."""

    def __init__(self) -> None:
        self._guard = RLock()
        self._flights: dict[str, _Flight[T]] = {}

    def call(self, key: str, function: Callable[[], T]) -> T:
        if not key:
            raise ValueError("single-flight key must be non-empty")
        leader = False
        with self._guard:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight(condition=Condition(self._guard))
                self._flights[key] = flight
                leader = True
            if not leader:
                while flight.running:
                    flight.condition.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result  # type: ignore[return-value]
        try:
            result = function()
        except BaseException as error:
            with self._guard:
                flight.error = error
                flight.running = False
                flight.condition.notify_all()
                self._flights.pop(key, None)
            raise
        with self._guard:
            flight.result = result
            flight.running = False
            flight.condition.notify_all()
            self._flights.pop(key, None)
        return result
