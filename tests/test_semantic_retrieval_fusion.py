import pytest

from runtime.retrieval import RETRIEVAL_OWNER
from runtime.semantic_integration_types import SemanticEvidence
from runtime.semantic_retrieval_fusion import fuse_evidence


def evidence(source_id: str, project_id: str = "p", text: str = "run engine fast"):
    return SemanticEvidence(source_id, "semantic_symbol", source_id, text, project_id, "one", f"{source_id}.py", trust=1.0)


def test_fusion_delegates_ranking_to_px_retrieval():
    items = (
        evidence("a", text="run engine fast"),
        SemanticEvidence("b", "project_map", "Other", "unrelated storage", "p", "two", "b.py", trust=1.0),
    )
    result = fuse_evidence("engine run", "p", items, identity_scope=("project",))
    assert result.canonical_retrieval_owner == RETRIEVAL_OWNER
    assert result.hits[0]["source_id"] == "a"
    assert len(result.receipt_sha256) == 64


def test_fusion_rejects_duplicate_or_foreign_evidence():
    with pytest.raises(ValueError, match="unique"):
        fuse_evidence("engine", "p", (evidence("a"), evidence("a")), identity_scope=("project",))
    with pytest.raises(PermissionError, match="requested project"):
        fuse_evidence("engine", "p", (evidence("a", "other"),), identity_scope=("project",))


def test_fusion_strictly_validates_budgets_and_identity_scope():
    with pytest.raises(ValueError):
        fuse_evidence("engine", "p", (evidence("a"),), max_results=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        fuse_evidence("engine", "p", (evidence("a"),), identity_scope=("project", "project"))
