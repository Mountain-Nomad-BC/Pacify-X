"""Auditable multi-objective decision support with interval uncertainty and regret bounds."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .common import stable_hash


def _interval(value: object) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        low = float(value.get("low", value.get("value")))
        high = float(value.get("high", value.get("value")))
        expected = float(value.get("expected", value.get("value", (low + high) / 2)))
    else:
        low = high = expected = float(value)
    if any(not math.isfinite(item) for item in (low, expected, high)):
        raise ValueError("metric intervals must be finite")
    if low > high or not low <= expected <= high:
        raise ValueError("metric interval must satisfy low <= expected <= high")
    return low, expected, high


def choose(payload: Mapping[str, Any]) -> dict[str, Any]:
    objectives = tuple(
        item for item in payload.get("objectives", ()) if isinstance(item, Mapping)
    )
    candidates = tuple(
        item for item in payload.get("candidates", ()) if isinstance(item, Mapping)
    )
    if not objectives or not candidates:
        raise ValueError("objectives and candidates are required")
    objective_ids = [str(item.get("id", "")) for item in objectives]
    if any(not value for value in objective_ids) or len(objective_ids) != len(
        set(objective_ids)
    ):
        raise ValueError("objective IDs must be unique and non-empty")
    directions = {
        str(item["id"]): str(item.get("direction", "maximize")) for item in objectives
    }
    if any(value not in {"maximize", "minimize"} for value in directions.values()):
        raise ValueError("objective direction must be maximize or minimize")
    candidate_ids = [str(item.get("id", "")) for item in candidates]
    if any(not value for value in candidate_ids) or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise ValueError("candidate IDs must be unique and non-empty")

    eligible: list[str] = []
    rejected: list[dict[str, Any]] = []
    parsed: dict[str, dict[str, tuple[float, float, float]]] = {}
    for candidate in candidates:
        identifier = str(candidate["id"])
        violations = [str(item) for item in candidate.get("constraint_violations", ())]
        metrics = candidate.get("metrics", {})
        if not isinstance(metrics, Mapping):
            violations.append("metrics must be an object")
            metrics = {}
        missing = sorted(set(objective_ids) - set(map(str, metrics)))
        if violations or missing:
            rejected.append(
                {"id": identifier, "violations": violations, "missing_metrics": missing}
            )
            continue
        parsed[identifier] = {
            objective_id: _interval(metrics[objective_id])
            for objective_id in objective_ids
        }
        eligible.append(identifier)
    if not eligible:
        return {
            "valid": True,
            "selected": None,
            "eligible": [],
            "rejected": rejected,
            "reason": "no feasible candidate",
        }

    ranges: dict[str, tuple[float, float]] = {}
    for objective in objectives:
        objective_id = str(objective["id"])
        values = [
            parsed[candidate_id][objective_id][index]
            for candidate_id in eligible
            for index in range(3)
        ]
        ranges[objective_id] = (min(values), max(values))
    weights = {
        str(item["id"]): max(0.0, float(item.get("weight", 1.0))) for item in objectives
    }
    if any(not math.isfinite(value) for value in weights.values()):
        raise ValueError("objective weights must be finite")
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        raise ValueError("at least one objective weight must be positive")
    weights = {key: value / weight_sum for key, value in weights.items()}

    rows: list[dict[str, Any]] = []
    expected_vectors: dict[str, tuple[float, ...]] = {}
    interval_vectors: dict[str, tuple[tuple[float, float], ...]] = {}
    for candidate_id in eligible:
        expected_utility = 0.0
        worst_utility = 0.0
        best_utility = 0.0
        expected_vector = []
        interval_vector = []
        normalized_metrics = {}
        for objective in objectives:
            objective_id = str(objective["id"])
            low, expected, high = parsed[candidate_id][objective_id]
            minimum, maximum = ranges[objective_id]
            span = maximum - minimum

            def normalize(value: float) -> float:
                base = 0.5 if span == 0 else (value - minimum) / span
                return base if directions[objective_id] == "maximize" else 1.0 - base

            normalized = (normalize(low), normalize(expected), normalize(high))
            worst, expected_normalized, best = (
                min(normalized),
                normalized[1],
                max(normalized),
            )
            expected_utility += weights[objective_id] * expected_normalized
            worst_utility += weights[objective_id] * worst
            best_utility += weights[objective_id] * best
            expected_vector.append(expected_normalized)
            interval_vector.append((worst, best))
            normalized_metrics[objective_id] = {
                "worst": worst,
                "expected": expected_normalized,
                "best": best,
            }
        expected_vectors[candidate_id] = tuple(expected_vector)
        interval_vectors[candidate_id] = tuple(interval_vector)
        rows.append(
            {
                "id": candidate_id,
                "expected_utility": expected_utility,
                "worst_case_utility": worst_utility,
                "best_case_utility": best_utility,
                "normalized_metrics": normalized_metrics,
            }
        )

    best_expected = max(row["expected_utility"] for row in rows)
    best_by_id = {row["id"]: row["best_case_utility"] for row in rows}
    worst_by_id = {row["id"]: row["worst_case_utility"] for row in rows}
    for row in rows:
        identifier = row["id"]
        competitor_best = max(
            (value for other, value in best_by_id.items() if other != identifier),
            default=row["best_case_utility"],
        )
        row["expected_regret"] = best_expected - row["expected_utility"]
        row["max_regret_bound"] = max(0.0, competitor_best - worst_by_id[identifier])
        row["pareto_dominated_expected"] = any(
            other != identifier
            and all(
                a >= b
                for a, b in zip(expected_vectors[other], expected_vectors[identifier])
            )
            and any(
                a > b
                for a, b in zip(expected_vectors[other], expected_vectors[identifier])
            )
            for other in eligible
        )
        row["robustly_dominated"] = any(
            other != identifier
            and all(
                other_worst >= this_best
                for (other_worst, _), (_, this_best) in zip(
                    interval_vectors[other], interval_vectors[identifier]
                )
            )
            and any(
                other_worst > this_best
                for (other_worst, _), (_, this_best) in zip(
                    interval_vectors[other], interval_vectors[identifier]
                )
            )
            for other in eligible
        )

    posture = str(payload.get("risk_posture", "expected"))
    if posture == "robust":
        rows.sort(
            key=lambda item: (
                -item["worst_case_utility"],
                item["max_regret_bound"],
                -item["expected_utility"],
                item["id"],
            )
        )
    elif posture == "minimax_regret":
        rows.sort(
            key=lambda item: (
                item["max_regret_bound"],
                -item["worst_case_utility"],
                -item["expected_utility"],
                item["id"],
            )
        )
    elif posture == "expected":
        rows.sort(
            key=lambda item: (
                -item["expected_utility"],
                -item["worst_case_utility"],
                item["id"],
            )
        )
    else:
        raise ValueError("risk_posture must be expected, robust, or minimax_regret")
    result = {
        "valid": True,
        "selected": rows[0]["id"],
        "risk_posture": posture,
        "eligible": rows,
        "rejected": rejected,
        "weights": weights,
        "regret_method": "independent interval upper bound: best competitor utility minus candidate worst utility",
        "warning": "Utility and regret bounds depend on declared objectives, scales, intervals, constraints, and unmodeled correlation.",
    }
    return {**result, "result_sha256": stable_hash(result)}
