from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES, _source_path, assemble, current_source_manifest


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "source.js").write_text("current source", encoding="utf-8")
    controls = []
    for control_id in ("pxui.demo.field.name", "pxui.demo.persistence.authoritativeState"):
        kind = control_id.split(".")[2]
        controls.append({
            "control_id": control_id, "surface_id": "demo", "kind": kind,
            "source_refs": ["source.js:1"], "evidence_mode": "contained_ui_input" if kind == "field" else "contained_durability",
            "stage_policy": {stage: "required" if stage in {"open_load", "display", "result_acknowledgement"} else "not_applicable_with_evidence" for stage in STAGES},
        })
    matrix = {"control_count": 2, "controls": controls}
    write(tmp_path / "registry/operational_control_proof_matrix.json", matrix)
    write(tmp_path / "registry/operational_surface_inventory.json", {"schema_version": "test", "inventory_id": "test", "surfaces": [{"surface_id": "demo", "controls": []}]})
    records = []
    for item in controls:
        chain = {stage: {"state": "not_applicable", "detail": "matrix N/A", "evidence": ["matrix"]} for stage in STAGES}
        for stage in ("open_load", "display", "result_acknowledgement"):
            chain[stage] = {"state": "missing", "detail": "not observed", "evidence": []}
        if item["kind"] == "field":
            for stage in ("open_load", "display", "result_acknowledgement"):
                chain[stage] = {"state": "present", "detail": "direct browser observation", "evidence": ["browser"]}
        records.append({"control_id": item["control_id"], "attempted": item["kind"] == "field", "rendered": item["kind"] == "field", "observed": item["kind"] == "field", "interaction_chain": chain})
    ui = tmp_path / "ui.json"
    write(ui, {"schema_version": "px.exhaustive-operational-control-walk/1.0", "source": {"control_source_manifest": current_source_manifest(tmp_path, matrix)}, "records": records})
    return tmp_path, ui


def stage_record(control_id: str) -> dict[str, object]:
    stages = {stage: {"state": "not_applicable", "detail": "matrix N/A", "evidence": ["matrix"]} for stage in STAGES}
    for stage in ("open_load", "display", "result_acknowledgement"):
        stages[stage] = {"state": "present", "detail": "direct disposable durability probe", "evidence": ["receipt"]}
    return {"control_id": control_id, "attempted": True, "rendered": False, "observed": True, "stages": stages}


def test_partial_sources_never_promote_missing_control(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    result = assemble(root, ui, [])
    records = {item["control_id"]: item for item in result["control_chains"]["controls"]}
    assert records["pxui.demo.field.name"]["terminal_disposition"] == "interaction_complete"
    assert records["pxui.demo.persistence.authoritativeState"]["terminal_disposition"] == "observed_only"
    assert result["control_chains"]["aggregates"]["complete_interaction_chains"] == 1


def test_exact_direct_stage_receipt_completes_only_its_control(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    receipt = root / "durability.json"
    matrix = json.loads((root / "registry/operational_control_proof_matrix.json").read_text(encoding="utf-8"))
    write(receipt, {"schema_version": "px.operational-control-stage-evidence/1.0", "evidence_kind": "direct_durability_measurement", "source": {"control_source_manifest": current_source_manifest(root, matrix)}, "records": [stage_record("pxui.demo.persistence.authoritativeState")]})
    result = assemble(root, ui, [receipt])
    assert result["control_chains"]["aggregates"]["complete_interaction_chains"] == 2


def test_complete_direct_observation_does_not_require_an_edit_attempt(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    value = json.loads(ui.read_text(encoding="utf-8"))
    record = value["records"][0]
    record["attempted"] = False
    record["observed"] = True
    write(ui, value)

    result = assemble(root, ui, [])
    records = {item["control_id"]: item for item in result["control_chains"]["controls"]}

    assert records["pxui.demo.field.name"]["terminal_disposition"] == "interaction_complete"
    assert result["control_chains"]["aggregates"]["observed_control_count"] == 1


def test_contextual_evidence_and_cross_denominator_ids_fail_closed(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    contextual = root / "contextual.json"
    matrix = json.loads((root / "registry/operational_control_proof_matrix.json").read_text(encoding="utf-8"))
    source = {"control_source_manifest": current_source_manifest(root, matrix)}
    write(contextual, {"schema_version": "px.operational-control-stage-evidence/1.0", "evidence_kind": "generic_passing_tests", "source": source, "records": []})
    with pytest.raises(ValueError, match="contextual"):
        assemble(root, ui, [contextual])
    write(contextual, {"schema_version": "px.operational-control-stage-evidence/1.0", "evidence_kind": "direct_durability_measurement", "source": source, "records": [stage_record("pxui.other.persistence.state")]})
    with pytest.raises(ValueError, match="outside the denominator"):
        assemble(root, ui, [contextual])


def test_source_path_accepts_numeric_and_semantic_anchors() -> None:
    assert _source_path("extension/src/panel.ts:12-18") == "extension/src/panel.ts"
    assert _source_path("extension/package.json:contributes.commands") == "extension/package.json"
    assert _source_path("extension/package.json") == "extension/package.json"


def test_current_source_owned_host_measurement_is_direct(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    receipt = root / "owned-host.json"
    matrix = json.loads((root / "registry/operational_control_proof_matrix.json").read_text(encoding="utf-8"))
    write(receipt, {"schema_version": "px.operational-control-stage-evidence/1.0", "evidence_kind": "direct_current_source_host_measurement", "source": {"control_source_manifest": current_source_manifest(root, matrix)}, "records": [stage_record("pxui.demo.persistence.authoritativeState")]})
    result = assemble(root, ui, [receipt])
    assert result["control_chains"]["aggregates"]["complete_interaction_chains"] == 2


def test_stale_or_unbound_receipts_fail_closed(tmp_path: Path) -> None:
    root, ui = fixture(tmp_path)
    value = json.loads(ui.read_text(encoding="utf-8"))
    del value["source"]["control_source_manifest"]
    write(ui, value)
    with pytest.raises(ValueError, match="absent or stale"):
        assemble(root, ui, [])
    root, ui = fixture(tmp_path / "stale")
    (root / "source.js").write_text("changed after observation", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or stale"):
        assemble(root, ui, [])
