"""Machine-readable ownership topology for effect-producing PX operations."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_repository_relative


SCHEMA_VERSION = "px.authority-topology/1.0"
REGISTRY_PATH = Path("registry/authority_topology.json")
REQUIRED_EFFECT_TYPES = frozenset(
    {
        "agent_execution",
        "filesystem_mutation",
        "ledger_append",
        "network",
        "process",
        "project_transfer",
        "provider_execution",
        "release_identity",
        "skill_promotion",
    }
)


def _load(root: Path) -> dict[str, Any]:
    value = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("authority topology must be an object")
    return value


def _python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _owner_errors(root: Path, value: object, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} must be an object"]
    errors: list[str] = []
    language = value.get("language")
    relative = value.get("path")
    symbol = value.get("symbol")
    if language not in {"python", "javascript"}:
        errors.append(f"{label}.language must be python or javascript")
    path = resolve_repository_relative(root, relative)
    if path is None or not path.is_file():
        errors.append(f"{label}.path is missing or outside the repository")
        return errors
    if not isinstance(symbol, str) or not symbol:
        errors.append(f"{label}.symbol is required")
    elif language == "python":
        try:
            if symbol not in _python_symbols(path):
                errors.append(f"{label}.symbol is not defined by {relative}")
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"{label}.path cannot be inspected: {error}")
    else:
        try:
            source = path.read_text(encoding="utf-8")
            if symbol not in source:
                errors.append(f"{label}.symbol is not present in {relative}")
        except (OSError, UnicodeError) as error:
            errors.append(f"{label}.path cannot be inspected: {error}")
    return errors


def validate_authority_topology(
    root: Path, payload: Mapping[str, Any] | None = None
) -> dict[str, object]:
    """Validate singular gates, rollback, receipts, and bypass visibility."""
    root = root.resolve(strict=True)
    try:
        topology = dict(payload) if payload is not None else _load(root)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return {"schema_version": SCHEMA_VERSION, "valid": False, "errors": [str(error)]}
    errors: list[str] = []
    if topology.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    effects = topology.get("effects")
    if not isinstance(effects, list):
        effects = []
        errors.append("effects must be a list")
    seen: set[str] = set()
    for index, effect in enumerate(effects):
        label = f"effects[{index}]"
        if not isinstance(effect, Mapping):
            errors.append(f"{label} must be an object")
            continue
        effect_type = effect.get("effect_type")
        if not isinstance(effect_type, str) or not effect_type:
            errors.append(f"{label}.effect_type is required")
            continue
        if effect_type in seen:
            errors.append(f"two authoritative gates declared for {effect_type}")
        seen.add(effect_type)
        errors.extend(_owner_errors(root, effect.get("authoritative_gate"), f"{effect_type}.authoritative_gate"))
        errors.extend(_owner_errors(root, effect.get("rollback_owner"), f"{effect_type}.rollback_owner"))
        errors.extend(_owner_errors(root, effect.get("bypass_detector"), f"{effect_type}.bypass_detector"))
        receipt = effect.get("receipt_contract")
        if not isinstance(receipt, str) or not receipt:
            errors.append(f"{effect_type}.receipt_contract is required")
        elif receipt.startswith("contracts/"):
            receipt_path = resolve_repository_relative(root, receipt)
            if receipt_path is None or not receipt_path.is_file():
                errors.append(f"{effect_type}.receipt_contract is missing")
        runtimes = effect.get("runtimes")
        if not isinstance(runtimes, list) or not runtimes:
            errors.append(f"{effect_type}.runtimes must be a non-empty list")
        elif len(set(map(str, runtimes))) > 1:
            vectors = effect.get("conformance_vectors")
            vector_path = resolve_repository_relative(root, vectors)
            if vector_path is None or not vector_path.is_file():
                errors.append(f"{effect_type} cross-runtime semantics lack conformance vectors")
    missing = sorted(REQUIRED_EFFECT_TYPES - seen)
    unknown = sorted(seen - REQUIRED_EFFECT_TYPES)
    if missing:
        errors.append(f"missing effect types: {missing}")
    if unknown:
        errors.append(f"unknown effect types: {unknown}")
    if topology.get("effect_count") != len(effects):
        errors.append("effect_count does not match effects")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "effect_count": len(effects),
        "errors": errors,
    }


def resolve_effect_authority(root: Path, effect_type: str) -> dict[str, Any]:
    topology = _load(root.resolve(strict=True))
    report = validate_authority_topology(root, topology)
    if not report["valid"]:
        raise ValueError("authority topology is invalid: " + "; ".join(report["errors"]))
    matches = [item for item in topology["effects"] if item["effect_type"] == effect_type]
    if len(matches) != 1:
        raise KeyError(f"unknown effect type {effect_type!r}")
    return dict(matches[0])
