import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.test_profiles import ProcessingOrderBlocked, freeze_repair_campaign
from scripts.verify_repair_operations import produce_operational_verification


def test_direct_script_entrypoint_imports_runtime_from_outside_project(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_repair_operations.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--project" in result.stdout


def _project(tmp_path, *, phase="operational_verification", unresolved=None):
    marker = tmp_path / ".engineering-bootstrap/project-record.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"project_id": "operational-test"}) + "\n", encoding="utf-8")
    campaign = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
    campaign.parent.mkdir(parents=True)
    campaign.write_text(json.dumps({
        "schema_version": "px.repair-campaign/1.0",
        "campaign_id": "operational-test-campaign",
        "phase": phase,
        "intake_open": phase != "operational_verification",
        "unresolved": unresolved or [],
    }) + "\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.9.0"\n', encoding="utf-8")
    extension = tmp_path / "extension"
    extension.mkdir()
    (extension / "package.json").write_text('{"version":"0.9.0"}\n', encoding="utf-8")
    (extension / "package-lock.json").write_text(
        '{"version":"0.9.0","packages":{"":{"version":"0.9.0"}}}\n', encoding="utf-8"
    )
    return campaign


def test_operational_producer_writes_independent_hash_bound_checks_accepted_by_freeze(tmp_path, monkeypatch):
    campaign = _project(tmp_path)
    state_digest = hashlib.sha256(campaign.read_bytes()).hexdigest()
    result = produce_operational_verification(tmp_path)
    assert result["valid"] is True
    assert result["campaign_state_sha256"] == state_digest
    assert len(result["checks"]) == 4
    for check in result["checks"]:
        artifact = tmp_path / check["artifact"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == check["artifact_sha256"]
    event_id = "gap-event:test:admitted"
    campaign_path = (tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json").resolve().as_posix()
    monkeypatch.setattr("runtime.operational_gap_ledger.read_snapshot", lambda _root: {
        "work_checkpoints": [{"event_id": "checkpoint:test", "active_gap_id": "PX-TEST"}],
        "work_admissions": [{
            "event_id": event_id, "sequence": 2, "gap_id": "PX-TEST",
            "session_id": "test-session", "expires_utc": "2099-01-01T00:00:00Z",
            "effect_scopes": [{"effect": "write", "scope": [campaign_path]}],
        }],
        "work_session_closures": [],
    })
    frozen = freeze_repair_campaign(tmp_path, admission_event_id=event_id, evidence_path=result["receipt"])
    assert frozen["phase"] == "repair_frozen"


def test_operational_producer_rejects_open_or_unresolved_intake_without_receipt(tmp_path):
    _project(tmp_path, phase="repair", unresolved=["outstanding"])
    with pytest.raises(ProcessingOrderBlocked, match="closed zero-denominator"):
        produce_operational_verification(tmp_path)
    assert not (tmp_path / ".engineering-bootstrap/processing-order/operational-verification").exists()


def test_operational_producer_retains_failing_artifact_and_freeze_rejects_it(tmp_path):
    _project(tmp_path)
    (tmp_path / "extension/package.json").write_text('{"version":"0.7.0"}\n', encoding="utf-8")
    result = produce_operational_verification(tmp_path)
    assert result["valid"] is False
    failed = [check for check in result["checks"] if not check["passed"]]
    assert [check["name"] for check in failed] == ["version-alignment"]
    assert (tmp_path / failed[0]["artifact"]).is_file()
    with pytest.raises(ProcessingOrderBlocked, match="not passing"):
        freeze_repair_campaign(
            tmp_path, admission_event_id="gap-event:ledger:000011", evidence_path=result["receipt"]
        )
