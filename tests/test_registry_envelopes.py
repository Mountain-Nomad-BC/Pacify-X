import copy
import json
from pathlib import Path

from runtime.registry_envelope import (
    discover_count_fields,
    validate_envelope_document,
    validate_registry_envelopes,
)
from scripts.build_registry_envelope_inventory import build_inventory


ROOT = Path(__file__).resolve().parents[1]


def test_every_count_bearing_registry_field_has_one_owner_and_invariant():
    result = validate_registry_envelopes(ROOT)
    assert result["valid"], result["errors"]
    assert result["record_count"] == len(discover_count_fields(ROOT)) == 47


def test_every_inventoried_count_rejects_deliberate_corruption():
    for record in build_inventory()["records"]:
        payload = json.loads((ROOT / record["path"]).read_text(encoding="utf-8"))
        corrupted = copy.deepcopy(payload)
        corrupted[record["count_key"]] += 1
        assert validate_envelope_document(corrupted, record), (record["path"], record["count_key"])


def test_missing_non_integer_and_empty_collection_are_intentional_failures():
    record = next(item for item in build_inventory()["records"] if item["path"] == "registry/declared_suite_formulas.json")
    payload = json.loads((ROOT / record["path"]).read_text(encoding="utf-8"))
    missing = copy.deepcopy(payload)
    missing.pop("formula_count")
    assert validate_envelope_document(missing, record)
    wrong_type = copy.deepcopy(payload)
    wrong_type["formula_count"] = True
    assert validate_envelope_document(wrong_type, record)
    empty = copy.deepcopy(payload)
    empty["formulas"] = []
    assert validate_envelope_document(empty, record)


def test_inventory_builder_is_deterministic():
    assert json.dumps(build_inventory(), sort_keys=True) == json.dumps(build_inventory(), sort_keys=True)
