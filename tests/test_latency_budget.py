from __future__ import annotations

import math
import pytest

from runtime.latency_budget import LatencyBudget, StageBudget


class Clock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)
    def __call__(self) -> float:
        return next(self.values)


def test_required_stage_is_never_shed_even_after_budget() -> None:
    budget = LatencyBudget(10, clock=Clock(1.0, 1.020))
    decision = budget.admit(StageBudget("authority", 5, required=True))
    assert decision.allowed
    assert decision.reason == "required_stage_over_budget"
    assert len(decision.decision_sha256) == 64


def test_optional_stage_is_shed_when_remaining_budget_is_too_small() -> None:
    budget = LatencyBudget(100, clock=Clock(1.0, 1.060))
    decision = budget.admit(StageBudget("rerank", 50, required=False))
    assert not decision.allowed
    assert decision.reason == "insufficient_remaining_budget"


def test_clock_rollback_fails_closed() -> None:
    budget = LatencyBudget(100, clock=Clock(2.0, 1.0))
    with pytest.raises(ValueError, match="moved backwards"):
        budget.remaining_ms()


def test_nonfinite_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        LatencyBudget(math.nan)
