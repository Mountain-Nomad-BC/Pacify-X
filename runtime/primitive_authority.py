"""Canonical authority for reusable PX execution primitives.

The registry names an owner; it does not import or execute that owner.  Static
resolution keeps authority validation safe in release gates and tooling.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_repository_relative


SCHEMA_VERSION = "px.primitive-authority/1.0"
REGISTRY_PATH = Path("registry/primitive_authority.json")
REQUIRED_PRIMITIVES = frozenset(
    {
        "agent_execution",
        "behavioral_assurance",
        "dimensional_formulas",
        "evidence_custody",
        "handoff",
        "hardware_placement",
        "impact",
        "memory_resolution",
        "model_selection",
        "retrieval",
        "specialist_selection",
        "task_normalization",
        "work_admission",
    }
)
_OWNER_FIELDS = frozenset({"language", "module", "path", "symbol"})


def load_primitive_authority(root: Path) -> dict[str, Any]:
    """Load the repository's primitive-authority registry."""
    path = root.resolve() / REGISTRY_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("primitive authority registry must be an object")
    return payload


def _defined_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    symbols: set[str] = set()

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
                symbols.add(qualified)
                if isinstance(node, ast.ClassDef):
                    visit(node.body, qualified)

    visit(tree.body)
    return symbols


def _validate_owner(
    root: Path,
    owner: object,
    *,
    label: str,
) -> tuple[list[str], tuple[str, str] | None]:
    if not isinstance(owner, Mapping):
        return [f"{label} must be an object"], None
    errors: list[str] = []
    missing = sorted(field for field in _OWNER_FIELDS if not owner.get(field))
    if missing:
        errors.append(f"{label} missing fields: {missing}")
        return errors, None
    if owner.get("language") != "python":
        errors.append(f"{label} language must be python")
    relative = owner.get("path")
    module = owner.get("module")
    symbol = owner.get("symbol")
    path = resolve_repository_relative(root, relative)
    if path is None or not path.is_file():
        errors.append(f"{label} owner path is missing or outside the repository")
        return errors, None
    expected_module = str(relative)[:-3].replace("/", ".") if str(relative).endswith(".py") else ""
    if module != expected_module:
        errors.append(
            f"{label} module {module!r} does not match owner path {relative!r}"
        )
    try:
        defined = _defined_symbols(path)
    except (OSError, SyntaxError, UnicodeError) as error:
        errors.append(f"{label} owner source cannot be inspected: {error}")
        return errors, None
    if symbol not in defined:
        errors.append(f"{label} unknown owner symbol {module}:{symbol}")
    return errors, (str(module), str(symbol))


def validate_primitive_authority(
    root: Path,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate complete, singular, statically resolvable primitive ownership."""
    root = root.resolve()
    try:
        registry = dict(payload) if payload is not None else load_primitive_authority(root)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "primitive_count": 0,
            "errors": [str(error)],
        }

    errors: list[str] = []
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    records = registry.get("primitives")
    if not isinstance(records, list):
        records = []
        errors.append("primitives must be a list")

    seen: set[str] = set()
    for index, record in enumerate(records):
        label = f"primitives[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{label} must be an object")
            continue
        primitive = record.get("primitive")
        if not isinstance(primitive, str) or not primitive:
            errors.append(f"{label}.primitive must be a non-empty string")
            continue
        if primitive in seen:
            errors.append(f"duplicate canonical owner for primitive {primitive}")
        seen.add(primitive)
        owner_errors, canonical = _validate_owner(
            root, record.get("canonical_owner"), label=f"{primitive}.canonical_owner"
        )
        errors.extend(owner_errors)

        if record.get("bypass_policy") != "deny_unless_exception":
            errors.append(f"{primitive} must deny undeclared bypasses")
        exceptions = record.get("bypass_exceptions")
        if not isinstance(exceptions, list):
            errors.append(f"{primitive}.bypass_exceptions must be a list")
            exceptions = []
        exception_ids: set[str] = set()
        for exception_index, exception in enumerate(exceptions):
            exception_label = f"{primitive}.bypass_exceptions[{exception_index}]"
            if not isinstance(exception, Mapping):
                errors.append(f"{exception_label} must be an object")
                continue
            exception_id = exception.get("exception_id")
            if not isinstance(exception_id, str) or not exception_id:
                errors.append(f"{exception_label} requires exception_id")
            elif exception_id in exception_ids:
                errors.append(f"{primitive} has duplicate bypass exception {exception_id}")
            else:
                exception_ids.add(exception_id)
            for field in ("rationale", "expires_utc"):
                if not exception.get(field):
                    errors.append(f"{exception_label} requires {field}")
            bypass_errors, _ = _validate_owner(
                root, exception.get("owner"), label=f"{exception_label}.owner"
            )
            errors.extend(bypass_errors)

        declared = record.get("declared_bypasses", [])
        if not isinstance(declared, list) or any(
            not isinstance(value, str) or not value for value in declared
        ):
            errors.append(f"{primitive}.declared_bypasses must be a string list")
        elif set(declared) != exception_ids:
            errors.append(
                f"{primitive} has an undeclared or stale bypass; declared IDs must "
                "exactly match bypass exceptions"
            )

        federated = record.get("federated_owners", [])
        if not isinstance(federated, list):
            errors.append(f"{primitive}.federated_owners must be a list")
            federated = []
        federated_seen: set[tuple[str, str]] = set()
        for owner_index, owner in enumerate(federated):
            owner_errors, locator = _validate_owner(
                root,
                owner,
                label=f"{primitive}.federated_owners[{owner_index}]",
            )
            errors.extend(owner_errors)
            if locator == canonical or locator in federated_seen:
                errors.append(f"{primitive} has a duplicate federated owner")
            if locator is not None:
                federated_seen.add(locator)

    missing = sorted(REQUIRED_PRIMITIVES - seen)
    unknown = sorted(seen - REQUIRED_PRIMITIVES)
    if missing:
        errors.append(f"missing required primitives: {missing}")
    if unknown:
        errors.append(f"unknown primitives: {unknown}")
    if registry.get("primitive_count") != len(records):
        errors.append("primitive_count does not match primitives")

    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "primitive_count": len(records),
        "required_primitive_count": len(REQUIRED_PRIMITIVES),
        "errors": errors,
    }


def resolve_primitive_owner(
    root: Path,
    primitive: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the sole validated canonical owner for ``primitive``."""
    registry = dict(payload) if payload is not None else load_primitive_authority(root)
    report = validate_primitive_authority(root, registry)
    if not report["valid"]:
        raise ValueError("primitive authority is invalid: " + "; ".join(report["errors"]))
    matches = [
        record
        for record in registry["primitives"]
        if record.get("primitive") == primitive
    ]
    if len(matches) != 1:
        raise KeyError(f"unknown primitive {primitive!r}")
    return dict(matches[0]["canonical_owner"])
