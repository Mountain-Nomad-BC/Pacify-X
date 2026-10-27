"""Isolated effect observers.

Observers are the *external* authority on what actually happened: an OS/kernel
network observer, a process/job observer, a filesystem observer. They are
read-only relative to the protected workload and are supplied by the caller, not
by the protected execution. Gremlin consumes their findings; it does not trust the
workload's own telemetry as sole truth (plan section 26).

An observer that is unavailable degrades the workload's capability (fail closed):
loss of observation cannot increase the agent's freedom (GN-INV-007).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

SCHEMA_VERSION = "px.gremlin-observers/1.0"

OBSERVER_KINDS = ("network", "process_tree", "filesystem", "ipc")


class Observer(Protocol):
    """A read-only observer of one effect surface."""

    kind: str
    available: bool

    def poll(self) -> tuple[object, ...]:
        """Return newly observed effect events (never mutate the workload)."""
        ...


@dataclass
class ObserverHealth:
    network: bool = True
    process_tree: bool = True
    filesystem: bool = True
    ipc: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "network": self.network,
            "process_tree": self.process_tree,
            "filesystem": self.filesystem,
            "ipc": self.ipc,
        }

    def missing(self) -> tuple[str, ...]:
        return tuple(kind for kind, ok in self.as_dict().items() if not ok)


@dataclass
class ObserverSet:
    """The registered observers for a Gremlin instance.

    ``observers`` is a mapping from observer kind to a zero-argument poll function.
    The functions are provided by the *host*, which is why the workload cannot
    register or remove an observer.
    """

    observers: dict[str, Callable[[], tuple[object, ...]]] = field(default_factory=dict)
    health: ObserverHealth = field(default_factory=ObserverHealth)

    def register(self, kind: str, poll: Callable[[], tuple[object, ...]]) -> None:
        if kind not in OBSERVER_KINDS:
            raise ValueError(f"unknown observer kind {kind!r}")
        if not callable(poll):
            raise TypeError("observer must be a callable poll function")
        self.observers[kind] = poll
        setattr(self.health, kind, True)

    def unregister(self, kind: str) -> None:
        self.observers.pop(kind, None)
        if kind in OBSERVER_KINDS:
            setattr(self.health, kind, False)

    def poll_all(self) -> tuple[tuple[str, tuple[object, ...]], ...]:
        results = []
        for kind in OBSERVER_KINDS:
            poll = self.observers.get(kind)
            if poll is None:
                setattr(self.health, kind, False)
                results.append((kind, ()))
                continue
            try:
                results.append((kind, tuple(poll())))
                setattr(self.health, kind, True)
            except Exception:
                # An observer that fails becomes unavailable; the workload loses
                # capability, never gains it.
                setattr(self.health, kind, False)
                results.append((kind, ()))
        return tuple(results)