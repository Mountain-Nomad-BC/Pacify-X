from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES
from scripts.build_installed_probe_control_evidence import build


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def owned_receipt(tmp_path: Path, *, host_errors: list[object] | None = None) -> Path:
    policy = {stage: "required" for stage in STAGES}
    chain = {stage: {"state": "present", "detail": f"direct {stage}", "evidence": ["owned-host"]} for stage in STAGES}
    write(tmp_path / "registry/operational_control_proof_matrix.json", {
        "controls": [{"control_id": "pxui.demo.action.read", "stage_policy": policy}]
    })
    receipt = tmp_path / "receipt.json"
    write(receipt, {
        "schema_version": "px.operational-ui-walk/1.2",
        "host_source_mismatch": False,
        "source_identity": {"state": "verified"},
        "host_errors": host_errors or [],
        "installed_control_probe": {
            "schema_version": "px.installed-operational-control-probe/1.0",
            "bridge_instrumented": True,
            "eligible_control_count": 1,
            "records": [{"control_id": "pxui.demo.action.read", "attempted": True, "rendered": True, "observed": True, "interaction_chain": chain}],
        },
    })
    return receipt


def test_adapts_only_exact_direct_owned_host_stages(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path)
    result = build(tmp_path, receipt, "direct_current_source_host_measurement")
    assert result["evidence_kind"] == "direct_current_source_host_measurement"
    assert result["records"][0]["stages"]["backend_dispatch"]["state"] == "present"
    assert result["source"]["receipt_sha256"]


def test_rejects_host_errors_and_matrix_conflicts(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path, host_errors=[{"message": "failure"}])
    with pytest.raises(ValueError, match="host errors"):
        build(tmp_path, receipt, "direct_current_source_host_measurement")
    receipt = owned_receipt(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["installed_control_probe"]["records"][0]["interaction_chain"]["display"]["state"] = "not_applicable"
    write(receipt, value)
    with pytest.raises(ValueError, match="conflicts with proof matrix"):
        build(tmp_path, receipt, "direct_current_source_host_measurement")


def test_merges_exact_reversible_configuration_profile_without_promoting_missing_fault_stage(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    matrix_path = tmp_path / "registry/operational_control_proof_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["controls"].append({
        "control_id": "pxui.settings.action.toggleBillablePolicy",
        "stage_policy": {stage: "required" for stage in STAGES},
    })
    write(matrix_path, matrix)
    chain = {
        stage: {
            "state": "missing" if stage == "failure_handling" else "present",
            "detail": "fault not injected" if stage == "failure_handling" else f"direct reversible {stage}",
            "evidence": [] if stage == "failure_handling" else ["owned-reversible-host"],
        }
        for stage in STAGES
    }
    value["reversible_configuration_profile"] = {
        "schema_version": "px.installed-operational-control-probe/1.0",
        "eligible_control_count": 1,
        "records": [{
            "control_id": "pxui.settings.action.toggleBillablePolicy",
            "attempted": True,
            "rendered": True,
            "observed": True,
            "interaction_chain": chain,
        }],
    }
    write(receipt, value)

    result = build(tmp_path, receipt, "direct_installed_host_measurement")

    assert len(result["records"]) == 2
    configured = next(record for record in result["records"] if record["control_id"].endswith("toggleBillablePolicy"))
    assert configured["stages"]["recovery_rollback"]["state"] == "present"
    assert configured["stages"]["failure_handling"]["state"] == "missing"
