"""Fresh campaign guards; never execute the unsafe original helper bodies."""
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
RETIRED = [
    # Retired legacy helpers. The legacy spelling is deliberate: this test asserts
    # the old control-directory paths are gone and can no longer launch broad
    # checks or unowned deletion.
    ".engineering-bootstrap/tmp/run_auth.ps1",
    ".engineering-bootstrap/tmp/run_iso.ps1",
    ".engineering-bootstrap/tmp/run_broad2.ps1",
    "scripts/cleanup_pytest_ephemerals.ps1",
    "scripts/cleanup_owned_test_ephemerals.ps1",
    "scripts/cleanup_px_generated_test_fixtures.ps1",
]


def test_environment_discovery_does_not_mint_historical_or_certification_authority():
    source = (ROOT / "scripts/cert_env.ps1").read_text(encoding="utf-8-sig")
    assert "PX_COMMENCEMENT_ORCHESTRATION" not in source
    assert not re.search(r"C:\\Users\\", source, re.I)
    assert "certification_verified" in source and "$false" in source
    assert "reconstructed stand-in" not in source


@pytest.mark.parametrize("relative", RETIRED)
def test_legacy_helpers_cannot_launch_broad_checks_or_unowned_deletion(relative):
    source = (ROOT / relative).read_text(encoding="utf-8-sig")
    assert "throw" in source.lower() and "retired" in source.lower()
    assert not re.search(r"\b(?:Remove-Item|regenerate_projections|pytest|Start-Process)\b", source, re.I)
    assert not re.search(r"\[.*?\]::Delete\s*\(", source, re.I)
    assert "$env:TEMP" not in source


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(tmp_path, command):
    from runtime.resource_lifecycle import ResourceManager
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("Native PowerShell unavailable; source guards remain mandatory")
    manager = ResourceManager(tmp_path / "process-ledger.json")
    record, process = manager.spawn_owned_process(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=tmp_path, project_id="powershell-campaign-controls",
        run_id=uuid4().hex, lane_id="focused", creator=__name__,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except BaseException:
        manager.terminate_owned_process(record.resource_id, graceful_timeout_seconds=1)
        raise
    closed = manager.complete_process(record.resource_id)
    assert not closed.active and closed.status == "reclaimed"
    return process.returncode, stdout, stderr


def test_all_repaired_helpers_parse_without_execution(tmp_path):
    paths = RETIRED + ["scripts/cert_env.ps1"]
    command = "$ErrorActionPreference='Stop'; "
    for relative in paths:
        command += (
            "$tokens=$null;$errors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            + _literal(ROOT / relative)
            + ",[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){throw 'PowerShell parse errors'};"
        )
    code, _, errors = _powershell(tmp_path, command)
    assert code == 0, errors


@pytest.mark.parametrize("relative", RETIRED)
def test_retired_helpers_fail_before_any_effect(relative, tmp_path):
    canary = tmp_path / "user-owned-canary.txt"
    canary.write_text("retain this data", encoding="utf-8")
    before = canary.read_bytes()
    code, out, errors = _powershell(tmp_path, "& " + _literal(ROOT / relative))
    assert code != 0 and "retired" in (out + errors).lower()
    assert canary.read_bytes() == before
    assert not list(tmp_path.glob("PX_*.txt"))


def test_tool_discovery_reports_real_tool_without_certification_claim(tmp_path):
    import json
    command = "$result=& " + _literal(ROOT / "scripts/cert_env.ps1") + ";$result|ConvertTo-Json -Depth 6 -Compress"
    code, out, errors = _powershell(tmp_path, command)
    assert code == 0, errors
    report = json.loads(out)
    assert report["certification_verified"] is False
    assert report["historical_artifacts_required"] is False
    assert report["installs_or_builds_performed"] is False
    assert report["tools"][0]["name"] == "python"
    assert Path(report["tools"][0]["path"]).is_file()


def test_missing_tool_discovery_cannot_report_success(tmp_path):
    command = "& " + _literal(ROOT / "scripts/cert_env.ps1") + " -RequiredTools px_nonexistent_campaign_tool_012345"
    code, out, errors = _powershell(tmp_path, command)
    assert code != 0
    assert "unavailable" in (out + errors).lower()
