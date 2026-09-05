"""Shared invariants for count-bearing JSON registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .corrective_release import SOURCE_CARD_IDS


COUNT_SUFFIX = "_count"


UNOWNED_COUNT_FIELDS = {
    ("registry/operational_gap_ledger.head.json", "event_count"),
    ("registry/operational_gap_ledger.head.json", "snapshot_event_count"),
    ("registry/operational_gap_ledger.snapshot.json", "event_count"),
    ("registry/px_world_state.json", "ledger_event_count"),
    ("registry/px_world_state.json", "open_blocker_count"),
    (
        "registry/operational_surface_inventory.json",
        "dashboard_navigation_surface_count",
    ),
    ("registry/operational_surface_inventory.json", "ui_action_count"),
}


def _count_fields(payload: Mapping[str, Any]) -> set[str]:
    return {key for key in payload if key == "count" or key.endswith(COUNT_SUFFIX)}


def discover_count_fields(root: Path) -> set[tuple[str, str]]:
    root = root.resolve()
    discovered: set[tuple[str, str]] = set()
    for path in sorted((root / "registry").rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            relative = path.relative_to(root).as_posix()
            discovered.update(
                (relative, key)
                for key in _count_fields(payload)
                if (relative, key) not in UNOWNED_COUNT_FIELDS
            )
    return discovered


def _collection(payload: Mapping[str, Any], key: str) -> list[Any] | dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, (list, dict)):
        raise ValueError(f"collection {key!r} must be a list or object")
    return value


def _external_value(root: Path | None, record: Mapping[str, Any]) -> Any:
    if root is None:
        raise ValueError("external registry-envelope rule requires repository root")
    relative = str(record.get("source_path", ""))
    if not relative or "\\" in relative:
        raise ValueError("external registry-envelope source path is invalid")
    resolved_root = root.resolve()
    source = (resolved_root / relative).resolve()
    try:
        source.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("external registry-envelope source escapes repository") from error
    try:
        value: Any = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if "source_default" in record:
            return record["source_default"]
        raise
    for key in str(record.get("source_key", "")).split("."):
        if not key:
            continue
        if not isinstance(value, Mapping) or key not in value:
            if "source_default" in record:
                return record["source_default"]
            raise ValueError(f"external registry-envelope source key is missing: {key}")
        value = value[key]
    return value


def derive_count(
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> int:
    rule = record["rule"]
    if rule == "external_length":
        value = _external_value(root, record)
        if not isinstance(value, (list, dict)):
            raise ValueError("external_length requires a list or object source")
        return len(value)
    if rule == "external_scalar":
        value = _external_value(root, record)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("external_scalar requires an integer source")
        return value
    if rule == "external_filtered":
        value = _external_value(root, record)
        if not isinstance(value, list):
            raise ValueError("external_filtered requires a list source")
        return sum(
            isinstance(item, dict)
            and item.get(record["field"]) == record.get("equals")
            for item in value
        )
    collection = _collection(payload, str(record["collection_key"]))
    if rule == "length":
        return len(collection)
    if rule == "filtered_values":
        if not isinstance(collection, dict):
            raise ValueError("rule 'filtered_values' requires an object collection")
        return sum(
            isinstance(item, dict)
            and item.get(record["field"]) == record.get("equals")
            for item in collection.values()
        )
    if not isinstance(collection, list):
        raise ValueError(f"rule {rule!r} requires a list collection")
    if rule == "filtered":
        return sum(
            isinstance(item, dict) and item.get(record["field"]) == record.get("equals")
            for item in collection
        )
    if rule == "unique":
        return len(
            {item.get(record["field"]) for item in collection if isinstance(item, dict)}
        )
    if rule == "duplicates":
        values = [
            item.get(record["field"]) for item in collection if isinstance(item, dict)
        ]
        return len(values) - len(set(values))
    if rule == "source_cards":
        return sum(
            isinstance(item, dict) and item.get("id") in SOURCE_CARD_IDS
            for item in collection
        )
    if rule == "child_cards":
        return sum(
            isinstance(item, dict) and item.get("id") not in SOURCE_CARD_IDS
            for item in collection
        )
    if rule == "nested_length":
        return sum(
            len(item.get(record["nested"], ()))
            for item in collection
            if isinstance(item, dict)
        )
    if rule == "nested_filtered":
        return sum(
            isinstance(nested, dict)
            and nested.get(record["field"]) == record.get("equals")
            for item in collection
            if isinstance(item, dict)
            for nested in item.get(record["nested"], ())
        )
    if rule == "nested_object_filtered":
        return sum(
            isinstance(item, dict)
            and isinstance(item.get(record["nested"]), dict)
            and item[record["nested"]].get(record["field"])
            == record.get("equals")
            for item in collection
        )
    raise ValueError(f"unsupported registry-envelope rule: {rule}")


def validate_envelope_document(
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> list[str]:
    key = str(record["count_key"])
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{key} must be an integer"]
    try:
        expected = derive_count(payload, record, root=root)
    except (KeyError, TypeError, ValueError) as error:
        return [str(error)]
    return (
        []
        if value == expected
        else [f"{key}={value} does not match derived count {expected}"]
    )


def validate_registry_envelopes(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inventory_path = root / "registry/registry_envelope_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("records", [])
    declared = {(str(item["path"]), str(item["count_key"])) for item in records}
    discovered = discover_count_fields(root)
    errors: list[str] = []
    missing = sorted(discovered - declared)
    extra = sorted(declared - discovered)
    if missing:
        errors.append(f"unowned count fields: {missing}")
    if extra:
        errors.append(f"stale count-field owners: {extra}")
    by_path: dict[str, dict[str, Any]] = {}
    for item in records:
        relative = str(item["path"])
        payload = by_path.setdefault(
            relative, json.loads((root / relative).read_text(encoding="utf-8"))
        )
        errors.extend(
            f"{relative}: {error}"
            for error in validate_envelope_document(payload, item, root=root)
        )
        for required in ("schema", "builder", "consumer"):
            if not item.get(required):
                errors.append(f"{relative}/{item.get('count_key')}: missing {required}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "record_count": len(records),
        "registry_count": len(by_path),
        "errors": errors,
    }
