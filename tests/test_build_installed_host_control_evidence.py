from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES
from scripts.build_installed_host_control_evidence import build


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "extension/evidence/installed-vsix-smoke.json"


def _current_vsix() -> Path | None:
    if not RECEIPT.is_file():
        return None
    return ROOT / "extension/dist" / json.loads(
        RECEIPT.read_text(encoding="utf-8")
    )["artifact"]["name"]


def _portable_installed_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "product"
    matrix = root / "registry" / "operational_control_proof_matrix.json"
    matrix.parent.mkdir(parents=True)
    source = root / "source.js"
    source.write_text("current installed control source", encoding="utf-8")
    wanted = {
        "pxui.agent-studio.persistence.authoritativeState", "pxui.agent-studio.reload_reopen.authoritativeState",
        "pxui.agents.persistence.authoritativeState", "pxui.agents.reload_reopen.authoritativeState",
        "pxui.workflow-studio.persistence.authoritativeState", "pxui.workflow-studio.reload_reopen.authoritativeState",
        "pxui.workflows.persistence.authoritativeState", "pxui.workflows.reload_reopen.authoritativeState",
        "pxui.studio-lifecycle.lifecycle.path.1", "pxui.studio-lifecycle.lifecycle.path.2",
        "pxui.skill-studio.persistence.authoritativeState", "pxui.sidebar.acknowledgement.surface",
    }
    current = json.loads((ROOT / "registry/operational_control_proof_matrix.json").read_text(encoding="utf-8"))
    controls = [{**item, "source_refs": ["source.js:1"]} for item in current["controls"] if item["control_id"] in wanted]
    assert len(controls) == 12
    matrix.write_text(json.dumps({"control_count": len(controls), "controls": controls}), encoding="utf-8")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    engine_identity = {"file_total": 1, "tree_sha256": "1" * 64, "records": [{"path": "source.js", "sha256": source_sha, "bytes": source.stat().st_size}]}
    identity_path = root / "registry" / "engine_identity.json"
    identity_path.write_text(json.dumps(engine_identity), encoding="utf-8")
    artifact = root / "extension" / "dist" / "pacify-x-test.vsix"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"portable installed-host fixture\n")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipt = {
        "schema_version": "px.installed-vsix-certification/1.1",
        "artifact": {
            "name": artifact.name,
            "unchanged": True,
            "sha256_before": digest,
            "sha256_after": digest,
        },
        "engine_connected": True,
        "engine_identity": {"manifest_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(), "tree_sha256": engine_identity["tree_sha256"], "file_total": 1},
        "process_lifecycle": {
            "worker_exit_verified": True,
            "process_tree_closed_verified": True,
            "exit_code": 0,
        },
        "host": {
            "exact_studio_round_trips": {
                "setup_ready": True,
                "agent": {
                    "admission": "admitted",
                    "reopen_authenticated": True,
                    "run_outcome": "succeeded",
                },
                "workflow": {
                    "admission": "admitted",
                    "reopen_authenticated": True,
                    "run_state": "succeeded",
                },
                "skill": {"save_status": "created", "content_bound": True},
            },
            "live_sidebar": {
                "provider": {
                    "resolved": True,
                    "visible": True,
                    "html_assigned": True,
                    "ready_count": 1,
                    "render_ack_count": 1,
                    "contract_rejection_count": 0,
                    "operation_error_count": 0,
                }
            },
        },
    }
    receipt_path = root / "extension" / "evidence" / "installed-vsix-smoke.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return root, receipt_path, artifact


def test_exact_installed_receipt_maps_only_narrow_observed_stages(
    tmp_path: Path,
) -> None:
    root, receipt, artifact = _portable_installed_fixture(tmp_path)
    result = build(root, receipt, artifact)
    records = {item["control_id"]: item for item in result["records"]}
    assert len(records) == 12
    sidebar = records["pxui.sidebar.acknowledgement.surface"]
    assert sidebar["rendered"] is True
    assert sidebar["stages"]["result_acknowledgement"]["state"] == "present"
    persistence = records["pxui.agent-studio.persistence.authoritativeState"]
    assert persistence["stages"]["persistence"]["state"] == "present"
    assert persistence["stages"]["reload_reopen"]["state"] == "present"
    assert persistence["stages"]["display"]["state"] == "missing"
    assert persistence["stages"]["failure_handling"]["state"] == "missing"
    assert set(persistence["stages"]) == set(STAGES)


def test_artifact_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    root, target, artifact = _portable_installed_fixture(tmp_path)
    receipt = json.loads(target.read_text(encoding="utf-8"))
    receipt["artifact"]["sha256_after"] = "0" * 64
    target.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="exact retained VSIX"):
        build(root, target, artifact)


def test_stale_engine_control_source_fails_closed(tmp_path: Path) -> None:
    root, target, artifact = _portable_installed_fixture(tmp_path)
    (root / "source.js").write_text("source changed after host run", encoding="utf-8")
    with pytest.raises(ValueError, match="engine identity is absent or stale"):
        build(root, target, artifact)


def test_retained_host_receipt_is_current_or_explicitly_stale() -> None:
    current_vsix = _current_vsix()
    if current_vsix is None or not current_vsix.is_file():
        pytest.skip("retained installed VSIX is external host custody")
    try:
        result = build(ROOT, RECEIPT, current_vsix)
    except ValueError as error:
        assert str(error) == "installed-host receipt engine identity is absent or stale"
        return
    assert len(result["records"]) == 12
