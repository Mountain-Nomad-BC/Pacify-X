from pathlib import Path
import pytest
from runtime.semantic_cross_project import CrossProjectSemanticService
from runtime.semantic_project_catalog import SemanticProjectCatalog
from runtime.semantic_project_map_bridge import query_project_map_evidence
from tests.semantic_integration_test_support import auth, make_project


def test_missing_project_map_fails_explicitly_without_breaking_semantic_reads(tmp_path: Path):
    project = make_project(tmp_path / "p")
    catalog = SemanticProjectCatalog(); catalog.register("p1", project)
    cross = CrossProjectSemanticService(catalog)

    with pytest.raises((FileNotFoundError, ValueError)):
        query_project_map_evidence("p1", project, "helper")

    semantic = cross.query(
        auth("p1", "semantic.symbol.find"),
        "p1",
        "semantic.symbol.find",
        {"pattern": "helper"},
    )
    assert semantic["result"]["matches"]
    cross.close()
