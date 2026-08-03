"""Classify and validate every Python source surface in the framework tree."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _role(relative: str) -> tuple[str, str, bool]:
    parts = relative.split("/")
    if parts[0] == "tests":
        return "release-test", "release-verification", True
    if parts[0] == "runtime":
        return "installed-runtime", "engineering_bootstrap", True
    if parts[0] == "builders":
        return "installed-builder", "engineering_bootstrap.builders", True
    if parts[0] == "templates" and len(parts) >= 2 and parts[1] == "generated":
        return "installed-generator-template", "generated-artifact-reconciliation", True
    if parts[0] == ".agents" and len(parts) >= 5 and parts[1] == "skills" and "scripts" in parts:
        return "installed-skill-tool", parts[2], True
    if parts[0] == "scripts":
        return "source-build-control", "project-release-control", False
    return "unknown", "unowned", False


def certify_python_surfaces(root: Path, exact_tool_certification: dict[str, Any], *, require_map_current: bool = True) -> dict[str, Any]:
    root = root.resolve()
    source_checkout = (root / "pyproject.toml").is_file() and (root / "tests").is_dir()
    if not source_checkout:
        ownership_path = root / "registry" / "python_surface_ownership.json"
        if not ownership_path.is_file():
            return {"schema_version": "1.0", "valid": False, "python_file_count": 0, "syntax_valid_count": 0, "errors": ["installed Python surface ownership map is missing"], "records": []}
        ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        expected = {record["path"]: record for record in ownership.get("records", ()) if record.get("packaged")}
        records = []
        errors = []
        for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix().casefold()):
            relative = path.relative_to(root).as_posix()
            record = expected.get(relative)
            if record is None:
                errors.append(f"{relative}: installed Python file is absent from ownership map")
                continue
            if _digest(path) != record["sha256"]:
                errors.append(f"{relative}: installed Python file hash mismatch")
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
            except (OSError, SyntaxError, UnicodeError) as error:
                errors.append(f"{relative}: {type(error).__name__}: {error}")
            records.append(record)
        missing = sorted(set(expected) - {record["path"] for record in records})
        errors.extend(f"{path}: mapped packaged Python file is missing from installation" for path in missing)
        return {
            "schema_version": "1.0",
            "valid": not errors,
            "python_file_count": len(records),
            "syntax_valid_count": len(records) - sum(1 for error in errors if "SyntaxError" in error or "UnicodeError" in error),
            "source_python_file_count": ownership.get("python_file_count"),
            "packaged_file_count": len(expected),
            "errors": errors,
            "records": records,
        }
    tests = sorted((root / "tests").glob("test_*.py"))
    test_text = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace") for path in tests}
    direct_paths = {record["target"] for record in exact_tool_certification.get("results", ()) if record["positive_behavior"]["passed"]}
    direct_paths.update(record["target"] for record in exact_tool_certification.get("wrapper_results", ()) if record["behavior"]["passed"])
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix().casefold()):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        role, owner, packaged = _role(relative)
        syntax_error = None
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as error:
            syntax_error = f"{type(error).__name__}: {error}"
            errors.append(f"{relative}: {syntax_error}")
        references = sorted(name for name, text in test_text.items() if path.name in text or relative in text)
        if role == "release-test":
            evidence = [relative]
            level = "executable-test"
        elif relative in direct_paths:
            evidence = ["runtime/exact_tool_certification.py", "tests/test_exact_tool_certification.py"]
            level = "direct-isolated-behavior"
        elif references:
            evidence = references
            level = "direct-test-reference"
        elif role in {"installed-runtime", "installed-builder"}:
            evidence = ["tests", "tests/test_installed_wheel_e2e.py"]
            level = "full-suite-and-installed-integration"
        elif role == "source-build-control":
            evidence = ["structural AST validation", "project-management release boundary"]
            level = "source-only-structural"
        else:
            evidence = []
            level = "unvalidated"
        if role == "unknown":
            errors.append(f"{relative}: unknown Python surface")
        if packaged and role == "installed-skill-tool" and level not in {"direct-isolated-behavior", "direct-test-reference"}:
            errors.append(f"{relative}: packaged skill tool lacks direct behavioral evidence")
        records.append({
            "path": relative,
            "sha256": _digest(path),
            "bytes": path.stat().st_size,
            "role": role,
            "owner": owner,
            "packaged": packaged,
            "validation_level": level,
            "evidence": evidence,
            "syntax_valid": syntax_error is None,
        })
    role_counts: dict[str, int] = {}
    validation_counts: dict[str, int] = {}
    for record in records:
        role_counts[record["role"]] = role_counts.get(record["role"], 0) + 1
        validation_counts[record["validation_level"]] = validation_counts.get(record["validation_level"], 0) + 1
    ownership_path = root / "registry" / "python_surface_ownership.json"
    map_current = False
    if ownership_path.is_file():
        stored = json.loads(ownership_path.read_text(encoding="utf-8"))
        map_current = stored.get("records") == records
    if require_map_current and not map_current:
        errors.append("Python surface ownership map is stale or missing")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "python_file_count": len(records),
        "syntax_valid_count": sum(1 for record in records if record["syntax_valid"]),
        "packaged_file_count": sum(1 for record in records if record["packaged"]),
        "direct_behavior_count": validation_counts.get("direct-isolated-behavior", 0),
        "direct_test_reference_count": validation_counts.get("direct-test-reference", 0),
        "source_only_structural_count": validation_counts.get("source-only-structural", 0),
        "map_current": map_current,
        "role_counts": dict(sorted(role_counts.items())),
        "validation_counts": dict(sorted(validation_counts.items())),
        "errors": errors,
        "records": records,
    }
