"""Core event envelope and normalized effect events.

All Gremlin components join on a common set of IDs so a single deviation timeline
can be reconstructed: ``event_id``, ``execution_id``, ``correlation_id``,
``trace_id``, ``process_identity``, ``socket_id``, ``tool_call_id``,
``authorization_id``, ``intervention_id``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import itertools
import re
from typing import Any, Mapping

from ..json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.gremlin-event/1.0"

_MONOTONIC = itertools.count(1)

EFFECT_TYPES = frozenset(
    {
        "outbound_network",
        "inbound_listener",
        "dns",
        "filesystem_write",
        "filesystem_escape",
        "executable_creation",
        "process_spawn",
        "ipc",
        "service_creation",
        "scheduled_task",
        "registry_change",
        "secret_access",
        "browser_automation",
        "external_api",
        "device_access",
        "raw_socket",
        "process_injection",
        "debugger_attach",
        "privilege_escalation",
        "containment_control_interference",
    }
)

# Decision categories (plan section 7): do not reduce every event to safe/unsafe.
DECISION_CATEGORIES = frozenset(
    {
        "expected_authorized",
        "expected_unauthorized",
        "unexpected_authorized",
        "unexpected_unauthorized",
        "unknown_unresolved",
        "containment_control_interference",
    }
)

_HEX = re.compile("[0-9a-f]{64}")


def _text(value: Any, name: str, *, max_len: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_len:
        raise ValueError(f"{name} must be bounded nonempty text")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _optional_text(value: Any, name: str, *, max_len: int = 512) -> str | None:
    if value is None:
        return None
    return _text(value, name, max_len=max_len)


@dataclass(frozen=True, slots=True)
class EffectEvent:
    """A normalized effect observed on a protected execution's surface."""

    event_id: str
    effect_type: str
    execution_id: str
    agent_id: str
    pid: int
    process_start_identity: str
    sandbox_id: str | None
    target: str
    action: str
    requested_scope: str
    observed_scope: str
    timestamp_utc: str
    correlation_id: str
    trace_id: str
    source_component: str
    socket_id: str | None = None
    tool_call_id: str | None = None
    monotonic_sequence: int = field(default_factory=lambda: next(_MONOTONIC))
    policy_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        if self.effect_type not in EFFECT_TYPES:
            raise ValueError(f"unknown effect type {self.effect_type!r}")
        for name in ("execution_id", "agent_id", "process_start_identity", "target",
                     "action", "requested_scope", "observed_scope", "correlation_id",
                     "trace_id", "source_component"):
            _text(getattr(self, name), name)
        _text(self.timestamp_utc, "timestamp_utc", max_len=64)
        for name in ("sandbox_id", "socket_id", "tool_call_id"):
            _optional_text(getattr(self, name), name)
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("effect event pid must be a positive integer")
        if type(self.monotonic_sequence) is not int or self.monotonic_sequence <= 0:
            raise ValueError("monotonic sequence must be a positive integer")

    def _body(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @property
    def event_sha256(self) -> str:
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=65536)).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {**self._body(), "event_sha256": self.event_sha256}


@dataclass(frozen=True, slots=True)
class CoreEvent:
    """The generic event envelope used by every Gremlin component."""

    event_id: str
    event_type: str
    execution_id: str
    source_component: str
    timestamp_utc: str
    payload: Mapping[str, Any]
    correlation_id: str | None = None
    trace_id: str | None = None
    integrity_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "event_type", "execution_id", "source_component", "timestamp_utc"):
            _text(getattr(self, name), name, max_len=128)
        if not isinstance(self.payload, Mapping):
            raise ValueError("core event payload must be a mapping")

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": "px.gremlin-core-event/1.0", **asdict(self)}