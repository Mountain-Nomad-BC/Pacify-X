"""Normalize semantic evidence provenance without turning derived evidence into source authority."""
from __future__ import annotations
from .semantic_code_types import stable_sha256
from .semantic_integration_types import SemanticEvidence


def evidence_provenance(item: SemanticEvidence) -> dict[str, object]:
    identity = {
        "source_id": item.source_id,
        "source_kind": item.source_kind,
        "project_id": item.project_id,
        "lineage": item.lineage,
        "locator": item.locator,
        "revision": item.revision,
    }
    return {**identity, "derived": True, "authoritative_source": False, "provenance_sha256": stable_sha256(identity)}
