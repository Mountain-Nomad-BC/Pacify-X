"""Deterministic enforcement supervisor.

The final enforcement path never depends on an LLM. The supervisor freezes or
kills the protected execution tree using the platform process identity. It remains
operational even if the model service, analytics or orchestration are down
(GN-INV-012).

The supervisor is supplied by the host as a set of bounded primitives
(``freeze``/``terminate_tree``) so the enforcement mechanism is a real OS action,
not a no-op. An unavailable supervisor fails closed: high-risk execution is
frozen/refused rather than allowed to continue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Protocol

SCHEMA_VERSION = "px.gremlin-supervisor/1.0"

ENFORCEMENT_ACTIONS = frozenset(
    {"terminate_execution_tree", "freeze_execution", "revoke_network", "deny", "none"}
)


class SupervisorUnavailable(RuntimeError):
    """Raised when enforcement cannot be performed; callers must fail closed."""


class EnforcementBackend(Protocol):
    """Host-supplied bounded OS enforcement primitives."""

    available: bool

    def terminate_tree(self, identity: dict[str, object]) -> dict[str, object]:
        ...

    def freeze(self, identity: dict[str, object]) -> dict[str, object]:
        ...


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    action: str
    performed: bool
    scope: str
    identity_sha256: str
    detail: str
    supervisor_healthy: bool

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


class DeterministicSupervisor:
    """Applies enforcement against a validated process identity."""

    def __init__(self, backend: EnforcementBackend | None = None) -> None:
        self._backend = backend

    @property
    def healthy(self) -> bool:
        return self._backend is not None and bool(getattr(self._backend, "available", False))

    def enforce(
        self,
        action: str,
        *,
        identity: dict[str, object],
        expected_pid: int,
        expected_process_start_identity: str,
        kill_scope: str = "protected_execution_tree",
    ) -> EnforcementResult:
        """Apply enforcement, validating the identity before any destructive act.

        A PID that does not match the process-start identity is refused
        (GN-INV-004): enforcement never runs against a recycled PID.
        """
        if action not in ENFORCEMENT_ACTIONS:
            raise ValueError(f"unknown enforcement action {action!r}")
        if action == "none":
            return EnforcementResult("none", False, kill_scope, "", "no enforcement required", self.healthy)
        actual_pid = identity.get("pid")
        actual_start = identity.get("process_start_identity")
        if actual_pid != expected_pid or actual_start != expected_process_start_identity:
            raise SupervisorUnavailable(
                "refusing enforcement: process identity does not match the registered tuple"
            )
        if self._backend is None or not self.healthy:
            raise SupervisorUnavailable(
                "enforcement backend is unavailable; high-risk execution must be frozen/refused"
            )
        if action == "terminate_execution_tree":
            detail = self._backend.terminate_tree(identity)
            return EnforcementResult(
                action,
                self._backend_confirmed(detail, "terminated"),
                kill_scope,
                str(identity.get("identity_sha256", "")),
                str(detail)[:512],
                True,
            )
        if action == "freeze_execution":
            detail = self._backend.freeze(identity)
            return EnforcementResult(
                action,
                self._backend_confirmed(detail, "frozen"),
                kill_scope,
                str(identity.get("identity_sha256", "")),
                str(detail)[:512],
                True,
            )
        # revoke_network / deny are handled by the containment facade (no OS kill).
        return EnforcementResult(action, True, kill_scope, str(identity.get("identity_sha256", "")), "handled by containment", True)

    @staticmethod
    def _backend_confirmed(detail: object, expected_key: str) -> bool:
        """A backend invocation is not a verified outcome (G05).

        ``performed`` is True only when the backend's structured result confirms
        the requested OS postcondition. An unstructured detail is treated as
        unconfirmed (fail closed) — the caller must treat it as an enforcement
        failure, not as success.
        """
        if isinstance(detail, Mapping):
            if expected_key in detail:
                return detail[expected_key] is True
            if detail.get("performed") is True:
                return True
            return False
        return False