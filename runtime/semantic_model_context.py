"""Bounded, model-neutral context materialization from fused semantic evidence."""
from __future__ import annotations

from typing import Mapping

from .semantic_code_types import canonical_json_bytes
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import FusedQueryResult

_RESERVED = {
    "schema_version",
    "project_id",
    "query",
    "items",
    "item_count",
    "available_item_count",
    "byte_count",
    "truncated",
    "retrieval_owner",
    "source_receipt_sha256",
    "write_authority",
}


def _serialized_size(payload: Mapping[str, object]) -> int:
    return len(canonical_json_bytes(payload))


def _with_exact_byte_count(payload: dict[str, object]) -> tuple[dict[str, object], int]:
    size = 0
    for _ in range(8):
        candidate = dict(payload)
        candidate["byte_count"] = size
        new_size = _serialized_size(candidate)
        if new_size == size:
            return candidate, new_size
        size = new_size
    candidate = dict(payload)
    candidate["byte_count"] = size
    return candidate, _serialized_size(candidate)


def materialize_model_context(
    result: FusedQueryResult,
    *,
    max_bytes: int | None = None,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
    annotations: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(result, FusedQueryResult):
        raise TypeError("result must be a FusedQueryResult")
    budget = limits.max_context_bytes if max_bytes is None else max_bytes
    if type(budget) is not int or not 1 <= budget <= limits.max_context_bytes:
        raise ValueError("max_bytes must be a positive integer within max_context_bytes")
    extras = dict(annotations or {})
    overlap = _RESERVED.intersection(extras)
    if overlap:
        raise ValueError(f"context annotations override reserved fields: {sorted(overlap)!r}")
    # Validate serializability/bounds before any partial output is built.
    if len(canonical_json_bytes(extras)) > limits.max_receipt_bytes:
        raise ValueError("context annotation budget exceeded")

    items: list[dict[str, object]] = []
    base: dict[str, object] = {
        "schema_version": "px.semantic-model-context/1.1",
        "project_id": result.project_id,
        "query": result.query,
        "items": items,
        "item_count": 0,
        "available_item_count": len(result.hits),
        "byte_count": 0,
        "truncated": bool(result.hits),
        "retrieval_owner": result.canonical_retrieval_owner,
        "source_receipt_sha256": result.receipt_sha256,
        "write_authority": False,
        **extras,
    }
    empty_payload, empty_size = _with_exact_byte_count(base)
    if empty_size > budget:
        raise ValueError("model context envelope exceeds requested byte budget")

    payload = empty_payload
    for hit in result.hits:
        if not isinstance(hit, Mapping):
            raise TypeError("fused retrieval hits must be mappings")
        item = {
            "source_id": hit.get("source_id"),
            "title": hit.get("title"),
            "excerpt": hit.get("excerpt"),
            "citation": hit.get("citation"),
            "lineage": hit.get("lineage"),
            "score": hit.get("score"),
            "source_revision": hit.get("source_revision"),
        }
        # Reject objects that only become strings through a permissive serializer.
        canonical_json_bytes(item)
        candidate = dict(base)
        candidate_items = [*items, item]
        candidate["items"] = candidate_items
        candidate["item_count"] = len(candidate_items)
        candidate["truncated"] = len(candidate_items) < len(result.hits)
        candidate, size = _with_exact_byte_count(candidate)
        if size > budget:
            break
        items = candidate_items
        payload = candidate

    # If every item fit, make the final truncation marker exact.
    final = dict(payload)
    final["items"] = items
    final["item_count"] = len(items)
    final["truncated"] = len(items) < len(result.hits)
    final, final_size = _with_exact_byte_count(final)
    if final_size > budget:
        raise RuntimeError("model context budget invariant violated")
    return final
