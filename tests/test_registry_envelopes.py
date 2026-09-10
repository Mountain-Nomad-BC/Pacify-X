import copy
import json
from pathlib import Path
import pytest

from runtime.registry_envelope import (
    UNOWNED_COUNT_FIELDS,
    discover_count_fields,
    validate_envelope_document,
    validate_registry_envelopes,
)
from scripts.build_registry_envelope_inventory import build_inventory


ROOT = Path(__file__).resolve().parents[1]


def _owned_registry(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "owner.py").write_text("# fixture owner\n", encoding="utf-8")
    payload = {"schema_version": "fixture/1", "count": 1, "second_count": 1, "rows": ["one"]}
    (tmp_path / "registry/owned.json").write_text(json.dumps(payload), encoding="utf-8")
    row = {"path": "registry/owned.json", "count_key": "count", "collection_key": "rows",
           "rule": "length", "builder": "owner.py", "consumer": "owner.py",
           "schema": "root schema_version plus shared registry-envelope invariant"}
    inventory = {"records": [row, {**row, "count_key": "second_count"}]}
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    return inventory


def test_duplicate_owner_cannot_disappear_in_coverage_set(tmp_path):
    inventory = _owned_registry(tmp_path)
    inventory["records"].append(dict(inventory["records"][0]))
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert any("duplicate" in error for error in result["errors"])


@pytest.mark.parametrize("field,value", [("builder", "absent.py"), ("consumer", "../escape.py"),
                                        ("schema", "invented schema"), ("path", "../escape.json")])
def test_owner_contract_must_resolve_inside_repository(tmp_path, field, value):
    inventory = _owned_registry(tmp_path)
    inventory["records"][0][field] = value
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert result["errors"]


def test_registry_coverage_and_counts_share_one_acquired_document(tmp_path, monkeypatch):
    _owned_registry(tmp_path)
    target = (tmp_path / "registry/owned.json").resolve()
    original = Path.open
    reads = []

    def track(path, *args, **kwargs):
        if path.resolve() == target:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", track)
    assert validate_registry_envelopes(tmp_path)["valid"]
    assert len(reads) == 1


def test_declared_schema_version_is_validated(tmp_path):
    _owned_registry(tmp_path)
    (tmp_path / "registry/owned.json").write_text(json.dumps({"count": 1, "second_count": 1, "rows": [1]}), encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert any("schema_version" in error for error in result["errors"])


def test_filtered_and_unique_counts_use_json_value_identity():
    payload = {"count": 1, "rows": [{"value": True}, {"value": 1}]}
    rule = {"count_key": "count", "collection_key": "rows", "rule": "filtered", "field": "value", "equals": True}
    assert validate_envelope_document(payload, rule) == []
    payload["count"] = 2
    rule["rule"] = "unique"
    assert validate_envelope_document(payload, rule) == []


def test_registry_acquisition_has_an_aggregate_byte_budget(tmp_path, monkeypatch):
    _owned_registry(tmp_path)
    inventory_bytes = (tmp_path / "registry/registry_envelope_inventory.json").stat().st_size
    monkeypatch.setattr("runtime.registry_envelope.MAX_ACQUIRED_BYTES", inventory_bytes + 10)
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert any("max_bytes" in error for error in result["errors"])


def test_uppercase_registry_extension_keeps_its_coverage(tmp_path):
    _owned_registry(tmp_path)
    (tmp_path / "registry/extra.JSON").write_text('{"count":1,"rows":[1]}', encoding="utf-8")
    assert ("registry/extra.JSON", "count") in discover_count_fields(tmp_path)
    assert not validate_registry_envelopes(tmp_path)["valid"]


def test_inventory_builder_declares_exact_versionless_documents():
    rows = build_inventory()["records"]
    versionless = {(row["path"], row["count_key"]) for row in rows
                   if row["schema"] == "shared registry-envelope invariant (versionless document)"}
    assert versionless == {
        ("registry/external_capability_benchmarks.json", "case_count"),
        ("registry/security_capabilities/domains.json", "canonical_domain_count"),
        ("registry/security_capabilities/domains.json", "source_raw_domain_count"),
    }


def test_explicit_versionless_contract_still_requires_exact_counts(tmp_path):
    inventory = _owned_registry(tmp_path)
    for row in inventory["records"]:
        row["schema"] = "shared registry-envelope invariant (versionless document)"
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    path = tmp_path / "registry/owned.json"
    payload = {"count": 1, "second_count": 1, "rows": [1]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_registry_envelopes(tmp_path)["valid"]
    payload["count"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert any("derived count" in error for error in result["errors"])


def test_versionless_contract_cannot_hide_a_present_invalid_version(tmp_path):
    inventory = _owned_registry(tmp_path)
    for row in inventory["records"]:
        row["schema"] = "shared registry-envelope invariant (versionless document)"
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (tmp_path / "registry/owned.json").write_text('{"schema_version":false,"count":1,"second_count":1,"rows":[1]}', encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert not result["valid"]
    assert any("schema_version" in error for error in result["errors"])


def test_versionless_builder_contract_validates_actual_documents_in_owned_fixture(tmp_path):
    paths = {"registry/external_capability_benchmarks.json", "registry/security_capabilities/domains.json"}
    rows = [row for row in build_inventory()["records"] if row["path"] in paths]
    for row in rows:
        for field in ("path", "builder", "consumer"):
            target = tmp_path / row[field]
            target.parent.mkdir(parents=True, exist_ok=True)
            if field == "path":
                target.write_bytes((ROOT / row[field]).read_bytes())
            else:
                target.write_text("# owned reference-resolution fixture\n", encoding="utf-8")
    (tmp_path / "registry/registry_envelope_inventory.json").write_text(json.dumps({"records": rows}), encoding="utf-8")
    result = validate_registry_envelopes(tmp_path)
    assert result["valid"], result["errors"]
    assert result["record_count"] == 3 and result["registry_count"] == 2


def test_externally_derived_surface_counts_are_not_local_collection_invariants():
    excluded = {
        key
        for path, key in UNOWNED_COUNT_FIELDS
        if path == "registry/operational_surface_inventory.json"
    }
    assert excluded == {"dashboard_navigation_surface_count", "ui_action_count"}
    discovered = discover_count_fields(ROOT)
    assert (
        "registry/operational_surface_inventory.json",
        "dashboard_navigation_surface_count",
    ) not in discovered


def test_mutable_ledger_projection_counts_are_not_live_envelope_invariants():
    excluded = {
        (path, key)
        for path, key in UNOWNED_COUNT_FIELDS
        if path
        in {
            "registry/operational_gap_ledger.head.json",
            "registry/operational_gap_ledger.snapshot.json",
            "registry/px_world_state.json",
        }
    }
    assert excluded == {
        ("registry/operational_gap_ledger.head.json", "event_count"),
        ("registry/operational_gap_ledger.head.json", "snapshot_event_count"),
        ("registry/operational_gap_ledger.snapshot.json", "event_count"),
        ("registry/px_world_state.json", "ledger_event_count"),
        ("registry/px_world_state.json", "open_blocker_count"),
    }
    discovered = discover_count_fields(ROOT)
    assert excluded.isdisjoint(discovered)


def test_every_count_bearing_registry_field_has_one_owner_and_invariant():
    result = validate_registry_envelopes(ROOT)
    assert result["valid"], result["errors"]
    assert result["record_count"] == len(discover_count_fields(ROOT))
    assert result["record_count"] > 0


def test_every_inventoried_count_rejects_deliberate_corruption():
    for record in build_inventory()["records"]:
        payload = json.loads((ROOT / record["path"]).read_text(encoding="utf-8"))
        corrupted = copy.deepcopy(payload)
        corrupted[record["count_key"]] += 1
        assert validate_envelope_document(corrupted, record, root=ROOT), (
            record["path"],
            record["count_key"],
        )


def test_missing_non_integer_and_empty_collection_are_intentional_failures():
    record = next(
        item
        for item in build_inventory()["records"]
        if item["path"] == "registry/declared_suite_formulas.json"
    )
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
    assert json.dumps(build_inventory(), sort_keys=True) == json.dumps(
        build_inventory(), sort_keys=True
    )


def test_nested_object_filtered_count_tracks_current_receipts():
    record = {
        "count_key": "current_required_receipt_count",
        "collection_key": "records",
        "rule": "nested_object_filtered",
        "nested": "receipt_state",
        "field": "current",
        "equals": True,
    }
    payload = {
        "current_required_receipt_count": 1,
        "records": [
            {"receipt_state": {"current": True}},
            {"receipt_state": {"current": False}},
            {"kind": "vsix"},
        ],
    }
    assert validate_envelope_document(payload, record) == []
    payload["current_required_receipt_count"] = 2
    assert validate_envelope_document(payload, record)
