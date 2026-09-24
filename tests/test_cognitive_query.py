from __future__ import annotations

import json
from pathlib import Path
import pytest

from runtime.cognitive_query import (
    CognitiveCandidate, bounded_topk, cognitive_query, hydrate_selected,
    query_repository_index, CORE_CATEGORIES,
)
from runtime.tiny_model_operator import TinyModelOperator


def c(category: str, oid: str, score: float, *, project="p", lifecycle="admitted") -> CognitiveCandidate:
    return CognitiveCandidate(category, oid, "r1", score, oid, lifecycle, project, (), ("test",), f"{oid}.json", oid)


def test_top_per_category_is_bounded_and_project_filtered():
    rows = [c("skills", f"s{i}", i / 10) for i in range(1, 6)] + [c("skills", "foreign", 1.0, project="other")]
    result = bounded_topk(rows, project_id="p", top_per_category=3)
    assert [item.object_id for item in result["skills"]] == ["s5", "s4", "s3"]
    with pytest.raises(ValueError, match="1..3"):
        bounded_topk(rows, project_id="p", top_per_category=4)


def test_non_retrievable_lifecycle_is_excluded():
    result = bounded_topk([c("goals", "g1", .9, lifecycle="candidate")], project_id="p")
    assert result["goals"] == []


def test_librarian_runs_only_for_ambiguous_category_and_cannot_expand_set():
    calls = []
    lib = TinyModelOperator(
        lambda payload: calls.append(payload) or {"selected_ids": ["s2", "s1"], "unresolved": False, "reason": "fit"},
        model_id="qwen3.5-0.8b-control", profile_id="cpu", model_generation="mg", fabric_generation="fg",
    )
    result = cognitive_query(
        "skill lookup", project_id="p", generation_id="cg",
        candidates=[c("skills", "s1", .80), c("skills", "s2", .78), c("knowledge", "k1", 1.0)],
        librarian=lib, retrieval_generation="rg",
    )
    assert [item.object_id for item in result.categories["skills"]][:2] == ["s2", "s1"]
    assert [item.object_id for item in result.categories["knowledge"]] == ["k1"]
    assert len(calls) == 1
    assert calls[0]["purpose"] == "rerank-skills"


def test_hydration_can_only_use_returned_ids():
    result = cognitive_query("q", project_id="p", generation_id="g", candidates=[c("skills", "s1", .9)])
    hydrated = hydrate_selected(result, {"skills": ["s1"]}, lambda item: {"id": item.object_id})
    assert hydrated["records"][0]["body"]["id"] == "s1"
    with pytest.raises(ValueError, match="non-result"):
        hydrate_selected(result, {"skills": ["made-up"]}, lambda item: {})


def test_repository_index_query_returns_core_shape(tmp_path: Path):
    registry = tmp_path / "registry"; registry.mkdir()
    payload = {
        "revision": "rev-index",
        "records": [
            {"key":"skill:alpha", "id":"alpha", "kind":"skill", "title":"Alpha plumber", "summary":"plumbing skill", "owner":"o", "status":"admitted", "domain":"plumbing", "path":"registry/skills/alpha.json", "implementation_path":"", "aliases":[], "triggers":["plumbing"], "concepts":[], "inputs":[], "outputs":[], "dependencies":[], "formula_refs":[], "relations":[], "source_sha256":"a"*64, "source_provenance":[]},
            {"key":"workflow:wf", "id":"wf", "kind":"workflow", "title":"Plumbing workflow", "summary":"workflow", "owner":"o", "status":"active", "domain":"orchestration", "path":"registry/wf.json", "implementation_path":"", "aliases":[], "triggers":["plumbing"], "concepts":[], "inputs":[], "outputs":[], "dependencies":[], "formula_refs":[], "relations":[], "source_sha256":"b"*64, "source_provenance":[]},
        ],
        "edges": [],
    }
    (registry / "cognitive_map_index.json").write_text(json.dumps(payload), encoding="utf-8")
    result = query_repository_index(tmp_path, "plumbing", project_id="p", top_per_category=2)
    assert result.generation_id == "rev-index"
    assert result.categories["skills"][0].object_id == "alpha"
    assert result.categories["orchestrations"][0].object_id == "wf"
    assert tuple(result.as_dict()["categories"]) == CORE_CATEGORIES


def test_hydration_context_pressure_requires_published_checkpoint_at_threshold():
    result = cognitive_query("q", project_id="p", generation_id="g", candidates=[c("skills", "s1", .9)])
    soft = hydrate_selected(result, {"skills": ["s1"]}, lambda item: {"id": item.object_id}, context_used_tokens=71, context_max_tokens=100)
    assert soft["context_pressure"] == "soft-compaction-checkpoint-consideration"
    with pytest.raises(RuntimeError, match="published checkpoint"):
        hydrate_selected(result, {"skills": ["s1"]}, lambda item: {}, context_used_tokens=82, context_max_tokens=100)
    receipt = {"schema_version":"px.context-checkpoint-publication/1.0", "checkpoint_id":"ctx-1", "compaction_permitted":True, "receipt_sha256":"a"*64}
    allowed = hydrate_selected(result, {"skills": ["s1"]}, lambda item: {"ok": True}, context_used_tokens=90, context_max_tokens=100, checkpoint_publication_receipt=receipt)
    assert allowed["context_pressure"] == "hard-checkpoint-and-block-bulk-hydration"
    assert allowed["checkpoint_id"] == "ctx-1"
