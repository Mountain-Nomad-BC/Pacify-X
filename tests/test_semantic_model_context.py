import json
import pytest

from runtime.semantic_code_types import stable_sha256
from runtime.semantic_integration_types import FusedQueryResult
from runtime.semantic_model_context import materialize_model_context


def result(*, hits=()):
    return FusedQueryResult(
        "q",
        "p",
        hits,
        {"x": len(hits)},
        100,
        "runtime.retrieval.retrieve",
        stable_sha256({"fixture": "context", "n": len(hits)}),
    )


def test_model_context_is_read_only_and_exactly_bounded():
    hit = {
        "source_id": "s",
        "title": "T",
        "excerpt": "x" * 100,
        "citation": "source:s",
        "lineage": "l",
        "score": 1.0,
        "source_revision": "r",
    }
    ctx = materialize_model_context(result(hits=(hit,)), max_bytes=1000)
    encoded = json.dumps(ctx, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert ctx["write_authority"] is False
    assert ctx["item_count"] == 1
    assert ctx["truncated"] is False
    assert ctx["byte_count"] == len(encoded) <= 1000


def test_model_context_truncates_whole_items_not_bytes():
    hit = {
        "source_id": "s",
        "title": "T",
        "excerpt": "x" * 5000,
        "citation": "source:s",
        "lineage": "l",
        "score": 1.0,
        "source_revision": "r",
    }
    ctx = materialize_model_context(result(hits=(hit,)), max_bytes=500)
    assert ctx["item_count"] == 0
    assert ctx["available_item_count"] == 1
    assert ctx["truncated"] is True


def test_model_context_rejects_invalid_budget_and_reserved_annotation_override():
    with pytest.raises(ValueError):
        materialize_model_context(result(), max_bytes=0)
    with pytest.raises(ValueError, match="reserved"):
        materialize_model_context(result(), annotations={"items": []})
