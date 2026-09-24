from datetime import datetime, timezone
from runtime.semantic_evidence_bridge import bind_semantic_evidence
from runtime.semantic_integration_types import SemanticEvidence

def test_evidence_binding_supports_claim_with_tool_results():
    evidence = (SemanticEvidence("s","semantic_symbol","helper","helper","p","lineage","a.py"),)
    package = bind_semantic_evidence("task", "helper exists", evidence, as_of=datetime(2026,9,20,tzinfo=timezone.utc))
    assert package.unsupported_claims == ()
    assert package.claims[0].supported is True

import pytest


def test_evidence_binding_rejects_duplicate_source_revision():
    item = SemanticEvidence("s", "semantic_symbol", "helper", "helper", "p", "lineage", "a.py", revision="r1")
    with pytest.raises(ValueError, match="duplicate"):
        bind_semantic_evidence(
            "task", "helper exists", (item, item),
            as_of=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
