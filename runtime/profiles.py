"""Validation for portable bootstrap resource and model-routing profiles."""

from __future__ import annotations

from pathlib import Path
import tomllib


PROFILE_IDS = frozenset(
    {"default", "constrained", "large-workstation", "local-model", "cloud-restricted"}
)


def validate_profile(path: Path) -> dict[str, object]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("unsupported schema_version")
    if payload.get("id") not in PROFILE_IDS:
        errors.append("unknown profile id")
    resources = payload.get("resources", {})
    for key in ("max_agents", "max_heavy_lanes", "max_context_bytes"):
        value = resources.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"resources.{key} must be positive")
    if resources.get("max_heavy_lanes") != 1:
        errors.append("profiles must serialize heavy work")
    routing = payload.get("routing", {})
    if set(routing) != {"local_models", "cloud_models", "sensitive_data"}:
        errors.append("routing keys are incomplete")
    serialized = path.read_text(encoding="utf-8")
    if ":\\" in serialized or "/Users/" in serialized or "\\Users\\" in serialized:
        errors.append("profile contains a machine-specific path")
    return {
        "valid": not errors,
        "id": payload.get("id"),
        "errors": errors,
        "profile": payload,
    }


def validate_profile_set(root: Path) -> dict[str, object]:
    results = [validate_profile(path) for path in sorted(root.glob("*.toml"))]
    ids = {item["id"] for item in results}
    errors = [error for item in results for error in item["errors"]]
    errors.extend(f"missing profile: {name}" for name in sorted(PROFILE_IDS - ids))
    return {
        "valid": not errors,
        "profile_count": len(results),
        "errors": errors,
        "profiles": results,
    }
