import json
from pathlib import Path
import tempfile

from runtime.full_repair import EXPECTED_IDS, validate_full_repair_ledger


ROOT = Path(__file__).resolve().parents[1]


def test_full_repair_ledger_maps_every_controlling_audit_card() -> None:
    result = validate_full_repair_ledger(ROOT)
    assert result["valid"], result["errors"]
    assert result["card_count"] == len(EXPECTED_IDS) == 42
    assert result["passed"] == 42
    assert result["in_progress"] == 0
    assert result["open"] == 0


def test_full_repair_ledger_accepts_every_card_with_executed_receipts() -> None:
    result = validate_full_repair_ledger(ROOT, require_all_passed=True)
    assert result["valid"], result["errors"]


def test_finalizer_pending_allowlist_does_not_pre_pass_publication() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = json.loads(
            (ROOT / "registry/full_repair_ledger.json").read_text(encoding="utf-8")
        )
        for card in ledger["cards"]:
            card["status"] = "open" if card["id"] == "PC-037" else "passed"
            card["receipts"] = ["synthetic-executed-receipt"]
            for relative in [*card["owners"], *card["tests"]]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)
        (root / "registry").mkdir(exist_ok=True)
        (root / "registry/full_repair_ledger.json").write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        strict = validate_full_repair_ledger(root, require_all_passed=True)
        assert not strict["valid"]
        assert any("PC-037: remains open" in error for error in strict["errors"])
        staged = validate_full_repair_ledger(
            root,
            require_all_passed=True,
            allowed_pending=frozenset({"PC-037"}),
        )
        assert staged["valid"], staged["errors"]
