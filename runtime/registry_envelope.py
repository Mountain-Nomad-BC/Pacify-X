"""Shared invariants for count-bearing JSON registries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .bounded_walk import WalkLimits, bounded_walk
from .corrective_release import SOURCE_CARD_IDS
from .json_io import decode_json_object, json_value_key, read_bounded_bytes


COUNT_SUFFIX = "_count"
ENVELOPE_SCHEMA = "root schema_version plus shared registry-envelope invariant"
VERSIONLESS_ENVELOPE_SCHEMA = "shared registry-envelope invariant (versionless document)"
MAX_OWNER_RECORDS = 10_000
MAX_ACQUIRED_BYTES = 256 * 1024 * 1024


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
    byte_budget = [MAX_ACQUIRED_BYTES]
    for path in _registry_paths(root):
        payload = _read_document(path, byte_budget)
        relative = path.relative_to(root).as_posix()
        discovered.update(_owned_fields(relative, payload))
    return discovered


def _registry_paths(root: Path) -> tuple[Path, ...]:
    registry_root = root / "registry"
    tree = bounded_walk(registry_root, limits=WalkLimits(
        max_files=10_000, max_depth=32, max_bytes=256 * 1024 * 1024,
        max_entries=100_000, max_directories=2_000,
    ), exclude=lambda relative: not relative.casefold().endswith(".json")
       and not (registry_root / relative).is_dir())
    return tuple(entry.path for entry in tree.files if entry.path.suffix.casefold() == ".json")


def _read_document(path: Path, byte_budget: list[int], *, max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    remaining = min(max_bytes, byte_budget[0])
    if remaining < 1:
        raise ValueError("registry-envelope aggregate acquisition budget exhausted")
    try:
        raw = read_bounded_bytes(path, max_bytes=remaining)
    except ValueError:
        # An overflow probe closes this acquisition budget; subsequent external
        # rules cannot repeatedly consume the same remainder after rejection.
        byte_budget[0] = 0
        raise
    byte_budget[0] -= len(raw)
    return decode_json_object(raw, max_bytes=remaining)


def _owned_fields(relative: str, payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {(relative, key) for key in _count_fields(payload)
            if (relative, key) not in UNOWNED_COUNT_FIELDS}


def _contained_path(root: Path, relative: Any) -> Path:
    if (type(relative) is not str or not relative or len(relative) > 4096
            or "\\" in relative or ":" in relative or relative.startswith("/")
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("registry-envelope path must be a portable relative path")
    source = (root / relative).resolve()
    if not source.is_relative_to(root) or source == root:
        raise ValueError("registry-envelope path escapes repository")
    return source


def _equal(left: Any, right: Any) -> bool:
    return json_value_key(left) == json_value_key(right)


def _collection(payload: Mapping[str, Any], key: str) -> list[Any] | dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, (list, dict)):
        raise ValueError(f"collection {key!r} must be a list or object")
    return value


def _external_value(root: Path | None, record: Mapping[str, Any],
                    documents: dict[Path, dict[str, Any]] | None = None,
                    byte_budget: list[int] | None = None) -> Any:
    if root is None:
        raise ValueError("external registry-envelope rule requires repository root")
    resolved_root = root.resolve()
    source = _contained_path(resolved_root, record.get("source_path"))
    try:
        if documents is not None and source in documents:
            value: Any = documents[source]
        else:
            value = _read_document(source, byte_budget if byte_budget is not None else [MAX_ACQUIRED_BYTES])
            if documents is not None:
                documents[source] = value
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
    _documents: dict[Path, dict[str, Any]] | None = None,
    _byte_budget: list[int] | None = None,
) -> int:
    rule = record["rule"]
    if rule == "external_length":
        value = _external_value(root, record, _documents, _byte_budget)
        if not isinstance(value, (list, dict)):
            raise ValueError("external_length requires a list or object source")
        return len(value)
    if rule == "external_scalar":
        value = _external_value(root, record, _documents, _byte_budget)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("external_scalar requires an integer source")
        return value
    if rule == "external_filtered":
        value = _external_value(root, record, _documents, _byte_budget)
        if not isinstance(value, list):
            raise ValueError("external_filtered requires a list source")
        return sum(
            isinstance(item, dict)
            and _equal(item.get(record["field"]), record.get("equals"))
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
            and _equal(item.get(record["field"]), record.get("equals"))
            for item in collection.values()
        )
    if not isinstance(collection, list):
        raise ValueError(f"rule {rule!r} requires a list collection")
    if rule == "filtered":
        return sum(
            isinstance(item, dict) and _equal(item.get(record["field"]), record.get("equals"))
            for item in collection
        )
    if rule == "unique":
        return len(
            {json_value_key(item.get(record["field"])) for item in collection if isinstance(item, dict)}
        )
    if rule == "duplicates":
        values = [
            json_value_key(item.get(record["field"])) for item in collection if isinstance(item, dict)
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
            and _equal(nested.get(record["field"]), record.get("equals"))
            for item in collection
            if isinstance(item, dict)
            for nested in item.get(record["nested"], ())
        )
    if rule == "nested_object_filtered":
        return sum(
            isinstance(item, dict)
            and isinstance(item.get(record["nested"]), dict)
            and _equal(item[record["nested"]].get(record["field"]), record.get("equals"))
            for item in collection
        )
    raise ValueError(f"unsupported registry-envelope rule: {rule}")


def validate_envelope_document(
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
    _documents: dict[Path, dict[str, Any]] | None = None,
    _byte_budget: list[int] | None = None,
) -> list[str]:
    key = str(record["count_key"])
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{key} must be an integer"]
    try:
        expected = derive_count(payload, record, root=root, _documents=_documents, _byte_budget=_byte_budget)
    except (OSError, KeyError, TypeError, ValueError) as error:
        return [str(error)]
    return (
        []
        if value == expected
        else [f"{key}={value} does not match derived count {expected}"]
    )


def validate_registry_envelopes(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inventory_path = root / "registry/registry_envelope_inventory.json"
    errors: list[str] = []
    records = []
    by_path: dict[str, dict[str, Any]] = {}
    declared: set[tuple[str, str]] = set()
    discovered: set[tuple[str, str]] = set()
    byte_budget = [MAX_ACQUIRED_BYTES]
    try:
        inventory = _read_document(inventory_path, byte_budget, max_bytes=4 * 1024 * 1024)
        records = inventory.get("records")
        if type(records) is not list or not 1 <= len(records) <= MAX_OWNER_RECORDS:
            raise ValueError("registry envelope requires 1..10000 owner records")
        owned_paths = set()
        needed_paths = set()
        for number, item in enumerate(records):
            if type(item) is not dict:
                raise ValueError(f"owner record {number} must be an object")
            relative = item.get("path")
            path = _contained_path(root, relative)
            if not path.is_relative_to(root / "registry") or path.suffix.casefold() != ".json":
                raise ValueError("owned count path must be registry JSON")
            key = item.get("count_key")
            if type(key) is not str or not (key == "count" or key.endswith(COUNT_SUFFIX)):
                raise ValueError("owner count_key must name a count field")
            identity = (relative, key)
            if identity in declared:
                raise ValueError(f"duplicate registry count owner: {relative}/{key}")
            declared.add(identity)
            for role in ("builder", "consumer"):
                owner = _contained_path(root, item.get(role))
                if not owner.is_file():
                    raise ValueError(f"{relative}/{key}: {role} does not resolve")
            if item.get("schema") not in (ENVELOPE_SCHEMA, VERSIONLESS_ENVELOPE_SCHEMA):
                raise ValueError(f"{relative}/{key}: unsupported envelope schema contract")
            owned_paths.add(relative)
            needed_paths.add(path)
            if "source_path" in item:
                needed_paths.add(_contained_path(root, item["source_path"]))
        documents = {inventory_path.resolve(): inventory}
        for path in _registry_paths(root):
            resolved = path.resolve()
            payload = documents.get(resolved)
            if payload is None:
                payload = _read_document(path, byte_budget)
            relative = path.relative_to(root).as_posix()
            discovered.update(_owned_fields(relative, payload))
            if resolved in needed_paths:
                documents[resolved] = payload
            if relative in owned_paths:
                by_path[relative] = payload
        for item in records:
            relative = item["path"]
            payload = by_path.get(relative)
            if payload is None:
                errors.append(f"{relative}: owned registry is missing")
                continue
            if item["schema"] == ENVELOPE_SCHEMA:
                version = payload.get("schema_version")
                if type(version) is not str or not version.strip() or len(version) > 256:
                    errors.append(f"{relative}: declared schema_version must be a bounded nonempty string")
            elif "schema_version" in payload:
                errors.append(f"{relative}: versionless contract requires absent schema_version")
            errors.extend(f"{relative}: {error}" for error in validate_envelope_document(
                payload, item, root=root, _documents=documents, _byte_budget=byte_budget,
            ))
    except (OSError, TypeError, KeyError, ValueError) as error:
        errors.append(str(error))
    missing = sorted(discovered - declared)
    extra = sorted(declared - discovered)
    if missing:
        errors.append(f"unowned count fields: {missing}")
    if extra:
        errors.append(f"stale count-field owners: {extra}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "record_count": len(records) if type(records) is list else 0,
        "registry_count": len(by_path),
        "errors": errors,
    }
