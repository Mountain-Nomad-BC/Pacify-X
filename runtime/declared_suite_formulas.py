"""Auditable formulas reconstructed from declared suite identifiers."""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return numerator / denominator


def canary_quality_delta(canary: float, baseline: float) -> float:
    return canary - baseline


def certification_coverage(verified: int, required: int) -> float:
    return _ratio(verified, required)


def confidence_combination_independent(confidences: Iterable[float]) -> float:
    values = list(confidences)
    if not values or any(value < 0 or value > 1 for value in values):
        raise ValueError("confidences must be a nonempty sequence in [0, 1]")
    return 1.0 - math.prod(1.0 - value for value in values)


def context_utility_density(utilities: Iterable[float], token_count: int) -> float:
    return _ratio(sum(utilities), token_count)


def expected_plan_utility(outcomes: Iterable[Mapping[str, float]], cost: float = 0.0) -> float:
    rows = list(outcomes)
    probability = sum(float(row["probability"]) for row in rows)
    if not rows or abs(probability - 1.0) > 1e-9:
        raise ValueError("outcome probabilities must sum to one")
    return sum(float(row["probability"]) * float(row["utility"]) for row in rows) - cost


def impact_risk_score(likelihood: float, severity: float, exposure: float = 1.0, confidence: float = 1.0) -> float:
    if any(value < 0 for value in (likelihood, severity, exposure, confidence)):
        raise ValueError("risk factors cannot be negative")
    return likelihood * severity * exposure * confidence


def jaccard_change_overlap(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def kv_cache_bytes(layers: int, tokens: int, kv_heads: int, head_dim: int, bytes_per_element: float, batch: int = 1) -> float:
    values = (layers, tokens, kv_heads, head_dim, bytes_per_element, batch)
    if any(value <= 0 for value in values):
        raise ValueError("cache dimensions must be positive")
    return 2 * layers * tokens * kv_heads * head_dim * bytes_per_element * batch


def little_law_serving(arrival_rate: float, mean_latency: float) -> float:
    if arrival_rate < 0 or mean_latency < 0:
        raise ValueError("arrival rate and latency cannot be negative")
    return arrival_rate * mean_latency


def mutation_score(killed: int, total_non_equivalent: int) -> float:
    if killed < 0 or killed > total_non_equivalent:
        raise ValueError("killed mutants must be within the total")
    return _ratio(killed, total_non_equivalent)


def population_stability_index(expected: Sequence[float], actual: Sequence[float], epsilon: float = 1e-9) -> float:
    if len(expected) != len(actual) or not expected:
        raise ValueError("expected and actual distributions must have equal nonzero length")
    if abs(sum(expected) - 1.0) > 1e-6 or abs(sum(actual) - 1.0) > 1e-6:
        raise ValueError("distributions must sum to one")
    return sum((a - e) * math.log(max(a, epsilon) / max(e, epsilon)) for e, a in zip(expected, actual))


def precision_recall_f1(true_positive: int, false_positive: int, false_negative: int) -> dict[str, float]:
    if min(true_positive, false_positive, false_negative) < 0:
        raise ValueError("confusion counts cannot be negative")
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> list[dict[str, float]]:
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, 1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + rank)
    return [{"id": identifier, "score": score} for identifier, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def relative_performance_change(candidate: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("baseline cannot be zero")
    return (candidate - baseline) / abs(baseline)


def reproducibility_rate(reproduced: int, attempts: int) -> float:
    if reproduced < 0 or reproduced > attempts:
        raise ValueError("reproduced count must be within attempts")
    return _ratio(reproduced, attempts)


def risk_priority(severity: float, occurrence: float, detectability: float) -> float:
    if min(severity, occurrence, detectability) < 0:
        raise ValueError("risk factors cannot be negative")
    return severity * occurrence * detectability


def semantic_overlap_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    return jaccard_change_overlap(left, right)


def weighted_source_quality(signals: Iterable[Mapping[str, float]]) -> float:
    rows = list(signals)
    total_weight = sum(float(row["weight"]) for row in rows)
    if total_weight <= 0:
        raise ValueError("total source weight must be positive")
    if any(not 0 <= float(row["quality"]) <= 1 or float(row["weight"]) < 0 for row in rows):
        raise ValueError("quality must be in [0, 1] and weights cannot be negative")
    return sum(float(row["quality"]) * float(row["weight"]) for row in rows) / total_weight


FORMULAS = {
    "canary-quality-delta": canary_quality_delta,
    "certification-coverage": certification_coverage,
    "confidence-combination-independent": confidence_combination_independent,
    "context-utility-density": context_utility_density,
    "expected-plan-utility": expected_plan_utility,
    "impact-risk-score": impact_risk_score,
    "jaccard-change-overlap": jaccard_change_overlap,
    "kv-cache-bytes": kv_cache_bytes,
    "little-law-serving": little_law_serving,
    "mutation-score": mutation_score,
    "population-stability-index": population_stability_index,
    "precision-recall-f1": precision_recall_f1,
    "reciprocal-rank-fusion": reciprocal_rank_fusion,
    "relative-performance-change": relative_performance_change,
    "reproducibility-rate": reproducibility_rate,
    "risk-priority": risk_priority,
    "semantic-overlap-jaccard": semantic_overlap_jaccard,
    "weighted-source-quality": weighted_source_quality,
}


def validate_formula_registry(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate the canonical formula-registry envelope and implementation set."""
    errors: list[str] = []
    required = {"schema_version", "source", "formula_count", "formulas"}
    unexpected = set(payload) - required
    missing = required - set(payload)
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if unexpected:
        errors.append(f"unexpected fields: {sorted(unexpected)}")
    formulas = payload.get("formulas")
    if not isinstance(formulas, list):
        errors.append("formulas must be a list")
        formulas = []
    count = payload.get("formula_count")
    if isinstance(count, bool) or not isinstance(count, int):
        errors.append("formula_count must be an integer")
    elif count != len(formulas):
        errors.append(f"formula_count={count} does not match formulas={len(formulas)}")
    identifiers = [str(item.get("id", "")) for item in formulas if isinstance(item, Mapping)]
    if len(identifiers) != len(formulas) or any(not identifier for identifier in identifiers):
        errors.append("every formula must have a nonempty ID")
    if len(identifiers) != len(set(identifiers)):
        errors.append("duplicate formula IDs")
    missing_implementations = sorted(set(identifiers) - set(FORMULAS))
    unregistered_implementations = sorted(set(FORMULAS) - set(identifiers))
    if missing_implementations:
        errors.append(f"missing formula implementations: {missing_implementations}")
    if unregistered_implementations:
        errors.append(f"unregistered formula implementations: {unregistered_implementations}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "formula_count": len(formulas),
        "implementation_count": len(FORMULAS),
        "errors": errors,
    }
