from pathlib import Path
import pytest

from runtime.semantic_cross_project import CrossProjectSemanticService
from runtime.semantic_orchestration import SemanticReadOrchestrator
from runtime.semantic_project_catalog import SemanticProjectCatalog
from tests.semantic_integration_test_support import auth, make_project


def test_orchestration_requires_all_internal_read_scopes(tmp_path: Path):
    project = make_project(tmp_path / "p")
    catalog = SemanticProjectCatalog()
    catalog.register("p1", project)
    cross = CrossProjectSemanticService(catalog)
    try:
        with pytest.raises(PermissionError):
            SemanticReadOrchestrator(cross).query(
                auth("p1", "semantic.symbol.find"),
                "p1",
                "helper",
                include_project_map=False,
            )
    finally:
        cross.close()


def test_project_map_scope_is_only_required_when_requested(tmp_path: Path):
    project = make_project(tmp_path / "p")
    catalog = SemanticProjectCatalog()
    catalog.register("p1", project)
    cross = CrossProjectSemanticService(catalog)
    base = auth(
        "p1",
        "semantic.cross_project.query",
        "semantic.symbol.find",
        "semantic.knowledge.fuse",
        "semantic.model.context",
    )
    try:
        SemanticReadOrchestrator(cross).query(base, "p1", "helper", include_project_map=False)
        with pytest.raises(PermissionError):
            SemanticReadOrchestrator(cross).query(base, "p1", "helper", include_project_map=True)
    finally:
        cross.close()
