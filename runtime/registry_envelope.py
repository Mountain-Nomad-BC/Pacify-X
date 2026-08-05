"""Shared invariants for count-bearing JSON registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .corrective_release import SOURCE_CARD_IDS


COUNT_SUFFIX = "_count"


def _count_fields(payload: Mapping[str, Any]) -> set[str]:
    return {key for key in payload if key == "count" or key.endswith(COUNT_SUFFIX)}


def discover_count_fields(root: Path) -> set[tuple[str, str]]:
    root = root.resolve()
    discovered: set[tuple[str, str]] = set()
    for path in sorted((root / "registry").rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            relative = path.relative_to(root).as_posix()
            discovered.update((relative, key) for key in _count_fields(payload))
    return discovered


def _collection(payload: Mapping[str, Any], key: str) -> list[Any] | dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, (list, dict)):
        raise ValueError(f"collection {key!r} must be a list or object")
    return value


def derive_count(payload: Mapping[str, Any], record: Mapping[str, Any]) -> int:
    collection = _collection(payload, str(record["collection_key"]))
    rule = record["rule"]
    if rule == "length":
        return len(collection)
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
    raise ValueError(f"unsupported registry-envelope rule: {rule}")


def validate_envelope_document(
    payload: Mapping[str, Any], record: Mapping[str, Any]
) -> list[str]:
    key = str(record["count_key"])
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{key} must be an integer"]
    try:
        expected = derive_count(payload, record)
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
            for error in validate_envelope_document(payload, item)
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
