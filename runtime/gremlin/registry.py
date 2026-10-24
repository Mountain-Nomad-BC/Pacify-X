"""Protected-execution registry (Gremlin enrollment).

The registry holds the durable identity of every protected execution and its
containment state. Enrollment happens *before* workload release: a protected
execution must not run until it is registered and its containment is
acknowledged. Missing enrollment fails closed.

The registry is in-memory for a single control-plane instance and is deliberately
not writable by the workload: only the containment facade mutates it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ..json_io import bounded_canonical_json_bytes
from .identity import ProcessIdentity
from ..resource_lifecycle import VerifiedJobMembership

SCHEMA_VERSION = "px.gremlin-registry/1.0"

# Runtime state machine (plan section 29).
STATES = (
    "UNREGISTERED",
    "REGISTERED",
    "CONTAINMENT_ACKNOWLEDGED",
    "RUNNING_PROTECTED",
    "EVENT_OBSERVED",
    "EVALUATING",
    "INTERVENTION",
    "RESTRICTED",
    "TERMINATING",
    "TERMINATED",
    "DEVIATION_SEALED",
    "ANALYSIS_PENDING",
)

TERMINAL_STATES = frozenset({"TERMINATED", "DEVIATION_SEALED", "ANALYSIS_PENDING"})

# The only terminal-state progression: a terminated execution may seal its
# deviation and then queue for analysis. It is never resurrected to a live state.
TERMINAL_PROGRESSION = {
    "TERMINATED": ("DEVIATION_SEALED",),
    "DEVIATION_SEALED": ("ANALYSIS_PENDING",),
    "ANALYSIS_PENDING": (),
}


class EnrollmentError(ValueError):
    """Raised when enrollment is missing, duplicated or invalid (fail closed)."""


@dataclass(frozen=True, slots=True)
class ProtectedExecution:
    identity: ProcessIdentity
    state: str
    containment_receipt_id: str | None
    child_execution_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown protected execution state {self.state!r}")

    @property
    def agent_execution_id(self) -> str:
        return self.identity.agent_execution_id

    @property
    def released(self) -> bool:
        """True only when containment was acknowledged before workload release."""
        return self.containment_receipt_id is not None and self.state in {
            "RUNNING_PROTECTED", "EVENT_OBSERVED", "EVALUATING", "INTERVENTION",
            "RESTRICTED", "TERMINATING", "TERMINATED", "DEVIATION_SEALED", "ANALYSIS_PENDING",
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "identity": self.identity.as_dict(),
            "state": self.state,
            "containment_receipt_id": self.containment_receipt_id,
            "child_execution_ids": list(self.child_execution_ids),
        }


class ProtectedExecutionRegistry:
    """The authoritative in-memory registry of protected executions."""

    def __init__(self) -> None:
        self._executions: dict[str, ProtectedExecution] = {}
        self._pid_index: dict[int, set[str]] = {}

    def enroll(self, identity: ProcessIdentity) -> ProtectedExecution:
        key = identity.agent_execution_id
        if key in self._executions:
            raise EnrollmentError(f"execution {key!r} is already enrolled")
        # Many-to-one PID attribution: a shared broker PID may host several
        # protected sessions. The PID index is a fast lookup, not identity.
        self._pid_index.setdefault(identity.pid, set()).add(key)
        execution = ProtectedExecution(identity=identity, state="REGISTERED", containment_receipt_id=None)
        self._executions[key] = execution
        return execution

    def acknowledge_containment(self, agent_execution_id: str, receipt_id: str) -> ProtectedExecution:
        current = self._require(agent_execution_id)
        if type(receipt_id) is not str or not receipt_id.strip():
            raise EnrollmentError("containment acknowledgment requires a receipt identity")
        if current.containment_receipt_id is not None and current.containment_receipt_id != receipt_id:
            raise EnrollmentError("containment receipt cannot be replaced")
        updated = ProtectedExecution(
            identity=current.identity,
            state="CONTAINMENT_ACKNOWLEDGED",
            containment_receipt_id=receipt_id,
            child_execution_ids=current.child_execution_ids,
        )
        self._executions[agent_execution_id] = updated
        return updated

    def transition(self, agent_execution_id: str, state: str) -> ProtectedExecution:
        if state not in STATES:
            raise EnrollmentError(f"unknown state {state!r}")
        current = self._require(agent_execution_id)
        if current.state in TERMINAL_STATES and state != current.state:
            # Only the forward terminal progression is permitted; a terminal
            # execution can never be resurrected to a live/running state.
            if state not in TERMINAL_PROGRESSION.get(current.state, ()):
                raise EnrollmentError("terminal protected execution cannot be resurrected")
        updated = ProtectedExecution(
            identity=current.identity,
            state=state,
            containment_receipt_id=current.containment_receipt_id,
            child_execution_ids=current.child_execution_ids,
        )
        self._executions[agent_execution_id] = updated
        return updated

    def register_child(self, parent_execution_id: str, child_execution_id: str) -> ProtectedExecution:
        self._require(parent_execution_id)
        raise EnrollmentError(
            "child containment requires an OS-verified child identity and "
            "supervisor-owned containment evidence"
        )

    def register_verified_child(
        self,
        parent_execution_id: str,
        child_execution_id: str,
        custody: VerifiedJobMembership,
    ) -> ProtectedExecution:
        parent = self._require(parent_execution_id)
        child = self._require(child_execution_id)
        if type(custody) is not VerifiedJobMembership:
            raise EnrollmentError("verified supervisor Job membership evidence is required")
        if parent.state in TERMINAL_STATES:
            raise EnrollmentError("terminal execution cannot acquire child processes")
        if child.state not in {"CONTAINMENT_ACKNOWLEDGED", "RUNNING_PROTECTED"}:
            raise EnrollmentError("child must be contained before lineage registration")
        if (
            child.identity.parent_execution_id != parent_execution_id
            or child.identity.pid != custody.member_pid
            or child.identity.process_start_identity != custody.member_process_start_identity
            or child.identity.job_object_id != custody.job_object_id
            or parent.identity.job_object_id != custody.job_object_id
        ):
            raise EnrollmentError("child identity does not match verified parent Job membership")
        if child_execution_id in parent.child_execution_ids:
            raise EnrollmentError("child execution is already linked to this parent")
        updated = ProtectedExecution(
            identity=parent.identity,
            state=parent.state,
            containment_receipt_id=parent.containment_receipt_id,
            child_execution_ids=parent.child_execution_ids + (child_execution_id,),
        )
        self._executions[parent_execution_id] = updated
        return updated

    def resolve(self, *, pid: int, process_start_identity: str) -> tuple[ProtectedExecution, ...]:
        """Resolve every protected execution for a PID with the exact start identity.

        A PID-only match returns nothing: a recycled PID with a different
        process-start identity must not resolve to a live protected execution
        (GN-INV-004).
        """
        matches = []
        for key in self._pid_index.get(pid, set()):
            execution = self._executions.get(key)
            if execution is not None and execution.identity.matches(
                pid=pid, process_start_identity=process_start_identity
            ):
                matches.append(execution)
        return tuple(matches)

    def get(self, agent_execution_id: str) -> ProtectedExecution | None:
        return self._executions.get(agent_execution_id)

    def active(self) -> tuple[ProtectedExecution, ...]:
        return tuple(
            execution
            for execution in self._executions.values()
            if execution.state not in TERMINAL_STATES
        )

    def _require(self, agent_execution_id: str) -> ProtectedExecution:
        execution = self._executions.get(agent_execution_id)
        if execution is None:
            raise EnrollmentError(f"execution {agent_execution_id!r} is not enrolled (fail closed)")
        return execution

    def registry_sha256(self) -> str:
        body = {
            "schema_version": SCHEMA_VERSION,
            "executions": [self._executions[key].as_dict() for key in sorted(self._executions)],
        }
        return hashlib.sha256(bounded_canonical_json_bytes(body, max_bytes=4_194_304)).hexdigest()