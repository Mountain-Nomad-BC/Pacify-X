from pathlib import Path
import pytest

from runtime.semantic_code_types import stable_sha256
from runtime.semantic_integration_limits import SemanticIntegrationLimits
from runtime.semantic_integration_service import SemanticIntegrationService
from runtime.semantic_integration_types import FusedQueryResult
from tests.semantic_integration_test_support import auth, fusion_auth, make_project


def test_top_level_service_supports_dependency_clean_wave3_reads(tmp_path: Path):
    project = make_project(tmp_path / "p")
    service = SemanticIntegrationService()
    service.register_project("p1", project)
    try:
        result = service.query_operation(
            auth("p1", "semantic.symbol.find"),
            "p1",
            "semantic.symbol.find",
            {"pattern": "Engine"},
        )
        assert result["project_id"] == "p1"
        assert result["read_only"] is True
        assert result["result"]["matches"]
        assert service.inventory()["authoritative"] is False
    finally:
        service.close()


def test_wave4_orchestrated_query_and_local_model_context_are_live(tmp_path: Path):
    project = make_project(tmp_path / "p")
    service = SemanticIntegrationService()
    service.register_project("p1", project)
    try:
        result = service.query(
            fusion_auth("p1"), "p1", "Engine", include_project_map=False
        )
        assert result["mutation"] is False
        local = service.local_model_context(result, max_bytes=4096)
        assert local["operator_role"] == "librarian-concierge-grunt"
        assert local["tool_calls_allowed_by_context"] is False
    finally:
        service.close()


def test_service_forwards_custom_context_limits_to_wave4_bridge():
    service = SemanticIntegrationService(
        limits=SemanticIntegrationLimits(max_context_bytes=512)
    )
    fused = FusedQueryResult(
        "q",
        "p",
        (),
        {},
        0,
        "runtime.retrieval.retrieve",
        stable_sha256("fixture"),
    )
    with pytest.raises(ValueError, match="max_context_bytes"):
        service.local_model_context({"fused": {
            "query": fused.query,
            "project_id": fused.project_id,
            "hits": fused.hits,
            "source_counts": fused.source_counts,
            "context_bytes": fused.context_bytes,
            "canonical_retrieval_owner": fused.canonical_retrieval_owner,
            "receipt_sha256": fused.receipt_sha256,
        }}, max_bytes=1024)
    service.close()
