"""Campaign Phase B1: every authority entry point checks exact ledger bytes."""
import copy
import json

import pytest

from runtime.plan_registry import (
    CardLedgerEntry, PlanRegistryError, apply_status, build_card_ledger,
    ready_cards, validate_ledger, write_card_ledger,
)


def ledger():
    return build_card_ledger([CardLedgerEntry(
        card_id="BASE-001", title="Preserve", wave="W0", owner="runtime/source_freeze.py",
        existing_owners=("runtime/source_freeze.py",), candidate_new_owners=(),
        depends_on=(), acceptance=("Exact bytes retained",), rollback="Restore snapshot",
        source="manifests/punch_cards.json", source_basis="D-001", outcome="Preserved",
    )])


def test_valid_ledger_is_trusted():
    assert validate_ledger(ledger())["valid"]
    assert ready_cards(ledger()) == ["BASE-001"]


@pytest.mark.parametrize("field,value", [
    ("title", "Forged title"), ("owner", "runtime/other.py"),
    ("acceptance", ["No proof needed"]), ("depends_on", ["BASE-001"]),
])
def test_semantic_mutation_cannot_reuse_digest(field, value, tmp_path):
    original = ledger()
    broken = copy.deepcopy(original)
    broken["cards"][0][field] = value
    report = validate_ledger(broken)
    assert not report["valid"]
    assert any("digest" in problem for problem in report["problems"])
    with pytest.raises(PlanRegistryError, match="digest"):
        ready_cards(broken)
    # Missing overlays cannot bypass validation of the base ledger.
    with pytest.raises(PlanRegistryError, match="digest"):
        apply_status(broken, tmp_path / "absent.json")
    assert original == ledger()


def test_digest_is_required():
    broken = ledger()
    del broken["ledger_sha256"]
    assert not validate_ledger(broken)["valid"]
    with pytest.raises(PlanRegistryError, match="digest"):
        ready_cards(broken)


def test_digest_bound_transport_metadata_is_also_checked(tmp_path):
    manifest = tmp_path / "cards.json"
    manifest.write_text(json.dumps({"cards": [{
        "id": "BASE-001", "title": "Preserve", "wave": "W0",
        "existing_owners": ["runtime/source_freeze.py"], "depends_on": [],
        "acceptance": ["Exact bytes retained"], "rollback": "Restore snapshot",
    }]}))
    path = write_card_ledger(manifest, tmp_path)
    value = json.loads(path.read_text())
    assert validate_ledger(value)["valid"]
    value["artifact_sha256"] = "0" * 64
    assert not validate_ledger(value)["valid"]


def test_report_exposes_expected_and_observed_digests():
    value = ledger()
    value["ledger_sha256"] = "0" * 64
    report = validate_ledger(value)
    assert report["observed_ledger_sha256"] == "0" * 64
    assert report["expected_ledger_sha256"] != "0" * 64
