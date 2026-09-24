from __future__ import annotations

import pytest

from runtime.query_planner import LexiconEntry, QueryPlanner
from runtime.retrieval import RetrievalSource, retrieve


def test_query_plan_is_stable_and_resolves_aliases() -> None:
    planner = QueryPlanner((LexiconEntry("provider gateway", ("provider bridge",), "runtime"),))
    left = planner.plan("Show provider bridge evidence")
    right = planner.plan("Show provider bridge evidence")
    assert left.plan_sha256 == right.plan_sha256
    assert left.aliases_resolved == (("provider bridge", "provider gateway"),)
    assert "provider gateway" in left.expansions
    assert left.authority_granted is False


def test_query_planner_rejects_ambiguous_aliases() -> None:
    with pytest.raises(ValueError, match="ambiguous query alias"):
        QueryPlanner((LexiconEntry("alpha", ("same",)), LexiconEntry("beta", ("same",))))


def test_exact_source_id_survives_semantic_scoring_and_tiny_budget() -> None:
    planner = QueryPlanner()
    plan = planner.plan("source_id:doc-42 tell me about something unrelated")
    decision = retrieve(
        plan.raw_query,
        (
            RetrievalSource("doc-42", "Exact", "ZZZZ", ("public",), "exact"),
            RetrievalSource("other", "Something unrelated", "something unrelated and highly relevant", ("public",), "semantic"),
        ),
        identity_scope=(),
        max_results=1,
        max_context_bytes=1,
        query_plan=plan,
    )
    assert decision.hits[0].source_id == "doc-42"
    assert decision.hits[0].exact_identifier is True
    assert decision.query_plan_sha256 == plan.plan_sha256


def test_exact_hash_is_normalized_lowercase() -> None:
    value = "A" * 64
    plan = QueryPlanner().plan(f"prove {value}")
    assert plan.exact_identifiers == (value.lower(),)
    assert plan.exact_keys == (f"sha256:{value.lower()}",)


def test_retrieval_rejects_untyped_query_plan() -> None:
    with pytest.raises(ValueError, match="typed QueryPlan"):
        retrieve("x", (RetrievalSource("a", "A", "x", ("public",), "a"),), identity_scope=(), query_plan={})
