import copy
import json
from pathlib import Path
import shutil
import shlex

from runtime.corrective_release import SOURCE_CARD_IDS, validate_corrective_ledger
from runtime.cli import parser
from tests.repository_copy import canonical_copy_ignore


ROOT = Path(__file__).resolve().parents[1]


def _copy_product(target: Path) -> None:
    ignore = canonical_copy_ignore(
        ROOT,
        ".git",
        ".venv*",
        ".vscode-test",
        "Python",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "quarantine",
        "operation-bus",
        "preserved-extension-installations",
    )

    shutil.copytree(
        ROOT,
        target,
        ignore=ignore,
    )


def test_complete_source_card_denominator_and_child_finding_are_visible():
    result = validate_corrective_ledger(ROOT)
    assert result["valid"], result["errors"]
    assert result["source_cards"] == len(SOURCE_CARD_IDS) == 23
    assert result["children"] == 13


def test_historical_corrective_release_stays_closed_after_intake_validation():
    result = validate_corrective_ledger(ROOT, require_blocking_passed=True)
    state = json.loads(
        (ROOT / ".engineering-bootstrap/project-management/state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["lifecycle"]["status"] in {
        "integration-complete",
        "repair-in-progress",
    }
    assert result["valid"], result["errors"]
    if state["lifecycle"]["status"] == "integration-complete":
        assert state["checkpoint"]["next_safe_action"].startswith(
            "preserve the validated development tree"
        )
    else:
        assert "A08" in state["checkpoint"]["next_safe_action"]
    assert any(
        "REL-013 closed after two matching 4,030-file" in fact
        for fact in state["knowledge"]["facts"]
    )


def test_completed_finalizer_leaves_no_blocking_cards() -> None:
    strict = validate_corrective_ledger(ROOT, require_blocking_passed=True)
    assert strict["valid"], strict["errors"]
    staged = validate_corrective_ledger(
        ROOT,
        require_blocking_passed=True,
        allow_finalizer_in_progress=True,
    )
    assert staged["valid"], staged["errors"]


def test_closed_card_requires_existing_receipt(tmp_path):
    product = tmp_path / "product"
    (product / "registry").mkdir(parents=True)
    ledger = json.loads(
        (ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(ledger)
    card = next(item for item in mutated["cards"] if item["id"] == "REG-010-A")
    card["status"] = "passed"
    card["receipts"] = []
    (product / "registry/corrective_release_ledger.json").write_text(
        json.dumps(mutated), encoding="utf-8"
    )
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any("closed status requires receipts" in error for error in result["errors"])


def test_omitted_source_card_fails_closed(tmp_path):
    product = tmp_path / "product"
    (product / "registry").mkdir(parents=True)
    ledger = json.loads(
        (ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8")
    )
    ledger["cards"] = [card for card in ledger["cards"] if card["id"] != "SEC-010-B"]
    ledger["card_count"] -= 1
    (product / "registry/corrective_release_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any(
        "source-card denominator mismatch" in error for error in result["errors"]
    )


def test_missing_owner_and_stale_cli_acceptance_command_fail_closed(tmp_path):
    product = tmp_path / "product"
    _copy_product(product)
    ledger_path = product / "registry/corrective_release_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["cards"][0]["owning_paths"] = ["runtime/does_not_exist.py"]
    ledger["cards"][0]["acceptance_commands"] = [
        "engineering-bootstrap release summary"
    ]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    result = validate_corrective_ledger(product)
    assert not result["valid"]
    assert any("owning path does not exist" in item for item in result["errors"])
    assert any("not supported by the CLI" in item for item in result["errors"])


def test_every_declared_cli_acceptance_command_parses_in_the_real_cli():
    ledger = json.loads(
        (ROOT / "registry/corrective_release_ledger.json").read_text(encoding="utf-8")
    )
    for card in ledger["cards"]:
        for command in card["acceptance_commands"]:
            tokens = shlex.split(command, posix=False)
            if tokens[0] == "engineering-bootstrap":
                parser().parse_args(tokens[1:])
            elif tokens[:3] == ["python", "-m", "runtime.cli"]:
                parser().parse_args(tokens[3:])


def test_deployment_certified_lifecycle_requires_and_accepts_all_blockers_passed(
    tmp_path,
):
    product = tmp_path / "product"
    _copy_product(product)
    receipt = product / "evidence/test-all-blockers-passed.json"
    receipt.write_text('{"valid":true}\n', encoding="utf-8")
    (product / "evidence/release-certification-0.6.2.json").write_text(
        '{"status":"staging"}\n', encoding="utf-8"
    )
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
