"""Read-only facade joining the expansion's deterministic reasoning operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from .abduction import rank_explanations
from .analogy import compare as compare_analogy
from .causal import analyze as analyze_causal
from .constraint import solve as solve_constraints
from .decision import choose as choose_decision
from .formula_engine import compare_formulas, evaluate_formula
from .knowledge import project as project_knowledge
from .logic import reason as reason_logic
from .probability import bayesian_portfolio, expected_value_of_information
from .strategy import select as select_strategy
from .temporal import analyze as analyze_temporal
from .common import stable_hash

_OPERATIONS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "reason-logic": reason_logic,
    "solve-constraints": solve_constraints,
    "rank-abductive-explanations": rank_explanations,
    "update-hypotheses": bayesian_portfolio,
    "rank-tests-by-voi": expected_value_of_information,
    "analyze-causal-graph": analyze_causal,
    "analyze-temporal-state": analyze_temporal,
    "compare-structural-analogy": compare_analogy,
    "choose-under-tradeoffs": choose_decision,
    "project-belief-ledger": project_knowledge,
    "evaluate-formula": evaluate_formula,
    "compare-formulas": compare_formulas,
    "select-reasoning-strategy": select_strategy,
}


def run_cognitive_operation(
    operation: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    function = _OPERATIONS.get(str(operation))
    if function is None:
        return {
            "valid": False,
            "errors": [f"unknown cognitive operation: {operation}"],
            "available": sorted(_OPERATIONS),
        }
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["payload must be an object"]}
    try:
        result = function(payload)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as error:
        return {
            "valid": False,
            "operation": operation,
            "errors": [str(error)],
            "input_sha256": stable_hash(payload),
        }
    return {
        "valid": bool(result.get("valid", True)),
        "operation": operation,
        "read_only": True,
        "result": result,
        "input_sha256": stable_hash(payload),
        "result_sha256": stable_hash(result),
    }


def integration_healthcheck() -> dict[str, Any]:
    checks = {
        "logic": run_cognitive_operation(
            "reason-logic",
            {
                "facts": [{"predicate": "powered", "arguments": ["bank-1"]}],
                "rules": [
                    {
                        "id": "r1",
                        "premises": [{"predicate": "powered", "arguments": ["bank-1"]}],
                        "conclusion": {
                            "predicate": "may-heat",
                            "arguments": ["bank-1"],
                        },
                    }
                ],
                "queries": [{"predicate": "may-heat", "arguments": ["bank-1"]}],
            },
        ),
        "probability": run_cognitive_operation(
            "update-hypotheses",
            {
                "hypotheses": [
                    {"id": "element", "prior": 0.5},
                    {"id": "contactor", "prior": 0.5},
                ],
                "evidence": [
                    {
                        "id": "voltage-present",
                        "likelihoods": {"element": 0.9, "contactor": 0.2},
                    }
                ],
            },
        ),
        "constraint": run_cognitive_operation(
            "solve-constraints",
            {
                "variables": {"voltage": [208, 240], "element": ["on", "off"]},
                "constraints": [
                    {"type": "eq", "left": {"var": "voltage"}, "right": {"value": 240}}
                ],
                "max_solutions": 4,
            },
        ),
    }
    return {
        "valid": all(item["valid"] for item in checks.values()),
        "operations": sorted(_OPERATIONS),
        "operation_count": len(_OPERATIONS),
        "checks": {key: value["valid"] for key, value in checks.items()},
        "read_only": True,
    }
