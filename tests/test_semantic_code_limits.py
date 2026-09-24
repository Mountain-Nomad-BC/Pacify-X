from __future__ import annotations

import math

import pytest

from runtime.semantic_code_limits import BudgetExceeded, SemanticCodeLimits, enforce_count


def test_limits_reject_bool_and_invalid_duration():
    with pytest.raises(ValueError):
        SemanticCodeLimits(max_files=True)
    with pytest.raises(ValueError):
        SemanticCodeLimits(max_duration_seconds=0)
    with pytest.raises(ValueError):
        SemanticCodeLimits(max_duration_seconds=True)
    with pytest.raises(ValueError):
        SemanticCodeLimits(max_duration_seconds=math.nan)
    with pytest.raises(ValueError):
        SemanticCodeLimits(max_duration_seconds=math.inf)


def test_count_budget_is_explicit():
    with pytest.raises(BudgetExceeded) as error:
        enforce_count("too_many", 3, 2)
    assert error.value.code == "too_many"
