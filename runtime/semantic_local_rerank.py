"""Attach bounded local-model relevance scores before canonical PX ranking.

The input must already be a small candidate set selected by deterministic/canonical PX
retrieval logic.  This module only attaches one optional relevance signal; it never
becomes a ranking, visibility, or authority owner.
"""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Callable

from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import SemanticEvidence

ScoreFunction = Callable[[str, SemanticEvidence], float]


def attach_local_relevance_scores(
    query: str,
    evidence: tuple[SemanticEvidence, ...],
    scorer: ScoreFunction,
    *,
    max_candidates: int | None = None,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> tuple[SemanticEvidence, ...]:
    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > limits.max_query_bytes:
        raise ValueError("query must be nonempty and bounded")
    if type(evidence) is not tuple:
        raise TypeError("rerank evidence must be a tuple")
    if not callable(scorer):
        raise TypeError("scorer must be callable")
    candidate_limit = limits.max_results if max_candidates is None else max_candidates
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= limits.max_results:
        raise ValueError("max_candidates must be a positive integer within max_results")
    if len(evidence) > candidate_limit:
        raise ValueError("local rerank candidate budget exceeded")

    result: list[SemanticEvidence] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, SemanticEvidence):
            raise TypeError("rerank candidates must be SemanticEvidence objects")
        if item.source_id in seen:
            raise ValueError("rerank candidate source_id values must be unique")
        seen.add(item.source_id)
        raw = scorer(query, item)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("local relevance score must be numeric")
        score = float(raw)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("local relevance score must be finite and between 0 and 1")
        result.append(replace(item, dense_score=score))
    return tuple(result)
