import json
import pytest

from runtime.semantic_code_types import stable_sha256
from runtime.semantic_integration_types import FusedQueryResult
from runtime.semantic_local_model_bridge import local_model_context


def fused(*, hits=()):
    return FusedQueryResult(
        "q",
        "p",
        hits,
        {},
        0,
        "runtime.retrieval.retrieve",
        stable_sha256({"fixture": "local-model"}),
    )


def test_local_model_context_has_no_context_derived_authority():
    ctx = local_model_context(fused())
    assert ctx["execution_authority"] == "not_granted_by_context"
    assert ctx["tool_calls_allowed_by_context"] is False
    assert ctx["tool_authority_source"] == "separate_px_contracts"
    assert ctx["learning_updates_require_contract"] is True
    assert ctx["graph_map_updates_require_contract"] is True


def test_local_model_context_respects_final_serialized_budget():
    hit = {
        "source_id": "s",
        "title": "T",
        "excerpt": "x" * 1000,
        "citation": "source:s",
        "lineage": "l",
        "score": 1.0,
        "source_revision": "r",
    }
    ctx = local_model_context(fused(hits=(hit,)), max_bytes=900)
    encoded = json.dumps(ctx, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= 900
    assert ctx["byte_count"] == len(encoded)


def test_local_model_context_rejects_impossibly_small_envelope():
    with pytest.raises(ValueError, match="envelope"):
        local_model_context(fused(), max_bytes=32)
