from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.assemble_operational_control_evidence import STAGES
from scripts.build_installed_host_control_evidence import build


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "extension/evidence/installed-vsix-smoke.json"
CURRENT_VSIX = ROOT / "extension/dist" / json.loads(RECEIPT.read_text(encoding="utf-8"))["artifact"]["name"]


def test_current_exact_installed_receipt_maps_only_narrow_observed_stages() -> None:
    result = build(ROOT, RECEIPT, CURRENT_VSIX)
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
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt["artifact"]["sha256_after"] = "0" * 64
    target = tmp_path / "receipt.json"
    target.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="exact retained VSIX"):
        build(ROOT, target, CURRENT_VSIX)
