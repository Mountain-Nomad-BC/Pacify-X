from pathlib import Path
import pytest
from runtime.semantic_cross_project import CrossProjectSemanticService
from runtime.semantic_project_catalog import SemanticProjectCatalog
from tests.semantic_integration_test_support import auth, make_project

def test_cross_project_query_is_explicit_and_read_only(tmp_path: Path):
    project = make_project(tmp_path / "p")
    catalog = SemanticProjectCatalog(); catalog.register("p1", project)
    service = CrossProjectSemanticService(catalog)
    result = service.query(auth("p1", "semantic.symbol.find"), "p1", "semantic.symbol.find", {"pattern": "helper"})
    assert result["read_only"] is True
    assert any(x["name"] == "helper" for x in result["result"]["matches"])
    with pytest.raises(PermissionError): service.query(auth("p1", "semantic.edit.apply"), "p1", "semantic.edit.apply", {})
    service.close()

def test_cross_project_arguments_are_strict_not_truthy_coercions(tmp_path: Path):
    project = make_project(tmp_path / "strict")
    catalog = SemanticProjectCatalog(); catalog.register("p1", project)
    service = CrossProjectSemanticService(catalog)
    with pytest.raises(ValueError, match="substring must be a boolean"):
        service.query(
            auth("p1", "semantic.symbol.find"),
            "p1",
            "semantic.symbol.find",
            {"pattern": "helper", "substring": "false"},
        )
    with pytest.raises(ValueError, match="max_results"):
        service.query(
            auth("p1", "semantic.symbol.find"),
            "p1",
            "semantic.symbol.find",
            {"pattern": "helper", "max_results": True},
        )
    service.close()
