"""Durable protected-execution identity.

A PID alone is a *fast lookup index*, not durable identity: operating systems
reuse PIDs. The minimum strong tuple is

    (agent_execution_id, pid, process_start_identity, sandbox/job identity)

Every destructive enforcement decision must be validated against this tuple
before it is applied (GN-INV-004).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re

from ..json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.gremlin-execution-identity/1.0"

_DIGEST = re.compile("[0-9a-f]{64}")


def _bounded(value: str, name: str, *, max_len: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_len:
        raise ValueError(f"{name} must be bounded nonempty text")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _optional(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    return _bounded(value, name)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """The durable identity of one protected process.

    ``process_start_identity`` is the process-start time/token that distinguishes a
    live process from a recycled PID. ``sandbox_id`` / ``job_object_id`` are the
    platform containment identity (Windows Job Object, container/cgroup, etc.).
    """

    agent_execution_id: str
    agent_id: str
    pid: int
    process_start_identity: str
    parent_pid: int | None
    parent_execution_id: str | None
    sandbox_id: str | None
    job_object_id: str | None
    container_or_cgroup_id: str | None
    runtime_id: str | None
    model_id: str | None
    orchestration_id: str | None
    policy_profile: str
    registered_at_utc: str

    def __post_init__(self) -> None:
        _bounded(self.agent_execution_id, "agent_execution_id")
        _bounded(self.agent_id, "agent_id")
        _bounded(self.process_start_identity, "process_start_identity")
        _bounded(self.policy_profile, "policy_profile")
        _bounded(self.registered_at_utc, "registered_at_utc", max_len=64)
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("pid must be a positive integer")
        if self.parent_pid is not None and (type(self.parent_pid) is not int or self.parent_pid <= 0):
            raise ValueError("parent_pid must be a positive integer when present")
        for name in (
            "parent_execution_id", "sandbox_id", "job_object_id",
            "container_or_cgroup_id", "runtime_id", "model_id", "orchestration_id",
        ):
            _optional(getattr(self, name), name)

    def _body(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=16384)).hexdigest()

    def strong_tuple(self) -> tuple[str, int, str, str]:
        """The minimum strong identity tuple used to validate enforcement."""
        sandbox = self.sandbox_id or self.job_object_id or self.container_or_cgroup_id or ""
        return (self.agent_execution_id, self.pid, self.process_start_identity, sandbox)

    def matches(self, *, pid: int, process_start_identity: str) -> bool:
        """True only when the PID *and* the process-start identity both match.

        A PID-only match is never sufficient (GN-INV-004): a reused PID with a
        different process-start identity must be rejected.
        """
        return self.pid == pid and self.process_start_identity == process_start_identity

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "identity_sha256": self.identity_sha256, "strong_tuple": list(self.strong_tuple())}