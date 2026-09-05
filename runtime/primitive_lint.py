"""Conservative static lint for duplicate canonical primitive definitions."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .primitive_authority import (
    load_primitive_authority,
    validate_primitive_authority,
)


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_primitive_exceptions(
    registry: Mapping[str, object], *, now_utc: datetime | None = None
) -> dict[str, object]:
    """Require every duplicate-authority exception to be exact and unexpired."""
    now = now_utc or datetime.now(timezone.utc)
    errors: list[str] = []
    count = 0
    for record in registry.get("primitives", []):
        if not isinstance(record, Mapping):
            continue
        primitive = str(record.get("primitive") or "")
        for exception in record.get("bypass_exceptions", []):
            count += 1
            if not isinstance(exception, Mapping):
                errors.append(f"{primitive}: exception must be an object")
                continue
            owner = exception.get("owner")
            if not isinstance(owner, Mapping):
                errors.append(f"{primitive}: exception owner is required")
                continue
            path = str(owner.get("path") or "")
            symbol = str(owner.get("symbol") or "")
            if not path or not symbol or any(marker in path + symbol for marker in ("*", "?", "[")):
                errors.append(f"{primitive}: broad or incomplete exception owner")
            expiry = _time(exception.get("expires_utc"))
            if expiry is None or expiry <= now:
                errors.append(f"{primitive}: exception is invalid or expired")
    return {"valid": not errors, "exception_count": count, "errors": errors}


def _definitions(tree: ast.AST) -> Iterable[tuple[str, ast.AST]]:
    def walk(body: list[ast.stmt], prefix: str = ""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
                if not isinstance(node, ast.ClassDef):
                    yield qualified, node
                else:
                    yield from walk(node.body, qualified)

    yield from walk(tree.body)  # type: ignore[attr-defined]


def scan_duplicate_primitives(
    root: Path,
    *,
    registry: Mapping[str, object] | None = None,
    candidate_paths: Iterable[Path] | None = None,
) -> dict[str, object]:
    """Flag exact-name duplicate definitions and unresolved dynamic lookups."""
    root = root.resolve()
    authority = dict(registry) if registry is not None else load_primitive_authority(root)
    authority_report = validate_primitive_authority(root, authority)
    exception_report = validate_primitive_exceptions(authority)
    if not authority_report["valid"] or not exception_report["valid"]:
        return {
            "schema_version": "px.primitive-lint/1.0",
            "valid": False,
            "findings": [],
            "aliases": [],
            "errors": [*authority_report["errors"], *exception_report["errors"]],
        }
    primitives: dict[str, tuple[str, str, str]] = {}
    exceptions: set[tuple[str, str, str]] = set()
    for record in authority["primitives"]:
        owner = record["canonical_owner"]
        primitive = str(record["primitive"])
        primitives[str(owner["symbol"]).rsplit(".", 1)[-1]] = (
            primitive,
            str(owner["path"]),
            str(owner["symbol"]),
        )
        for exception in record.get("bypass_exceptions", []):
            exception_owner = exception["owner"]
            exceptions.add(
                (primitive, str(exception_owner["path"]), str(exception_owner["symbol"]))
            )
    paths = (
        sorted(path.resolve() for path in candidate_paths)
        if candidate_paths is not None
        else sorted(
            path.resolve()
            for directory in (root / "runtime", root / "scripts")
            if directory.is_dir()
            for path in directory.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )
    findings: list[dict[str, object]] = []
    aliases: list[dict[str, object]] = []
    for path in paths:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = f"<external>/{path.name}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as error:
            findings.append(
                {"kind": "ambiguity", "path": relative, "reason": f"uninspectable:{error}"}
            )
            continue
        for qualified, node in _definitions(tree):
            leaf = qualified.rsplit(".", 1)[-1]
            if leaf not in primitives:
                continue
            primitive, owner_path, owner_symbol = primitives[leaf]
            if (relative, qualified) == (owner_path, owner_symbol):
                continue
            if (primitive, relative, qualified) in exceptions:
                continue
            findings.append(
                {
                    "kind": "duplicate_definition",
                    "primitive": primitive,
                    "path": relative,
                    "symbol": qualified,
                    "line": getattr(node, "lineno", None),
                    "canonical_owner": f"{owner_path}:{owner_symbol}",
                }
            )
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if isinstance(value, ast.Name) and value.id in primitives:
                    aliases.append(
                        {"path": relative, "target": value.id, "line": node.lineno}
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in primitives
            ):
                findings.append(
                    {
                        "kind": "dynamic_ambiguity",
                        "primitive": primitives[str(node.args[1].value)][0],
                        "path": relative,
                        "line": node.lineno,
                    }
                )
    findings.sort(key=lambda item: (str(item.get("path")), int(item.get("line") or 0)))
    aliases.sort(key=lambda item: (str(item["path"]), int(item["line"])))
    return {
        "schema_version": "px.primitive-lint/1.0",
        "valid": not findings,
        "finding_count": len(findings),
        "findings": findings,
        "aliases": aliases,
        "errors": [],
    }
