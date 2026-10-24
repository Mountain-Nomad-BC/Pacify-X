"""One-shot remediation.

For a remediable violation, Gremlin gets exactly one bounded corrective attempt.
This prevents endless adversarial negotiation, prompt-injection loops, and
repeated probing of policy boundaries (GN-INV-005, GN-INV-006).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

SCHEMA_VERSION = "px.gremlin-intervention/1.0"

ALLOWED_RESPONSES = frozenset({"complied", "already_closed", "authorized_exception_reference"})


@dataclass(frozen=True, slots=True)
class Intervention:
    intervention_id: str
    event_id: str
    agent_execution_id: str
    violation_type: str
    required_action: str
    required_target: str
    deadline_ms: int
    allowed_response: tuple[str, ...]
    max_response_count: int
    failure_action: str

    def __post_init__(self) -> None:
        if self.max_response_count != 1:
            raise ValueError("the one-shot rule permits exactly one response")
        if not 1 <= self.deadline_ms <= 600_000:
            raise ValueError("intervention deadline must be bounded and positive")
        if any(item not in ALLOWED_RESPONSES for item in self.allowed_response):
            raise ValueError("unknown allowed intervention response")

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


@dataclass
class InterventionTracker:
    """Tracks the single bounded corrective attempt for one event.

    The response count is monotonic and never reset. A second response for the
    same intervention is refused, so an agent cannot negotiate repeatedly.
    """

    intervention: Intervention
    responses: list[dict[str, object]] = field(default_factory=list)
    issued_at_utc: str = ""
    resolved: bool = False
    outcome: str | None = None

    def issue(self, *, now: datetime | None = None) -> datetime:
        moment = now or datetime.now(timezone.utc)
        self.issued_at_utc = moment.isoformat()
        return moment + timedelta(milliseconds=self.intervention.deadline_ms)

    @property
    def deadline_utc(self) -> datetime:
        if not self.issued_at_utc:
            raise ValueError("intervention has not been issued")
        return datetime.fromisoformat(self.issued_at_utc) + timedelta(
            milliseconds=self.intervention.deadline_ms
        )

    def respond(self, response: str, *, now: datetime | None = None) -> str:
        """Record the single allowed response and return the outcome.

        Outcomes: ``complied``/``already_closed``/``authorized_exception_reference``
        resume the execution; ``timeout``/``failed`` terminate it.
        """
        if self.resolved:
            raise ValueError("intervention already resolved")
        if len(self.responses) >= self.intervention.max_response_count:
            raise ValueError("the one-shot rule permits no further response")
        if response not in self.intervention.allowed_response:
            raise ValueError(f"response {response!r} is not allowed for this intervention")
        moment = now or datetime.now(timezone.utc)
        self.responses.append({"response": response, "at_utc": moment.isoformat()})
        self.resolved = True
        self.outcome = response
        return response

    def expire(self, *, now: datetime | None = None) -> str:
        """Resolve as timeout when the bounded window elapsed without compliance."""
        moment = now or datetime.now(timezone.utc)
        if moment >= self.deadline_utc:
            self.resolved = True
            self.outcome = "timeout"
            return "timeout"
        raise ValueError("intervention window has not elapsed")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "intervention": self.intervention.as_dict(),
            "responses": list(self.responses),
            "issued_at_utc": self.issued_at_utc,
            "resolved": self.resolved,
            "outcome": self.outcome,
        }