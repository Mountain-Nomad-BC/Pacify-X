"""Advisory latency budgets with required-stage protection and optional shedding."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from time import monotonic
from typing import Callable, Iterable


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _finite_nonnegative(value: object, label: str) -> float:
    if type(value) not in (int, float) or type(value) is bool:
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result


@dataclass(frozen=True, slots=True)
class StageBudget:
    stage: str
    minimum_remaining_ms: float
    required: bool = False
    shed_rank: int = 100

    def __post_init__(self) -> None:
        if type(self.stage) is not str or not self.stage.strip() or len(self.stage.encode()) > 256:
            raise ValueError("stage must be a bounded identifier")
        _finite_nonnegative(self.minimum_remaining_ms, "minimum_remaining_ms")
        if type(self.required) is not bool:
            raise ValueError("required must be a literal boolean")
        if type(self.shed_rank) is not int or type(self.shed_rank) is bool or self.shed_rank < 0:
            raise ValueError("shed_rank must be a nonnegative integer")

    @property
    def soft_deadline_ms(self) -> float:  # compatibility alias
        return self.minimum_remaining_ms


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    stage: str
    allowed: bool
    reason: str
    elapsed_ms: float
    remaining_ms: float
    required: bool
    decision_sha256: str


class LatencyBudget:
    """Request deadline helper. Required correctness stages are never shed."""

    def __init__(self, total_ms: float, *, clock: Callable[[], float] = monotonic) -> None:
        self.total_ms = _finite_nonnegative(total_ms, "total_ms")
        if self.total_ms <= 0:
            raise ValueError("total_ms must be greater than zero")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._clock = clock
        self.started_at = self._sample(None)
        self._last_sample = self.started_at

    def _sample(self, previous: float | None) -> float:
        value = self._clock()
        if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)):
            raise ValueError("latency clock returned a non-finite sample")
        sample = float(value)
        if previous is not None and sample < previous:
            raise ValueError("latency clock moved backwards")
        return sample

    def _elapsed(self) -> float:
        sample = self._sample(self._last_sample)
        self._last_sample = sample
        return max(0.0, (sample - self.started_at) * 1000.0)

    def elapsed_ms(self) -> float:
        return self._elapsed()

    def remaining_ms(self) -> float:
        return max(0.0, self.total_ms - self._elapsed())

    def admit(self, stage: StageBudget) -> BudgetDecision:
        if type(stage) is not StageBudget:
            raise ValueError("typed StageBudget required")
        elapsed = self._elapsed()
        remaining = max(0.0, self.total_ms - elapsed)
        if stage.required:
            allowed, reason = True, "required_stage" if remaining > 0 else "required_stage_over_budget"
        elif remaining < float(stage.minimum_remaining_ms):
            allowed, reason = False, "insufficient_remaining_budget"
        else:
            allowed, reason = True, "budget_available"
        payload = {
            "stage": stage.stage,
            "allowed": allowed,
            "reason": reason,
            "elapsed_ms": round(elapsed, 6),
            "remaining_ms": round(remaining, 6),
            "required": stage.required,
            "total_ms": self.total_ms,
            "minimum_remaining_ms": float(stage.minimum_remaining_ms),
        }
        return BudgetDecision(stage.stage, allowed, reason, payload["elapsed_ms"], payload["remaining_ms"], stage.required, _sha(payload))

    def choose_optional(self, stages: Iterable[StageBudget]) -> tuple[StageBudget, ...]:
        rows = tuple(stages)
        if any(type(row) is not StageBudget or row.required for row in rows):
            raise ValueError("choose_optional accepts optional StageBudget records only")
        allowed: list[StageBudget] = []
        for stage in sorted(rows, key=lambda item: (item.shed_rank, item.minimum_remaining_ms, item.stage)):
            if self.admit(stage).allowed:
                allowed.append(stage)
        return tuple(allowed)
