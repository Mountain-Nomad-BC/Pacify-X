"""Bounded abductive portfolio generation for diagnostics and explanation search."""

from __future__ import annotations

from itertools import combinations
import math
from collections.abc import Mapping
from typing import Any

from .common import ensure_probability, stable_hash


def rank_explanations(payload: Mapping[str, Any]) -> dict[str, Any]:
    observations = tuple(str(item).strip() for item in payload.get("observations", ()))
    if not observations or any(not item for item in observations):
        raise ValueError("observations are required and must be non-empty")
    if len(observations) != len(set(observations)):
        raise ValueError("observations must be unique")
    observation_set = set(observations)
    hypotheses = tuple(
        item for item in payload.get("hypotheses", ()) if isinstance(item, Mapping)
    )
    if not hypotheses:
        raise ValueError("hypotheses are required")
    if len(hypotheses) > 24:
        raise ValueError("abductive enumeration is bounded to 24 hypotheses")
    ids = [str(item.get("id", "")).strip() for item in hypotheses]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("hypothesis IDs must be unique and non-empty")
    weights_raw = payload.get("observation_weights", {})
    if not isinstance(weights_raw, Mapping):
        raise ValueError("observation_weights must be an object")
    unknown_weights = sorted(set(map(str, weights_raw)) - observation_set)
    if unknown_weights:
        raise ValueError(f"weights reference unknown observations: {unknown_weights}")
    weights = {
        observation: float(weights_raw.get(observation, 1.0))
        for observation in observations
    }
    if any(not math.isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("observation weights must be finite and nonnegative")
    hypothesis_penalty = float(payload.get("hypothesis_penalty", 0.08))
    prediction_penalty_rate = float(payload.get("unobserved_prediction_penalty", 0.03))
    cost_scale = float(payload.get("cost_scale", 1.0))
    if (
        any(
            not math.isfinite(value) or value < 0
            for value in (hypothesis_penalty, prediction_penalty_rate)
        )
        or not math.isfinite(cost_scale)
        or cost_scale <= 0
    ):
        raise ValueError(
            "penalties must be finite and nonnegative; cost_scale must be positive"
        )
    max_size = max(1, min(int(payload.get("max_combination_size", 4)), len(hypotheses)))
    max_candidates = max(1, min(int(payload.get("max_candidates", 20)), 200))
    by_id = {str(item["id"]): item for item in hypotheses}
    candidates: list[dict[str, Any]] = []
    total_weight = sum(weights.values()) or 1.0

    for size in range(1, max_size + 1):
        for selected_tuple in combinations(ids, size):
            selected = set(selected_tuple)
            invalid_reasons: list[str] = []
            explained: set[str] = set()
            predicted_unobserved: set[str] = set()
            log_prior = 0.0
            cost = 0.0
            for hypothesis_id in selected_tuple:
                item = by_id[hypothesis_id]
                requires = set(map(str, item.get("requires", ())))
                conflicts = set(map(str, item.get("conflicts", ())))
                missing = requires - selected
                conflict = conflicts & selected
                if missing:
                    invalid_reasons.append(
                        f"{hypothesis_id} missing required hypotheses {sorted(missing)}"
                    )
                if conflict:
                    invalid_reasons.append(
                        f"{hypothesis_id} conflicts with {sorted(conflict)}"
                    )
                explains = set(map(str, item.get("explains", ())))
                predicts = set(map(str, item.get("predicts", ())))
                explained.update(explains & observation_set)
                predicted_unobserved.update(predicts - observation_set)
                prior = ensure_probability(
                    float(item.get("prior", 0.5)), f"{hypothesis_id} prior"
                )
                log_prior += math.log(max(prior, 1e-12))
                complexity_cost = float(item.get("complexity_cost", 0.0))
                test_cost = float(item.get("test_cost", 0.0))
                if any(
                    not math.isfinite(value) or value < 0
                    for value in (complexity_cost, test_cost)
                ):
                    raise ValueError(
                        f"{hypothesis_id}: costs must be finite and nonnegative"
                    )
                cost += complexity_cost + test_cost
            if invalid_reasons:
                continue
            covered_weight = sum(weights[item] for item in explained)
            coverage = covered_weight / total_weight
            unexplained = sorted(observation_set - explained)
            parsimony_penalty = hypothesis_penalty * max(0, size - 1)
            prediction_penalty = prediction_penalty_rate * len(predicted_unobserved)
            score = (
                coverage
                + 0.04 * log_prior
                - parsimony_penalty
                - prediction_penalty
                - cost / cost_scale
            )
            candidates.append(
                {
                    "hypotheses": list(selected_tuple),
                    "score": score,
                    "coverage": coverage,
                    "explained": sorted(explained),
                    "unexplained": unexplained,
                    "predicted_but_unobserved": sorted(predicted_unobserved),
                    "combined_log_prior": log_prior,
                    "cost": cost,
                }
            )
    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["coverage"],
            len(item["hypotheses"]),
            item["hypotheses"],
        )
    )
    candidates = candidates[:max_candidates]
    result = {
        "valid": True,
        "observations": list(observations),
        "candidates": candidates,
        "selected": candidates[0]["hypotheses"] if candidates else None,
        "residual_unknowns": candidates[0]["unexplained"]
        if candidates
        else list(observations),
        "warning": "Abduction ranks explanations from declared coverage, priors, and costs; it does not establish causal truth.",
    }
    return {**result, "result_sha256": stable_hash(result)}
