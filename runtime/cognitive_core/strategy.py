"""Reasoning-strategy selection based on explicit problem characteristics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import token_set, stable_hash


_MODE_SIGNALS = {
    "deductive": {"must", "constraint", "rule", "prove", "guarantee", "invariant"},
    "abductive": {"diagnose", "cause", "failure", "symptom", "explain", "hypothesis"},
    "bayesian": {
        "probability",
        "likelihood",
        "uncertain",
        "confidence",
        "evidence",
        "prior",
    },
    "causal": {
        "cause",
        "intervention",
        "counterfactual",
        "confounder",
        "effect",
        "why",
    },
    "constraint": {
        "limit",
        "requirement",
        "compatible",
        "valid",
        "allowed",
        "configuration",
    },
    "temporal": {"before", "after", "during", "sequence", "timeline", "state", "event"},
    "formula": {
        "calculate",
        "formula",
        "equation",
        "units",
        "dimension",
        "sensitivity",
    },
    "graph": {"dependency", "relationship", "connected", "path", "impact", "graph"},
    "analogical": {"similar", "analogy", "transfer", "pattern", "like", "compare"},
    "retrieval": {"find", "search", "retrieve", "document", "source", "lookup"},
}

_DEPENDENCIES = {
    "bayesian": ("evidence",),
    "causal": ("graph", "evidence"),
    "abductive": ("evidence", "constraint"),
    "formula": ("constraint",),
    "analogical": ("graph",),
}


def select(payload: Mapping[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        raise ValueError("goal is required")
    terms = token_set(goal)
    characteristics = {str(item) for item in payload.get("characteristics", ())}
    terms |= characteristics
    ranked = []
    for mode, signals in _MODE_SIGNALS.items():
        matched = sorted(terms & signals)
        score = len(matched)
        if mode in set(payload.get("required_modes", ())):
            score += 100
            matched.append("required_by_caller")
        if score:
            ranked.append({"mode": mode, "score": score, "matched_signals": matched})
    ranked.sort(key=lambda item: (-item["score"], item["mode"]))
    max_modes = max(1, int(payload.get("max_modes", 4)))
    selected = ranked[:max_modes]
    steps = []
    seen = set()

    def add(mode: str, reason: str) -> None:
        for dependency in _DEPENDENCIES.get(mode, ()):
            if dependency not in seen:
                add(dependency, f"required by {mode}")
        if mode not in seen:
            seen.add(mode)
            steps.append({"mode": mode, "reason": reason})

    for item in selected:
        add(item["mode"], "matched task signals")
    stop_conditions = [
        "declared postconditions are satisfied",
        "new evidence no longer changes the decision materially",
        "remaining uncertainty exceeds authority and requires abstention or escalation",
        "reasoning or tool budget is exhausted",
    ]
    result = {
        "valid": bool(steps),
        "goal": goal,
        "ranked_modes": ranked,
        "plan": steps,
        "stop_conditions": stop_conditions,
        "unmatched": not bool(steps),
    }
    return {**result, "result_sha256": stable_hash(result)}
