"""Bounded abductive portfolio generation for diagnostics and explanation search."""

from __future__ import annotations
from itertools import combinations
from heapq import nsmallest
import math
from collections.abc import Mapping
from typing import Any
from .common import ensure_probability, stable_hash
from ..numeric_inputs import (
    analysis_payload,
    bounded_integer,
    bounded_mapping,
    bounded_sequence,
    bounded_text,
    bounded_json_value,
    finite_number,
)

MAX_FRONTIER = 50000
MAX_FRONTIER_WORK = 5000000


def _names(value, name, maximum=128):
    values = tuple(
        bounded_text(item, name)
        for item in bounded_sequence(value, name, maximum=maximum)
    )
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    return values


def rank_explanations(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = analysis_payload(payload)
    observations = _names(payload.get("observations", []), "observations")
    if not observations:
        raise ValueError("observations are required and must be non-empty")
    observation_set = set(observations)
    hypotheses = bounded_sequence(
        payload.get("hypotheses", []), "hypotheses", maximum=24, minimum=1
    )
    max_size = bounded_integer(
        payload.get("max_combination_size", 4), "max_combination_size", maximum=24
    )
    max_size = min(max_size, len(hypotheses))
    max_candidates = bounded_integer(
        payload.get("max_candidates", 20), "max_candidates", maximum=200
    )
    frontier = sum(math.comb(len(hypotheses), size) for size in range(1, max_size + 1))
    if frontier > MAX_FRONTIER:
        raise ValueError("abductive enumeration exceeds its complete frontier budget")
    weights_raw = bounded_mapping(
        payload.get("observation_weights", {}), "observation_weights", maximum=128
    )
    weights = {}
    for key, value in weights_raw.items():
        key = bounded_text(key, "observation weight identity")
        if key in weights or key not in observation_set:
            raise ValueError("observation weights must have unique known identities")
        weights[key] = finite_number(value, "observation weight", minimum=0)
    weights = {name: weights.get(name, 1.0) for name in observations}
    scale = max(weights.values()) or 1.0
    weights = {name: value / scale for name, value in weights.items()}
    total_weight = math.fsum(weights.values()) or 1.0
    hypothesis_penalty = finite_number(
        payload.get("hypothesis_penalty", 0.08), "hypothesis_penalty", minimum=0
    )
    prediction_penalty_rate = finite_number(
        payload.get("unobserved_prediction_penalty", 0.03),
        "unobserved_prediction_penalty",
        minimum=0,
    )
    cost_scale = finite_number(payload.get("cost_scale", 1.0), "cost_scale", minimum=0)
    if cost_scale == 0:
        raise ValueError("cost_scale must be positive")
    by_id = {}
    for raw in hypotheses:
        item = bounded_mapping(raw, "hypothesis", maximum=32)
        identity = bounded_text(item.get("id"), "hypothesis identity")
        if identity in by_id:
            raise ValueError("hypothesis IDs must be unique and non-empty")
        prior = ensure_probability(item.get("prior", 0.5), f"{identity} prior")
        cost = finite_number(
            item.get("complexity_cost", 0.0), "complexity cost", minimum=0
        ) + finite_number(item.get("test_cost", 0.0), "test cost", minimum=0)
        by_id[identity] = {
            "requires": set(
                _names(item.get("requires", []), "required hypotheses", 24)
            ),
            "conflicts": set(
                _names(item.get("conflicts", []), "conflicting hypotheses", 24)
            ),
            "explains": set(_names(item.get("explains", []), "explained observations")),
            "predicts": set(_names(item.get("predicts", []), "predicted observations")),
            "log_prior": math.log(max(prior, 1e-12)),
            "cost": finite_number(cost, "combined hypothesis cost", minimum=0),
        }
    ids = list(by_id)
    for item in by_id.values():
        if (item["requires"] | item["conflicts"]) - set(ids):
            raise ValueError("hypothesis dependencies must reference known identities")
    max_members = max(
        sum(len(item[key]) for key in ("requires", "conflicts", "explains", "predicts"))
        for item in by_id.values()
    )
    if (
        frontier * (1 + len(observations) + max_size * (1 + max_members))
        > MAX_FRONTIER_WORK
    ):
        raise ValueError("abductive frontier exceeds its complete work budget")
    valid_candidates = 0

    def candidates():
        nonlocal valid_candidates
        for size in range(1, max_size + 1):
            for selected_tuple in combinations(ids, size):
                selected = set(selected_tuple)
                rows = [by_id[identity] for identity in selected_tuple]
                if any(
                    item["requires"] - selected or item["conflicts"] & selected
                    for item in rows
                ):
                    continue
                explained = (
                    set().union(*(item["explains"] for item in rows)) & observation_set
                )
                predicted = (
                    set().union(*(item["predicts"] for item in rows)) - observation_set
                )
                log_prior = sum(item["log_prior"] for item in rows)
                cost = finite_number(
                    sum(item["cost"] for item in rows),
                    "combined explanation cost",
                    minimum=0,
                )
                coverage = (
                    math.fsum(weights[item] for item in sorted(explained))
                    / total_weight
                )
                score = finite_number(
                    coverage
                    + 0.04 * log_prior
                    - hypothesis_penalty * max(0, size - 1)
                    - prediction_penalty_rate * len(predicted)
                    - cost / cost_scale,
                    "explanation score",
                )
                valid_candidates += 1
                yield {
                    "hypotheses": list(selected_tuple),
                    "score": score,
                    "coverage": coverage,
                    "explained": sorted(explained),
                    "unexplained": sorted(observation_set - explained),
                    "predicted_but_unobserved": sorted(predicted),
                    "combined_log_prior": log_prior,
                    "cost": cost,
                }

    ranked = nsmallest(
        max_candidates,
        candidates(),
        key=lambda item: (
            -item["score"],
            -item["coverage"],
            len(item["hypotheses"]),
            item["hypotheses"],
        ),
    )
    result = {
        "valid": True,
        "observations": list(observations),
        "candidates": ranked,
        "selected": ranked[0]["hypotheses"] if ranked else None,
        "residual_unknowns": ranked[0]["unexplained"] if ranked else list(observations),
        "frontier_evaluated": frontier,
        "valid_candidates": valid_candidates,
        "truncated": valid_candidates > max_candidates,
        "warning": "Abduction ranks explanations from declared coverage, priors, and costs; it does not establish causal truth.",
    }
    bounded_json_value(result)
    return {**result, "result_sha256": stable_hash(result)}
