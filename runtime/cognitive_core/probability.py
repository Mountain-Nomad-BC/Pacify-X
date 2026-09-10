"""Evidence-aware probabilistic reasoning with explicit dependence safeguards."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .common import entropy, ensure_probability, stable_hash
from ..numeric_inputs import (
    analysis_payload,
    bounded_integer,
    bounded_mapping,
    bounded_sequence,
    bounded_text,
    bounded_json_value,
    finite_number,
)

_EPS = 1e-12


def _normalize(values: Mapping[str, float]) -> dict[str, float]:
    values = bounded_mapping(values, "probability mass", maximum=256)
    numeric = {
        key: finite_number(value, "probability mass", minimum=0)
        for key, value in values.items()
    }
    scale = max(numeric.values(), default=0)
    if scale <= 0:
        raise ValueError("probability mass must be positive")
    numeric = {key: value / scale for key, value in numeric.items()}
    total = math.fsum(numeric.values())
    return {key: value / total for key, value in numeric.items()}


def bayesian_portfolio(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = analysis_payload(payload)
    hypotheses = bounded_sequence(
        payload.get("hypotheses", []), "hypotheses", maximum=256, minimum=1
    )
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
        identifier = bounded_text(item.get("id"), "hypothesis identity")
        if not identifier:
            raise ValueError("hypothesis IDs must be non-empty")
        parsed.append((identifier, ensure_probability(item.get("prior", 0.0), "prior")))
    identifiers = [identifier for identifier, _ in parsed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("hypothesis IDs must be unique")

    priors = _normalize(dict(parsed))
    log_scores = {
        key: (-math.inf if value == 0.0 else math.log(value))
        for key, value in priors.items()
    }
    evidence_rows = bounded_sequence(
        payload.get("evidence", []), "evidence", maximum=1024
    )
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
        evidence_id = bounded_text(
            evidence.get("id", f"evidence:{index}"), "evidence identity"
        )
        if not evidence_id or evidence_id in seen_evidence_ids:
            raise ValueError("evidence IDs must be unique and non-empty")
        seen_evidence_ids.add(evidence_id)
        group = bounded_text(
            evidence.get("dependence_group", evidence_id), "dependence group"
        )
        if not group:
            raise ValueError(f"{evidence_id}: dependence_group must be non-empty")
        dependence_counts[group] += 1
        default_damping = 1.0 / math.sqrt(dependence_counts[group])
        damping = finite_number(
            evidence.get("dependence_weight", default_damping), "dependence weight"
        )
        if not math.isfinite(damping) or not 0.0 < damping <= 1.0:
            raise ValueError("dependence_weight must be finite and in (0, 1]")
        likelihoods_raw = bounded_mapping(
            evidence.get("likelihoods", {}), "likelihoods", maximum=256
        )
        if not isinstance(likelihoods_raw, Mapping):
            raise ValueError(f"{evidence_id}: likelihoods must be an object")
        likelihoods = {}
        for key, value in likelihoods_raw.items():
            key = bounded_text(key, "likelihood identity")
            if key in likelihoods:
                raise ValueError("duplicate canonical likelihood identity")
            likelihoods[key] = ensure_probability(value, f"{evidence_id} likelihood")
        missing = sorted(set(priors) - set(likelihoods))
        extra = sorted(set(likelihoods) - set(priors))
        if missing or extra:
            raise ValueError(
                f"{evidence_id}: likelihood signature mismatch; missing={missing}, extra={extra}"
            )
        for hypothesis_id in priors:
            likelihood = ensure_probability(
                likelihoods[hypothesis_id], f"{evidence_id} likelihood"
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
    bounded_json_value(result)
    return {**result, "result_sha256": stable_hash(result)}


def expected_value_of_information(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rank tests by expected decision improvement minus declared cost and risk."""
    payload = analysis_payload(payload)
    baseline = finite_number(
        payload["baseline_expected_utility"], "baseline_expected_utility"
    )
    if not math.isfinite(baseline):
        raise ValueError("baseline_expected_utility must be finite")
    ranked = []
    seen: set[str] = set()
    for test in bounded_sequence(payload.get("tests", []), "tests", maximum=256):
        if not isinstance(test, Mapping):
            raise ValueError("each test must be an object")
        identifier = bounded_text(test.get("id"), "test identity")
        if not identifier or identifier in seen:
            raise ValueError("test IDs must be unique and non-empty")
        seen.add(identifier)
        outcomes = bounded_sequence(
            test.get("outcomes", []), "outcomes", maximum=256, minimum=1
        )
        for item in outcomes:
            bounded_mapping(item, "test outcome", maximum=16)
        if (
            not isinstance(outcomes, Sequence)
            or isinstance(outcomes, (str, bytes))
            or not outcomes
        ):
            raise ValueError(f"test {identifier}: outcomes must be a non-empty list")
        probabilities = [
            ensure_probability(item["probability"], f"test {identifier} probability")
            for item in outcomes
        ]
        probability_sum = sum(probabilities)
        if abs(probability_sum - 1.0) > 1e-9:
            raise ValueError(
                f"test {identifier}: outcome probabilities must sum to one"
            )
        utilities = [
            finite_number(item["best_expected_utility"], "outcome utility")
            for item in outcomes
        ]
        if any(not math.isfinite(value) for value in utilities):
            raise ValueError(f"test {identifier}: utilities must be finite")
        cost = finite_number(test.get("cost", 0.0), "test cost", minimum=0)
        risk_cost = finite_number(
            test.get("risk_cost", 0.0), "test risk cost", minimum=0
        )
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
        expected_after = finite_number(expected_after, "expected utility after test")
        raw_value = finite_number(expected_after - baseline, "information value")
        net_value = finite_number(raw_value - cost - risk_cost, "net information value")
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
    bounded_json_value(result)
    return {**result, "result_sha256": stable_hash(result)}


def calibration_metrics(
    predictions: Sequence[float], outcomes: Sequence[int], *, bins: int = 10
) -> dict[str, float]:
    predictions = bounded_sequence(
        predictions, "predictions", maximum=100000, minimum=1
    )
    outcomes = bounded_sequence(outcomes, "outcomes", maximum=100000, minimum=1)
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes must be equal non-empty sequences")
    bins = bounded_integer(bins, "bins", minimum=2, maximum=1000)
    if any(type(value) is not int or value not in (0, 1) for value in outcomes):
        raise ValueError("outcomes must be actual binary integers")
    ps = [ensure_probability(value, "prediction") for value in predictions]
    ys = outcomes
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)
    log_loss = -sum(
        y * math.log(max(p, _EPS)) + (1 - y) * math.log(max(1 - p, _EPS))
        for p, y in zip(ps, ys)
    ) / len(ps)
    counts = [0] * bins
    confidence_sums = [0.0] * bins
    corrections = [0.0] * bins
    outcome_sums = [0] * bins
    for prediction, outcome in zip(ps, ys):
        bucket = min(bins - 1, int(prediction * bins))
        # Correct a possible multiply-rounding error against the original
        # division-defined interval boundaries (e.g. 0.58 with 100 bins).
        if bucket and prediction < bucket / bins:
            bucket -= 1
        elif bucket < bins - 1 and prediction >= (bucket + 1) / bins:
            bucket += 1
        counts[bucket] += 1
        adjusted = prediction - corrections[bucket]
        combined = confidence_sums[bucket] + adjusted
        corrections[bucket] = (combined - confidence_sums[bucket]) - adjusted
        confidence_sums[bucket] = combined
        outcome_sums[bucket] += outcome
    ece = math.fsum(
        count
        / len(ps)
        * abs(confidence_sums[index] / count - outcome_sums[index] / count)
        for index, count in enumerate(counts)
        if count
    )
    return {
        "brier_score": brier,
        "log_loss": log_loss,
        "expected_calibration_error": ece,
    }
