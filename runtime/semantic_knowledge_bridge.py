"""Translate semantic evidence into the canonical PX retrieval source schema."""
from __future__ import annotations

from .retrieval import RetrievalSource
from .semantic_code_types import canonical_json_bytes
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import SemanticEvidence


def to_retrieval_sources(
    evidence: tuple[SemanticEvidence, ...],
    *,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> tuple[RetrievalSource, ...]:
    if type(evidence) is not tuple:
        raise TypeError("semantic evidence must be a tuple")
    if len(evidence) > limits.max_sources:
        raise ValueError("semantic evidence source budget exceeded")
    for item in evidence:
        if not isinstance(item, SemanticEvidence):
            raise TypeError("semantic evidence entries must be SemanticEvidence objects")
    source_ids = [item.source_id for item in evidence]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("semantic evidence source_id values must be unique")

    metadata_bytes = 0
    sources: list[RetrievalSource] = []
    for item in evidence:
        metadata = dict(item.metadata)
        structured = dict(item.structured)
        metadata_bytes += len(canonical_json_bytes(metadata)) + len(canonical_json_bytes(structured))
        if metadata_bytes > limits.max_receipt_bytes:
            raise ValueError("semantic evidence metadata budget exceeded")
        sources.append(
            RetrievalSource(
                source_id=item.source_id,
                title=item.title,
                text=item.text,
                visibility=item.visibility,
                lineage=item.lineage,
                kind=item.source_kind,
                links=(),
                metadata=metadata,
                structured=structured,
                dense_score=item.dense_score,
                graph_score=item.graph_score,
                trust=item.trust,
                source_revision=item.revision,
            )
        )
    return tuple(sources)
