import copy
import json
from pathlib import Path
import shutil
import shlex

from runtime.corrective_release import SOURCE_CARD_IDS, validate_corrective_ledger
from runtime.cli import parser


ROOT = Path(__file__).resolve().parents[1]


def test_complete_source_card_denominator_and_child_finding_are_visible():
    result = validate_corrective_ledger(ROOT)
    assert result["valid"], result["errors"]
    assert result["source_cards"] == len(SOURCE_CARD_IDS) == 23
    assert result["children"] == 12


def test_blocking_card_gate_matches_the_project_lifecycle():
    result = validate_corrective_ledger(ROOT, require_blocking_passed=True)
    state = json.loads((ROOT / ".engineering-bootstrap/project-management/state.json").read_text(encoding="utf-8"))
    if state["lifecycle"]["status"] == "complete":
        assert result["valid"], result["errors"]
    else:
        assert not result["valid"]
        assert any("blocking card" in error for error in result["errors"])


def test_closed_card_requires_existing_receipt(tmp_path):
    product = tmp_path / "product"
    (product / "registry").mkdir(parents=True)
    ledger = json.loads((ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(ledger)
    card = next(item for item in mutated["cards"] if item["id"] == "REG-010-A")
    card["status"] = "passed"
    card["receipts"] = []
    (product / "registry/corrective_release_ledger.json").write_text(json.dumps(mutated), encoding="utf-8")
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any("closed status requires receipts" in error for error in result["errors"])


def test_omitted_source_card_fails_closed(tmp_path):
    product = tmp_path / "product"
    (product / "registry").mkdir(parents=True)
    ledger = json.loads((ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8"))
    ledger["cards"] = [card for card in ledger["cards"] if card["id"] != "SEC-010-B"]
    ledger["card_count"] -= 1
    (product / "registry/corrective_release_ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any("source-card denominator mismatch" in error for error in result["errors"])


def test_missing_owner_and_stale_cli_acceptance_command_fail_closed(tmp_path):
    product = tmp_path / "product"
    shutil.copytree(ROOT, product)
    ledger_path = product / "registry/corrective_release_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["cards"][0]["owning_paths"] = ["runtime/does_not_exist.py"]
    ledger["cards"][0]["acceptance_commands"] = ["engineering-bootstrap release summary"]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any("owning path does not exist" in item for item in result["errors"])
    assert any("not supported by the CLI" in item for item in result["errors"])


def test_every_declared_cli_acceptance_command_parses_in_the_real_cli():
    ledger = json.loads((ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8"))
    for card in ledger["cards"]:
        for command in card["acceptance_commands"]:
            tokens = shlex.split(command, posix=False)
            if tokens[0] == "engineering-bootstrap":
                parser().parse_args(tokens[1:])
            elif tokens[:3] == ["python", "-m", "runtime.cli"]:
                parser().parse_args(tokens[3:])


def test_deployment_certified_lifecycle_requires_and_accepts_all_blockers_passed(tmp_path):
    product = tmp_path / "product"
    shutil.copytree(ROOT, product)
    receipt = product / "evidence/test-all-blockers-passed.json"
    receipt.write_text('{"valid":true}\n', encoding="utf-8")
    (product / "evidence/release-certification-0.6.2.json").write_text('{"status":"staging"}\n', encoding="utf-8")
    ledger_path = product / "registry/corrective_release_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for card in ledger["cards"]:
        card["status"] = "passed"
        card["receipts"] = ["evidence/test-all-blockers-passed.json"]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    state_path = product / ".engineering-bootstrap/project-management/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["lifecycle"]["status"] = "complete"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = validate_corrective_ledger(product, require_blocking_passed=True)
    assert result["valid"], result["errors"]
