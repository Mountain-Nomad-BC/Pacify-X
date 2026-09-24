import math
import pytest

from runtime.semantic_integration_limits import SemanticIntegrationLimits
from runtime.semantic_integration_types import SemanticEvidence
from runtime.semantic_local_rerank import attach_local_relevance_scores
from runtime.semantic_retrieval_fusion import fuse_evidence


def item(source_id: str):
    return SemanticEvidence(source_id, "symbol", source_id, "same tokens", "p", "l", source_id)


def test_local_scores_feed_canonical_retrieval_without_becoming_rank_owner():
    items = (item("a"), item("b"))
    scored = attach_local_relevance_scores(
        "same", items, lambda q, candidate: 1.0 if candidate.source_id == "b" else 0.0
    )
    assert scored[1].dense_score == 1.0
    result = fuse_evidence("same", "p", scored, identity_scope=("project",))
    assert result.canonical_retrieval_owner == "runtime.retrieval.retrieve"


def test_rerank_rejects_nonfinite_bool_and_out_of_range_scores():
    items = (item("a"),)
    for score in (True, math.nan, math.inf, -0.1, 1.1):
        with pytest.raises(ValueError):
            attach_local_relevance_scores("same", items, lambda q, candidate, score=score: score)


def test_rerank_is_bounded_to_small_candidate_set():
    items = (item("a"), item("b"), item("c"))
    limits = SemanticIntegrationLimits(max_results=2)
    with pytest.raises(ValueError, match="candidate budget"):
        attach_local_relevance_scores("same", items, lambda q, candidate: 0.5, limits=limits)


def test_rerank_rejects_duplicate_source_ids():
    with pytest.raises(ValueError, match="unique"):
        attach_local_relevance_scores("same", (item("a"), item("a")), lambda q, candidate: 0.5)
