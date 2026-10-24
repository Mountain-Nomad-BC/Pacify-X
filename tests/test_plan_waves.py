from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from runtime import plan_registry as plans

ROOT = Path(__file__).resolve().parents[1]
WAVE_PATH = "registry/planning/rev1xx/waves-fb4e708aea5010da1166f7defc80c0758270ff30922dd5a752ee5f791db038fa.json"
CARD_PATH = "registry/planning/rev1xx/be9857ee72e6a91d6bb70c8088a0d52749be84d3a68ad6e84b93e2a464f90ff3.json"


def inputs():
    return json.loads((ROOT / WAVE_PATH).read_text()), plans.build_card_ledger(plans.load_cards(ROOT / CARD_PATH))


def fixture(tmp_path):
    spec, ledger = inputs()
    target = tmp_path / WAVE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / WAVE_PATH).read_bytes())
    (tmp_path / "registry/punch_card_ledger.json").write_text(json.dumps(ledger))
    (tmp_path / "policies").mkdir()
    policy = {"canonical_waves": {"path": WAVE_PATH, "sha256": "fb4e708aea5010da1166f7defc80c0758270ff30922dd5a752ee5f791db038fa"}}
    (tmp_path / "policies/rev1xx-validation.json").write_text(json.dumps(policy))
    return spec, ledger, target


def test_all_sixty_cards_use_locked_numeric_wave_order():
    spec, ledger = inputs()
    result = plans.build_wave_map(spec, ledger)
    assert result["wave_order"] == [f"W{i}" for i in range(12)]
    assert result["waves"][2]["name"] == "Transactional remap and migration compiler"
    assert result["waves"][2]["cards"] == [f"MIG-{i:03d}" for i in range(1, 6)]
    assert sum(len(wave["cards"]) for wave in result["waves"]) == 60
    assert "execution_ready" not in result


@pytest.mark.parametrize("mutation", ["missing-W2", "renumber", "wrong-prerequisite", "empty-name", "extra-field", "wrong-version"])
def test_stale_or_incomplete_wave_metadata_fails_closed(mutation):
    spec, ledger = inputs()
    if mutation == "missing-W2":
        spec["waves"].pop(2)
    elif mutation == "renumber":
        spec["waves"][2]["id"] = "W3"
    elif mutation == "wrong-prerequisite":
        spec["waves"][3]["depends_on"] = ["W1"]
    elif mutation == "empty-name":
        spec["waves"][2]["name"] = ""
    elif mutation == "extra-field":
        spec["waves"][2]["accepted"] = True
    else:
        spec["schema_version"] = "old-recovery-waves"
    with pytest.raises(plans.PlanRegistryError):
        plans.build_wave_map(spec, ledger)


def test_card_dependency_cannot_reach_into_future_wave():
    spec, _ = inputs()
    entries = {entry.card_id: entry for entry in plans.load_cards(ROOT / CARD_PATH)}
    ledger = plans.build_card_ledger([
        replace(entries["BASE-001"], depends_on=("SEM-001",)),
        replace(entries["SEM-001"], depends_on=()),
    ])
    with pytest.raises(plans.PlanRegistryError, match="later wave"):
        plans.build_wave_map(spec, ledger)


def test_normal_cli_uses_only_admitted_map_and_is_read_only(tmp_path, capsys):
    from runtime.cli import main
    fixture(tmp_path)
    (tmp_path / "registry/stale_recovery_waves.json").write_text('{"W2":"execution"}')
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main(["--root", str(tmp_path), "plan-waves"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["valid"]
    assert result["waves"][2]["cards"] == [f"MIG-{i:03d}" for i in range(1, 6)]
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_wave_report_rejects_changed_normative_bytes(tmp_path):
    _, _, target = fixture(tmp_path)
    target.write_text('{"schema_version":"px.rev1xx-waves/1.0","waves":[]}')
    result = plans.wave_report(tmp_path)
    assert result["valid"] is False
    assert result["waves"] == []
    assert "digest mismatch" in result["errors"][0]


def test_wave_report_rejects_external_input_binding(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "policies/rev1xx-validation.json"
    value = json.loads(path.read_text())
    value["canonical_waves"]["path"] = "../outside.json"
    path.write_text(json.dumps(value))
    assert plans.wave_report(tmp_path)["valid"] is False
