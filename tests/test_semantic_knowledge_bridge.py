import pytest

from runtime.semantic_integration_limits import SemanticIntegrationLimits
from runtime.semantic_integration_types import SemanticEvidence
from runtime.semantic_knowledge_bridge import to_retrieval_sources


def evidence(source_id: str = "s", *, metadata=None):
    return SemanticEvidence(
        source_id,
        "semantic_symbol",
        "helper",
        "helper code",
        "p",
        "lineage",
        "a.py",
        trust=1.0,
        metadata=metadata or {},
    )


def test_bridge_uses_canonical_retrieval_schema():
    src = to_retrieval_sources((evidence(),))[0]
    assert src.source_id == "s"
    assert src.kind == "semantic_symbol"
    assert src.trust == 1.0
    assert src.lineage == "lineage"


def test_bridge_rejects_duplicate_source_identity():
    with pytest.raises(ValueError, match="unique"):
        to_retrieval_sources((evidence("s"), evidence("s")))


def test_bridge_bounds_metadata_serialization():
    limits = SemanticIntegrationLimits(max_receipt_bytes=32)
    with pytest.raises(ValueError, match="metadata budget"):
        to_retrieval_sources((evidence(metadata={"blob": "x" * 100}),), limits=limits)


def test_bridge_requires_tuple_input():
    with pytest.raises(TypeError):
        to_retrieval_sources([evidence()])  # type: ignore[arg-type]


def test_bridge_rejects_non_evidence_entries_cleanly():
    with pytest.raises(TypeError, match="SemanticEvidence"):
        to_retrieval_sources((object(),))  # type: ignore[arg-type]
