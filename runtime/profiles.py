"""Validation for portable bootstrap resource and model-routing profiles."""

from __future__ import annotations

from pathlib import Path

from .archive_io import reject_path_links
from .bounded_walk import WalkLimits, bounded_walk
from .config import (
    MAX_STARTUP_INTEGER,
    MAX_STARTUP_METADATA_BYTES,
    _table,
    load_bounded_toml,
)


PROFILE_IDS = frozenset(
    {"default", "constrained", "large-workstation", "local-model", "cloud-restricted"}
)
ROUTING_VALUES = {
    "local_models": frozenset({"optional", "disabled", "preferred"}),
    "cloud_models": frozenset(
        {"optional", "disabled", "metadata_only", "explicit_fallback"}
    ),
    "sensitive_data": frozenset({"policy_gated", "local_only"}),
}


def validate_profile(path: Path) -> dict[str, object]:
    try:
        payload = _table(
            load_bounded_toml(path),
            {"schema_version", "id", "resources", "routing"},
            "profile",
        )
        resources = _table(
            payload["resources"],
            {"max_agents", "max_heavy_lanes", "max_context_bytes"},
            "resources",
        )
        routing = _table(payload["routing"], set(ROUTING_VALUES), "routing")
    except (OSError, ValueError) as error:
        return {
            "valid": False,
            "id": None,
            "errors": [f"invalid profile: {str(error)[:512]}"],
            "profile": None,
        }
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("unsupported schema_version")
    if type(payload["id"]) is not str or payload["id"] not in PROFILE_IDS:
        errors.append("unknown profile id")
    for key in ("max_agents", "max_heavy_lanes", "max_context_bytes"):
        value = resources.get(key)
        if type(value) is not int or not 1 <= value <= MAX_STARTUP_INTEGER:
            errors.append(f"resources.{key} must be a bounded positive integer")
    if resources.get("max_heavy_lanes") != 1:
        errors.append("profiles must serialize heavy work")
    for field, values in ROUTING_VALUES.items():
        if type(routing[field]) is not str or routing[field] not in values:
            errors.append(f"routing.{field} has an unsupported value")
    return {
        "valid": not errors,
        "id": payload["id"]
        if type(payload["id"]) is str and payload["id"] in PROFILE_IDS
        else None,
        "errors": errors,
        "profile": payload if not errors else None,
    }


def validate_profile_set(root: Path) -> dict[str, object]:
    try:
        reject_path_links(root)
        inventory = bounded_walk(
            root,
            limits=WalkLimits(
                max_files=64,
                max_depth=1,
                max_bytes=64 * MAX_STARTUP_METADATA_BYTES,
                max_entries=256,
                max_directories=1,
                max_duration_seconds=10,
            ),
            exclude=lambda relative: not relative.endswith(".toml"),
        )
    except (OSError, ValueError) as error:
        return {
            "valid": False,
            "profile_count": 0,
            "errors": [f"profile set was not evaluated: {str(error)[:512]}"],
            "profiles": [],
        }
    results = [validate_profile(item.path) for item in inventory.files]
    ids = set()
    errors = [error for item in results for error in item["errors"]]
    for item in results:
        if item["id"] is not None:
            if item["id"] in ids:
                errors.append(f"duplicate profile id: {item['id']}")
            ids.add(item["id"])
    errors.extend(f"missing profile: {name}" for name in sorted(PROFILE_IDS - ids))
    return {
        "valid": not errors,
        "profile_count": len(results),
        "errors": errors,
        "profiles": results,
    }
