from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES
from scripts.build_installed_host_control_evidence import build


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "extension/evidence/installed-vsix-smoke.json"
CURRENT_VSIX = ROOT / "extension/dist" / json.loads(RECEIPT.read_text(encoding="utf-8"))["artifact"]["name"]


def _portable_installed_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "product"
    matrix = root / "registry" / "operational_control_proof_matrix.json"
    matrix.parent.mkdir(parents=True)
    matrix.write_bytes((ROOT / "registry/operational_control_proof_matrix.json").read_bytes())
    artifact = root / "extension" / "dist" / "pacify-x-test.vsix"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"portable installed-host fixture\n")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt["artifact"].update(
        {
            "name": artifact.name,
            "unchanged": True,
            "sha256_before": digest,
            "sha256_after": digest,
        }
    )
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


def test_current_host_receipt_remains_bound_when_retained_vsix_is_available() -> None:
    if not CURRENT_VSIX.is_file():
        pytest.skip("retained installed VSIX is external host custody")
    result = build(ROOT, RECEIPT, CURRENT_VSIX)
    assert len(result["records"]) == 12
