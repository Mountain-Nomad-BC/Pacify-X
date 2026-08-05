from __future__ import annotations
from typing import Any


def dominates(
    left: dict[str, float], right: dict[str, float], directions: dict[str, str]
) -> bool:
    no_worse = True
    strictly_better = False
    for metric, direction in directions.items():
        lv, rv = float(left[metric]), float(right[metric])
        if direction == "maximize":
            no_worse &= lv >= rv
            strictly_better |= lv > rv
        else:
            no_worse &= lv <= rv
            strictly_better |= lv < rv
    return bool(no_worse and strictly_better)


def pareto_front(
    candidates: list[dict[str, Any]], directions: dict[str, str]
) -> list[dict[str, Any]]:
    front = []
    for candidate in candidates:
        if not any(
            dominates(other["metrics"], candidate["metrics"], directions)
            for other in candidates
            if other is not candidate
        ):
            front.append(candidate)
    return sorted(front, key=lambda x: str(x.get("id")))


def evaluate(experiment: dict[str, Any]) -> dict[str, Any]:
    baseline = experiment["baseline"]
    candidates = experiment.get("candidates", [])
    directions = experiment.get("directions", {})
    thresholds = experiment.get("hard_thresholds", {})
    results = []
    for candidate in candidates:
        failures = []
        for metric, threshold in thresholds.items():
            value = float(candidate["metrics"][metric])
            direction = directions.get(metric, "maximize")
            if direction == "maximize" and value < float(threshold):
                failures.append(metric)
            if direction == "minimize" and value > float(threshold):
                failures.append(metric)
        regressions = []
        for metric, direction in directions.items():
            cv = float(candidate["metrics"][metric])
            bv = float(baseline["metrics"][metric])
            tolerance = float(
                experiment.get("regression_tolerance", {}).get(metric, 0.0)
            )
            if direction == "maximize" and cv + tolerance < bv:
                regressions.append(metric)
            elif direction == "minimize" and cv - tolerance > bv:
                regressions.append(metric)
        utility = 0.0
        for metric, weight in experiment.get("utility_weights", {}).items():
            cv = float(candidate["metrics"][metric])
            utility += float(weight) * (
                cv if directions.get(metric) == "maximize" else -cv
            )
        results.append(
            {
                "id": candidate["id"],
                "metrics": candidate["metrics"],
                "threshold_failures": failures,
                "regressions": regressions,
                "eligible": not failures and not regressions,
                "utility": round(utility, 8),
            }
        )
    eligible = [r for r in results if r["eligible"]]
    pareto = pareto_front(eligible, directions) if eligible else []
    selected = max(pareto, key=lambda x: x["utility"], default=None)
    return {
        "experiment_id": experiment.get("id"),
        "baseline": baseline,
        "candidate_results": results,
        "pareto_front": [x["id"] for x in pareto],
        "selected": selected["id"] if selected else None,
        "disposition": "promote_candidate" if selected else "retain_baseline",
        "rollback_required_on_failure": True,
        "promotion_requires_independent_validation": True,
    }
