"""Evidence-aware probabilistic reasoning with explicit dependence safeguards."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .common import entropy, ensure_probability, stable_hash

_EPS = 1e-12


def _normalize(values: Mapping[str, float]) -> dict[str, float]:
    numeric = {str(key): float(value) for key, value in values.items()}
    if any(not math.isfinite(value) or value < 0.0 for value in numeric.values()):
        raise ValueError("probability mass must be finite and nonnegative")
    total = sum(numeric.values())
    if total <= 0:
        raise ValueError("probability mass must be positive")
    return {key: value / total for key, value in numeric.items()}


def bayesian_portfolio(payload: Mapping[str, Any]) -> dict[str, Any]:
    hypotheses = payload.get("hypotheses", ())
    if (
        not isinstance(hypotheses, Sequence)
        or isinstance(hypotheses, (str, bytes))
        or not hypotheses
    ):
        raise ValueError("hypotheses must be a non-empty list")
    parsed: list[tuple[str, float]] = []
    for item in hypotheses:
        if not isinstance(item, Mapping):
            raise ValueError("each hypothesis must be an object")
        identifier = str(item.get("id", "")).strip()
        if not identifier:
            raise ValueError("hypothesis IDs must be non-empty")
        parsed.append(
            (identifier, ensure_probability(float(item.get("prior", 0.0)), "prior"))
        )
    identifiers = [identifier for identifier, _ in parsed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("hypothesis IDs must be unique")

    priors = _normalize(dict(parsed))
    log_scores = {
        key: (-math.inf if value == 0.0 else math.log(value))
        for key, value in priors.items()
    }
    evidence_rows = payload.get("evidence", ())
    if not isinstance(evidence_rows, Sequence) or isinstance(
        evidence_rows, (str, bytes)
    ):
        raise ValueError("evidence must be a list")
    dependence_counts: Counter[str] = Counter()
    update_trace: list[dict[str, Any]] = []
    seen_evidence_ids: set[str] = set()
    for index, evidence in enumerate(evidence_rows):
        if not isinstance(evidence, Mapping):
            raise ValueError("each evidence item must be an object")
        evidence_id = str(evidence.get("id", f"evidence:{index}")).strip()
        if not evidence_id or evidence_id in seen_evidence_ids:
            raise ValueError("evidence IDs must be unique and non-empty")
        seen_evidence_ids.add(evidence_id)
        group = str(evidence.get("dependence_group", evidence_id)).strip()
        if not group:
            raise ValueError(f"{evidence_id}: dependence_group must be non-empty")
        dependence_counts[group] += 1
        default_damping = 1.0 / math.sqrt(dependence_counts[group])
        damping = float(evidence.get("dependence_weight", default_damping))
        if not math.isfinite(damping) or not 0.0 < damping <= 1.0:
            raise ValueError("dependence_weight must be finite and in (0, 1]")
        likelihoods_raw = evidence.get("likelihoods", {})
        if not isinstance(likelihoods_raw, Mapping):
            raise ValueError(f"{evidence_id}: likelihoods must be an object")
        likelihoods = {str(key): value for key, value in likelihoods_raw.items()}
        missing = sorted(set(priors) - set(likelihoods))
        extra = sorted(set(likelihoods) - set(priors))
        if missing or extra:
            raise ValueError(
                f"{evidence_id}: likelihood signature mismatch; missing={missing}, extra={extra}"
            )
        for hypothesis_id in priors:
            likelihood = ensure_probability(
                float(likelihoods[hypothesis_id]), f"{evidence_id} likelihood"
            )
            if log_scores[hypothesis_id] == -math.inf or likelihood == 0.0:
                log_scores[hypothesis_id] = -math.inf
            else:
                log_scores[hypothesis_id] += damping * math.log(likelihood)
        finite_scores = [value for value in log_scores.values() if math.isfinite(value)]
        if not finite_scores:
            raise ValueError(
                f"{evidence_id}: evidence has zero likelihood under every live hypothesis"
            )
        maximum = max(finite_scores)
        current = _normalize(
            {
                key: (0.0 if value == -math.inf else math.exp(value - maximum))
                for key, value in log_scores.items()
            }
        )
        update_trace.append(
            {
                "evidence_id": evidence_id,
                "dependence_group": group,
                "effective_weight": round(damping, 8),
                "posterior": {
                    key: round(value, 12) for key, value in sorted(current.items())
                },
            }
        )
    finite_scores = [value for value in log_scores.values() if math.isfinite(value)]
    maximum = max(finite_scores)
    posteriors = _normalize(
        {
            key: (0.0 if value == -math.inf else math.exp(value - maximum))
            for key, value in log_scores.items()
        }
    )
    prior_entropy = entropy(priors.values())
    posterior_entropy = entropy(posteriors.values())
    entropy_change = prior_entropy - posterior_entropy
    ranked = sorted(posteriors.items(), key=lambda item: (-item[1], item[0]))
    result = {
        "valid": True,
        "hypotheses": [
            {"id": key, "prior": priors[key], "posterior": probability, "rank": rank}
            for rank, (key, probability) in enumerate(ranked, 1)
        ],
        "prior_entropy_bits": prior_entropy,
        "posterior_entropy_bits": posterior_entropy,
        "entropy_reduction_bits": entropy_change,
        "uncertainty_increased": entropy_change < 0.0,
        "updates": update_trace,
        "dependence_groups": dict(sorted(dependence_counts.items())),
        "dependence_policy": "caller-declared groups with default nth-item weight 1/sqrt(n)",
        "warning": "Likelihoods and dependence declarations must be defensible; damping is a conservative heuristic, not a learned joint likelihood model.",
    }
    return {**result, "result_sha256": stable_hash(result)}


def expected_value_of_information(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rank tests by expected decision improvement minus declared cost and risk."""
    baseline = float(payload["baseline_expected_utility"])
    if not math.isfinite(baseline):
        raise ValueError("baseline_expected_utility must be finite")
    ranked = []
    seen: set[str] = set()
    for test in payload.get("tests", ()):
        if not isinstance(test, Mapping):
            raise ValueError("each test must be an object")
        identifier = str(test.get("id", "")).strip()
        if not identifier or identifier in seen:
            raise ValueError("test IDs must be unique and non-empty")
        seen.add(identifier)
        outcomes = test.get("outcomes", ())
        if (
            not isinstance(outcomes, Sequence)
            or isinstance(outcomes, (str, bytes))
            or not outcomes
        ):
            raise ValueError(f"test {identifier}: outcomes must be a non-empty list")
        probabilities = [
            ensure_probability(
                float(item["probability"]), f"test {identifier} probability"
            )
            for item in outcomes
        ]
        probability_sum = sum(probabilities)
        if abs(probability_sum - 1.0) > 1e-9:
            raise ValueError(
                f"test {identifier}: outcome probabilities must sum to one"
            )
        utilities = [float(item["best_expected_utility"]) for item in outcomes]
        if any(not math.isfinite(value) for value in utilities):
            raise ValueError(f"test {identifier}: utilities must be finite")
        cost = float(test.get("cost", 0.0))
        risk_cost = float(test.get("risk_cost", 0.0))
        if (
            not math.isfinite(cost)
            or not math.isfinite(risk_cost)
            or cost < 0.0
            or risk_cost < 0.0
        ):
            raise ValueError(f"test {identifier}: costs must be finite and nonnegative")
        expected_after = sum(
            probability * utility
            for probability, utility in zip(probabilities, utilities)
        )
        raw_value = expected_after - baseline
        net_value = raw_value - cost - risk_cost
        ranked.append(
            {
                "id": identifier,
                "expected_utility_after": expected_after,
                "value_of_information": raw_value,
                "cost": cost,
                "risk_cost": risk_cost,
                "net_value_of_information": net_value,
                "recommended": net_value > 0,
            }
        )
    ranked.sort(key=lambda item: (-item["net_value_of_information"], item["id"]))
    result = {
        "valid": True,
        "baseline_expected_utility": baseline,
        "tests": ranked,
        "selected": ranked[0]["id"] if ranked and ranked[0]["recommended"] else None,
    }
    return {**result, "result_sha256": stable_hash(result)}


def calibration_metrics(
    predictions: Sequence[float], outcomes: Sequence[int], *, bins: int = 10
) -> dict[str, float]:
    if len(predictions) != len(outcomes) or not predictions:
        raise ValueError("predictions and outcomes must be equal non-empty sequences")
    if bins < 2:
        raise ValueError("bins must be at least two")
    ps = [ensure_probability(float(value), "prediction") for value in predictions]
    ys = [int(value) for value in outcomes]
    if any(value not in {0, 1} for value in ys):
        raise ValueError("outcomes must be binary")
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)
    log_loss = -sum(
        y * math.log(max(p, _EPS)) + (1 - y) * math.log(max(1 - p, _EPS))
        for p, y in zip(ps, ys)
    ) / len(ps)
    ece = 0.0
    for bucket in range(bins):
        low, high = bucket / bins, (bucket + 1) / bins
        indexes = [
            index
            for index, value in enumerate(ps)
            if low <= value < high or (bucket == bins - 1 and value == 1.0)
        ]
        if indexes:
            confidence = sum(ps[index] for index in indexes) / len(indexes)
            accuracy = sum(ys[index] for index in indexes) / len(indexes)
            ece += len(indexes) / len(ps) * abs(confidence - accuracy)
    return {
        "brier_score": brier,
        "log_loss": log_loss,
        "expected_calibration_error": ece,
    }
