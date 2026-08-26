from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES, current_source_manifest
from scripts.build_installed_probe_control_evidence import build


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def owned_receipt(tmp_path: Path, *, host_errors: list[object] | None = None) -> Path:
    policy = {stage: "required" for stage in STAGES}
    chain = {stage: {"state": "present", "detail": f"direct {stage}", "evidence": ["owned-host"]} for stage in STAGES}
    (tmp_path / "source.js").write_text("current owned-host source", encoding="utf-8")
    matrix = {"controls": [{"control_id": "pxui.demo.action.read", "stage_policy": policy, "source_refs": ["source.js:1"]}]}
    write(tmp_path / "registry/operational_control_proof_matrix.json", matrix)
    receipt = tmp_path / "receipt.json"
    write(receipt, {
        "schema_version": "px.operational-ui-walk/1.2",
        "host_source_mismatch": False,
        "source_identity": {"state": "verified", "control_source_manifest": current_source_manifest(tmp_path, matrix)},
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
        "source_refs": ["source.js:1"],
    })
    write(matrix_path, matrix)
    value["source_identity"]["control_source_manifest"] = current_source_manifest(tmp_path, matrix)
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


def test_merges_studio_profiles_and_combines_compatible_duplicate_stage_evidence(
    tmp_path: Path,
) -> None:
    receipt = owned_receipt(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    matrix_path = tmp_path / "registry/operational_control_proof_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    for control_id in ("pxui.agent-studio.action.setupStudio", "pxui.studio-lifecycle.action.openStudioFromCatalog"):
        matrix["controls"].append({
            "control_id": control_id,
            "stage_policy": {stage: "required" for stage in STAGES},
            "source_refs": ["source.js:1"],
        })
    write(matrix_path, matrix)
    value["source_identity"]["control_source_manifest"] = current_source_manifest(tmp_path, matrix)

    def direct_chain(prefix: str, missing: set[str] | None = None) -> dict[str, object]:
        missing = missing or set()
        return {
            stage: {
                "state": "missing" if stage in missing else "present",
                "detail": f"{prefix} {stage}",
                "evidence": [] if stage in missing else [prefix],
            }
            for stage in STAGES
        }

    value["studio_setup_profile"] = {
        "schema_version": "px.installed-operational-control-probe/1.0",
        "eligible_control_count": 1,
        "records": [{
            "control_id": "pxui.agent-studio.action.setupStudio",
            "attempted": True,
            "rendered": True,
            "observed": True,
            "interaction_chain": direct_chain("setup", {"failure_handling"}),
        }],
    }
    value["studio_revision_edit_profile"] = {
        "schema_version": "px.installed-studio-revision-edit-profile/1.0",
        "control_probe": {
            "schema_version": "px.installed-operational-control-probe/1.0",
            "eligible_control_count": 2,
            "records": [
                {
                    "control_id": "pxui.agent-studio.action.setupStudio",
                    "attempted": True,
                    "rendered": True,
                    "observed": True,
                    "interaction_chain": direct_chain("edit", {"runtime_effect"}),
                },
                {
                    "control_id": "pxui.studio-lifecycle.action.openStudioFromCatalog",
                    "attempted": True,
                    "rendered": True,
                    "observed": True,
                    "interaction_chain": direct_chain("reopen"),
                },
            ],
        },
    }
    write(receipt, value)

    result = build(tmp_path, receipt, "direct_current_source_host_measurement")

    assert len(result["records"]) == 3
    setup = next(record for record in result["records"] if record["control_id"].endswith("setupStudio"))
    assert setup["stages"]["failure_handling"]["state"] == "present"
    assert setup["stages"]["runtime_effect"]["state"] == "present"
    assert setup["stages"]["display"]["evidence"] == ["setup", "edit"]
    assert any(record["control_id"].endswith("openStudioFromCatalog") for record in result["records"])


def test_rejects_invalid_nested_studio_profile_denominator(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["studio_lifecycle_profile"] = {
        "schema_version": "px.installed-studio-lifecycle-profile/1.0",
        "control_probe": {
            "schema_version": "px.installed-operational-control-probe/1.0",
            "eligible_control_count": 1,
            "records": [],
        },
    }
    write(receipt, value)
    with pytest.raises(ValueError, match="studio_lifecycle_profile denominator"):
        build(tmp_path, receipt, "direct_current_source_host_measurement")


def test_merges_engine_outage_and_knowledge_lifecycle_profiles(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    matrix_path = tmp_path / "registry/operational_control_proof_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    control_ids = (
        "pxui.dashboard.action.refresh",
        "pxui.knowledge-core.action.rebuildKnowledgeIndex",
    )
    for control_id in control_ids:
        matrix["controls"].append({
            "control_id": control_id,
            "stage_policy": {stage: "required" for stage in STAGES},
            "source_refs": ["source.js:1"],
        })
    write(matrix_path, matrix)
    value["source_identity"]["control_source_manifest"] = current_source_manifest(tmp_path, matrix)

    def direct_chain(prefix: str) -> dict[str, object]:
        return {
            stage: {
                "state": "present",
                "detail": f"{prefix} {stage}",
                "evidence": [prefix],
            }
            for stage in STAGES
        }

    value["engine_outage_profile"] = {
        "schema_version": "px.installed-operational-control-probe/1.0",
        "eligible_control_count": 1,
        "records": [{
            "control_id": control_ids[0],
            "attempted": True,
            "rendered": True,
            "observed": True,
            "interaction_chain": direct_chain("engine-outage"),
        }],
    }
    value["knowledge_lifecycle_profile"] = {
        "schema_version": "px.installed-knowledge-lifecycle-profile/1.0",
        "control_probe": {
            "schema_version": "px.installed-operational-control-probe/1.0",
            "eligible_control_count": 1,
            "records": [{
                "control_id": control_ids[1],
                "attempted": True,
                "rendered": True,
                "observed": True,
                "interaction_chain": direct_chain("knowledge-lifecycle"),
            }],
        },
    }
    write(receipt, value)

    result = build(tmp_path, receipt, "direct_installed_host_measurement")

    adapted = {record["control_id"]: record for record in result["records"]}
    assert adapted[control_ids[0]]["stages"]["recovery_rollback"]["state"] == "present"
    assert adapted[control_ids[1]]["stages"]["persistence"]["state"] == "present"


def test_rejects_stale_control_source_identity(tmp_path: Path) -> None:
    receipt = owned_receipt(tmp_path)
    (tmp_path / "source.js").write_text("changed after host observation", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or stale"):
        build(tmp_path, receipt, "direct_current_source_host_measurement")
