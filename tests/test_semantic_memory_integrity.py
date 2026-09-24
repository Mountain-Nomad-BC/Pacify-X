import pytest

from runtime.semantic_memory_integrity import validate_memory_references
from tests.semantic_integration_test_support import memory_location, memory_record


def test_integrity_survives_physical_relocation_and_detects_stale():
    record = memory_record()
    loc = memory_location(record, tier="cold", locator="memory/cold/mem-1.json")
    contents = {"note": "depends on pxmem://p1/mem-1@2 and pxmem://p1/missing"}
    report = validate_memory_references(contents, {record.memory_id: loc}, project_id="p1")
    assert report.clean is False
    assert [item.code for item in report.issues] == ["stale_reference"]


def test_foreign_project_scope_is_rejected_before_target_lookup():
    report = validate_memory_references(
        {"note": "pxmem://foreign/secret"}, {}, project_id="p1"
    )
    assert [item.code for item in report.issues] == ["foreign_project_reference"]
    assert "does not resolve" not in report.issues[0].detail


def test_pinned_revision_requires_exact_current_revision_evidence():
    record = memory_record(revision=3)
    loc = memory_location(record)
    report = validate_memory_references(
        {"note": "pxmem://p1/mem-1@2"}, {record.memory_id: loc}, project_id="p1"
    )
    assert [item.code for item in report.issues] == ["revision_not_available"]


def test_integrity_reference_budget_is_strict():
    with pytest.raises(ValueError):
        validate_memory_references({"a": "pxmem://p/m"}, {}, max_references=0)


def test_integrity_allows_trailing_reference_free_sources_at_exact_budget():
    report = validate_memory_references(
        {"a": "pxmem://p/m", "z": "no references here"},
        {},
        max_references=1,
    )
    assert report.checked_references == 1
