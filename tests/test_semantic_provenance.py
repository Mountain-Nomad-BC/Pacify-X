from runtime.semantic_integration_types import SemanticEvidence
from runtime.semantic_provenance import evidence_provenance

def test_semantic_evidence_is_derived_not_authority():
    item = SemanticEvidence("s","symbol","T","text","p","lineage","a.py",revision="r")
    p = evidence_provenance(item)
    assert p["derived"] is True and p["authoritative_source"] is False
