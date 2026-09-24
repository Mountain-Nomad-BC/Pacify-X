"""Fuse semantic/project-map/memory/knowledge evidence through canonical PX retrieval."""
from __future__ import annotations

from dataclasses import asdict

from .retrieval import RETRIEVAL_OWNER, retrieve
from .semantic_code_types import stable_sha256
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import FusedQueryResult, SemanticEvidence
from .semantic_knowledge_bridge import to_retrieval_sources


def _validate_identity_scope(
    identity_scope: tuple[str, ...], *, limits: SemanticIntegrationLimits
) -> tuple[str, ...]:
    if type(identity_scope) is not tuple:
        raise TypeError("identity_scope must be a tuple")
    if len(identity_scope) > limits.max_operations:
        raise ValueError("identity scope budget exceeded")
    if len(set(identity_scope)) != len(identity_scope):
        raise ValueError("identity_scope values must be unique")
    for value in identity_scope:
        if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 512:
            raise ValueError("identity_scope values must be bounded nonempty text")
    return identity_scope


def fuse_evidence(
    query: str,
    project_id: str,
    evidence: tuple[SemanticEvidence, ...],
    *,
    identity_scope: tuple[str, ...] = (),
    max_results: int = 8,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> FusedQueryResult:
    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > limits.max_query_bytes:
        raise ValueError("query must be nonempty and within budget")
    if type(project_id) is not str or not project_id.strip() or len(project_id.encode("utf-8")) > 256:
        raise ValueError("project_id must be bounded nonempty text")
    if type(max_results) is not int or not 1 <= max_results <= limits.max_results:
        raise ValueError("max_results must be a positive integer within the result budget")
    scope = _validate_identity_scope(identity_scope, limits=limits)
    if type(evidence) is not tuple:
        raise TypeError("evidence must be a tuple")
    if len(evidence) > limits.max_sources:
        raise ValueError("semantic evidence source budget exceeded")
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, SemanticEvidence):
            raise TypeError("evidence entries must be SemanticEvidence objects")
        if item.project_id != project_id:
            raise PermissionError("fused evidence must belong to the requested project")
        if item.source_id in seen:
            raise ValueError("fused evidence source_id values must be unique")
        seen.add(item.source_id)

    decision = retrieve(
        query,
        to_retrieval_sources(evidence, limits=limits),
        identity_scope=scope,
        max_results=max_results,
        max_context_bytes=limits.max_context_bytes,
    )
    hits = tuple(asdict(hit) for hit in decision.hits)
    counts: dict[str, int] = {}
    by_id = {item.source_id: item for item in evidence}
    for hit in decision.hits:
        kind = by_id[hit.source_id].source_kind if hit.source_id in by_id else "unknown"
        counts[kind] = counts.get(kind, 0) + 1
    identity = {
        "query": query,
        "project_id": project_id,
        "identity_scope": scope,
        "max_results": max_results,
        "hits": hits,
        "filtered_source_ids": decision.filtered_source_ids,
        "source_counts": counts,
        "context_bytes": decision.context_bytes,
        "owner": decision.canonical_owner,
        "owner_revision": decision.owner_revision,
        "signal_availability": dict(decision.signal_availability),
    }
    return FusedQueryResult(
        query,
        project_id,
        hits,
        counts,
        decision.context_bytes,
        RETRIEVAL_OWNER,
        stable_sha256(identity),
    )
