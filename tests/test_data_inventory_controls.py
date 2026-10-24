"""Data planning enumerates real custody and never substitutes for erasure."""
import copy
from pathlib import Path

import pytest

from runtime.data_inventory import build_inventory, erasure_plan, DataInventoryError
from runtime.data_controls import data_control_request, SCHEMA_VERSION


def test_host_resource_custody_is_present_and_planning_performs_no_writes(tmp_path, monkeypatch):
    custody = tmp_path / ".agentic_engineering_os_px/resource-lifecycle"
    custody.mkdir(parents=True)
    ledger = custody / "resources.json"
    ledger.write_text('{"fixture":"actual owned namespace"}\n', encoding="utf-8")
    before = ledger.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("read-only planning attempted a filesystem mutation")
    for method in ("write_text", "write_bytes", "mkdir", "unlink", "rename", "replace"):
        monkeypatch.setattr(Path, method, forbidden)
    response = data_control_request(tmp_path, {
        "schema_version": SCHEMA_VERSION, "operation": "inventory"})
    inventory = response["result"]
    store = next(row for row in inventory["stores"] if row["store_id"] == "host-resource-lifecycle")
    assert store["present"] is True
    assert store["owner"] == "runtime.resource_lifecycle"
    assert store["retention_days"] is None
    assert inventory["coverage_complete"] is False
    assert response["effects_executed"] is False
    assert response["legal_signoff_asserted"] is False
    plan = erasure_plan(inventory, ["explicit-subject"])
    assert plan["executed"] is False
    assert plan["scope_resolution_complete"] is False
    assert {"store_id": store["store_id"], "reason": "technical_evidence_preservation"} in plan["refused_stores"]
    assert ledger.read_bytes() == before


def test_tampered_inventory_cannot_remove_subject_resolution(tmp_path):
    inventory = build_inventory(tmp_path)
    changed = copy.deepcopy(inventory)
    changed["stores"][0]["subject_record_resolution_required"] = False
    with pytest.raises(DataInventoryError, match="digest differs"):
        erasure_plan(changed, ["subject"])


def test_access_manifest_does_not_claim_record_export_or_complete_coverage(tmp_path):
    response = data_control_request(tmp_path, {
        "schema_version": SCHEMA_VERSION, "operation": "access-manifest",
        "subject_scope": ["subject"]})
    result = response["result"]
    assert result["status"] == "CANONICAL_SUBJECT_RECORD_RESOLUTION_REQUIRED"
    assert result["record_count"] is None
    assert result["record_content_exported"] is False
    assert result["coverage_complete"] is False
