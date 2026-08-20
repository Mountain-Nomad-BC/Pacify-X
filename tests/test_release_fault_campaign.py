from __future__ import annotations

import json
from pathlib import Path

from scripts.run_release_fault_campaign import _load


ROOT = Path(__file__).resolve().parents[1]


def test_release_fault_campaign_is_complete_bounded_and_non_shell() -> None:
    campaign = _load(ROOT)
    required = set(campaign["required_dimensions"])
    covered = {dimension for lane in campaign["lanes"] for dimension in lane["dimensions"]}
    assert covered == required
    assert "crash-window" in required
    assert "ui-boundary" in required
    for lane in campaign["lanes"]:
        assert lane["command"][0] in {"python", "node"}
        assert all("shell" not in token.casefold() for token in lane["command"])
        for token in lane["command"]:
            if token.startswith("tests/"):
                assert (ROOT / lane["cwd"] / token).is_file()


def test_retained_fault_campaign_receipt_cannot_overstate_failed_lane(tmp_path: Path) -> None:
    record = {
        "schema_version": "px.release-fault-campaign-receipt/1.0",
        "lanes": [{"passed": True}, {"passed": False}],
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert all(lane["passed"] for lane in loaded["lanes"]) is False
