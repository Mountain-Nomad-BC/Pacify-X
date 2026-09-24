from pathlib import Path
import pytest

from runtime.semantic_cross_project import CrossProjectSemanticService
from runtime.semantic_orchestration import SemanticReadOrchestrator
from runtime.semantic_project_catalog import SemanticProjectCatalog
from tests.semantic_integration_test_support import fusion_auth, make_project


def build(tmp_path: Path):
    project = make_project(tmp_path / "p")
    catalog = SemanticProjectCatalog()
    catalog.register("p1", project)
    cross = CrossProjectSemanticService(catalog)
    return cross, SemanticReadOrchestrator(cross)


def test_orchestrated_read_produces_fused_context_receipt_and_authority_boundary(tmp_path: Path):
    cross, orchestrator = build(tmp_path)
    try:
        result = orchestrator.query(fusion_auth("p1"), "p1", "helper", include_project_map=False)
        assert result["effects"] == ["read"] and result["mutation"] is False
        assert result["model_context"]["item_count"] >= 1
        assert len(result["receipt"]["receipt_sha256"]) == 64
        assert result["authority_boundary"]["follow_on_actions_require_px_contract"] is True
    finally:
        cross.close()


def test_orchestration_rejects_boolean_or_out_of_range_result_budget(tmp_path: Path):
    cross, orchestrator = build(tmp_path)
    try:
        for value in (True, 0, orchestrator.limits.max_results + 1):
            with pytest.raises(ValueError):
                orchestrator.query(fusion_auth("p1"), "p1", "helper", include_project_map=False, max_results=value)  # type: ignore[arg-type]
    finally:
        cross.close()


def test_orchestration_requires_boolean_project_map_flag(tmp_path: Path):
    cross, orchestrator = build(tmp_path)
    try:
        with pytest.raises(TypeError):
            orchestrator.query(fusion_auth("p1"), "p1", "helper", include_project_map=1)  # type: ignore[arg-type]
    finally:
        cross.close()
