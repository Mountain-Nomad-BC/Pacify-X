"""Compatibility paths must invoke the canonical certification owner."""
import importlib
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "build_release_successor_configs", "pre_candidate_hygiene",
    "reconcile_cohesion_cards", "reconcile_unverified_operational_controls",
    "run_installed_operational_owner", "run_release_candidate",
    "run_release_candidate_dry", "run_release_stage_owner",
    "validate_certification_pipeline",
)

@pytest.mark.parametrize("name", SCRIPTS)
def test_compatibility_import_is_the_canonical_module(name):
    canonical = importlib.import_module("scripts." + name)
    compatibility = importlib.import_module("px.py_cert.scripts." + name)
    assert compatibility is canonical
    assert compatibility.main is canonical.main
    assert Path(compatibility.__file__).resolve() == ROOT / "scripts" / (name + ".py")

def test_certification_constants_use_one_native_owner():
    canonical = importlib.import_module("runtime.certification_contract")
    compatibility = importlib.import_module("px.py_cert.runtime.certification_contract")
    assert compatibility is canonical
    assert compatibility.RELEASE_STAGES is canonical.RELEASE_STAGES

@pytest.mark.parametrize("name", SCRIPTS)
def test_compatibility_cli_delegates_arguments_exit_and_globals(name, monkeypatch):
    canonical = importlib.import_module("scripts." + name)
    calls = []
    arguments = [str(ROOT / "px/py_cert/scripts" / (name + ".py")), "--sentinel"]
    def main():
        calls.append(tuple(sys.argv))
        return 23
    monkeypatch.setattr(canonical, "main", main)
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(arguments[0], run_name="__main__")
    assert stopped.value.code == 23
    assert calls == [tuple(arguments)]

def test_stage_owner_help_works_through_direct_compatibility_script():
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "px/py_cert/scripts/run_release_stage_owner.py"), "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "--config" in result.stdout


def test_release_campaign_compatibility_uses_current_native_module_and_policy(tmp_path):
    """Observational API only: no release stage, identity apply or certification."""
    import hashlib
    import json
    canonical=importlib.import_module("runtime.release_campaign")
    compatibility=importlib.import_module("px.py_cert.runtime.release_campaign")
    assert compatibility is canonical
    assert compatibility.ReleaseCampaignBlocked is canonical.ReleaseCampaignBlocked
    assert compatibility.release_state_relative is canonical.release_state_relative
    assert compatibility.release_campaign_status is canonical.release_campaign_status
    assert Path(compatibility.__file__).resolve()==ROOT/"runtime/release_campaign.py"
    assert compatibility.release_state_relative(tmp_path)==canonical.STATE_PATH
    (tmp_path/"policies").mkdir()
    policy={"schema_version":"px.validation-basis/1.0","basis":"current_implementation",
        "authority":"OWNER-FRESH-VALIDATION-001","campaign_id":"disposable-adapter-campaign"}
    (tmp_path/"policies/rev1xx-validation.json").write_text(json.dumps(policy))
    expected=Path(".agentic_engineering_os_px/processing-order/current-campaigns")/hashlib.sha256(policy["campaign_id"].encode()).hexdigest()/"release-identity.json"
    assert compatibility.release_state_relative(tmp_path)==expected
    assert not (tmp_path/expected).exists()
    policy["authority"]="caller-without-owner-authority"
    (tmp_path/"policies/rev1xx-validation.json").write_text(json.dumps(policy))
    from runtime.plan_registry import PlanRegistryError
    with pytest.raises(PlanRegistryError,match="explicit owner authority"):
        compatibility.release_state_relative(tmp_path)
    assert not (tmp_path/".agentic_engineering_os_px").exists()
