from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime import plan_registry as plans

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    policy = json.loads((ROOT / "policies/rev1xx-validation.json").read_text())
    policy.pop("status_overlay", None)
    # A new fixture campaign cannot inherit a different host's registration.
    policy.pop("foundation_status_authority", None)
    paths = ["registry/punch_card_ledger.json", policy["canonical_waves"]["path"]]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps(policy))
    return tmp_path


def test_fresh_campaign_requires_no_historical_status_or_receipt(tmp_path):
    root = fixture(tmp_path)
    result = plans.begin_plan_campaign(root)
    assert result["valid"]
    assert result["planned_card_count"] == 60
    assert result["accepted_card_count"] == 0
    assert result["execution_ready"] == ["BASE-001"]
    assert not (root / "evidence").exists()
    report = plans.readiness_report(root)
    assert report["valid"]
    assert report["accepted_card_count"] == 0


def test_old_status_is_untouched_and_cannot_grant_current_acceptance(tmp_path):
    root = fixture(tmp_path)
    legacy = root / "registry/punch_card_status.json"
    legacy.write_bytes(b"unreadable historical status; no validation authority")
    before = legacy.read_bytes()
    plans.begin_plan_campaign(root)
    assert legacy.read_bytes() == before
    assert plans.readiness_report(root)["accepted_card_count"] == 0


def test_repeat_start_is_idempotent(tmp_path):
    root = fixture(tmp_path)
    plans.begin_plan_campaign(root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert plans.begin_plan_campaign(root)["idempotent"]
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_start_cannot_erase_current_card_progress(tmp_path):
    root = fixture(tmp_path)
    plans.begin_plan_campaign(root)
    target = root / plans.CURRENT_STATUS_RELATIVE
    value = json.loads(target.read_text())
    value["cards"] = {"BASE-001": {"status": "in_progress"}}
    target.write_text(json.dumps(value))
    before = target.read_bytes()
    with pytest.raises(plans.PlanRegistryError, match="reset current campaign progress"):
        plans.begin_plan_campaign(root)
    assert target.read_bytes() == before


def test_current_inputs_change_requires_new_planned_context(tmp_path):
    root = fixture(tmp_path)
    plans.begin_plan_campaign(root)
    policy_path = root / "policies/rev1xx-validation.json"
    value = json.loads(policy_path.read_text())
    value["current_owner_note"] = "updated current requirements"
    policy_path.write_text(json.dumps(value))
    assert plans.readiness_report(root)["valid"] is False
    result = plans.begin_plan_campaign(root)
    assert result["accepted_card_count"] == 0
    assert result["idempotent"] is False
    assert plans.readiness_report(root)["valid"]
    assert list((root / "registry/planning/rev1xx/status-history").glob("*.json"))


def test_current_overlay_cannot_self_assert_accepted(tmp_path):
    root = fixture(tmp_path)
    plans.begin_plan_campaign(root)
    path = root / plans.CURRENT_STATUS_RELATIVE
    value = json.loads(path.read_text())
    value["cards"]["BASE-001"] = {"prior_status": "partial_verified", "status": "accepted", "owner_decision": "self-declared", "evidence": [], "acceptance": []}
    path.write_text(json.dumps(value))
    report = plans.readiness_report(root)
    assert report["valid"] is False
    assert report["execution_ready"] == []


def test_fresh_start_requires_explicit_owner_policy(tmp_path):
    root = fixture(tmp_path)
    path = root / "policies/rev1xx-validation.json"
    value = json.loads(path.read_text())
    value["authority"] = "overlay says PASS"
    path.write_text(json.dumps(value))
    with pytest.raises(plans.PlanRegistryError, match="explicit owner authority"):
        plans.begin_plan_campaign(root)
    assert not (root / plans.CURRENT_STATUS_RELATIVE).exists()


def test_normal_cli_start_and_readiness_use_current_campaign(tmp_path, capsys):
    from runtime.cli import main
    root = fixture(tmp_path)
    assert main(["--root", str(root), "plan-start"]) == 0
    assert json.loads(capsys.readouterr().out)["accepted_card_count"] == 0
    assert main(["--root", str(root), "plan-readiness"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["execution_ready"] == ["BASE-001"]
