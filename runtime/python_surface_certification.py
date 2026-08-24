"""Classify and validate every Python source surface in the framework tree."""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
from typing import Any

from .repository_scope import is_project_source

def _source_python_candidate(path: Path, root: Path) -> bool:
    """Return true only for project-owned Python source.

    Repository-local interpreters and virtual environments are dependency
    installations. They are inventoried by environment discovery and must not
    inflate the application ownership/certification surface.
    """
    relative = path.relative_to(root)
    if "__pycache__" in relative.parts:
        return False
    if relative.parts[:2] == (".px", "preserved-skills"):
        return False
    return is_project_source(path, root)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _installed_record_hashes() -> dict[Path, str]:
    distribution = importlib.metadata.distribution("engineering-loop-bootstrap")
    text = distribution.read_text("RECORD")
    if text is None:
        raise ValueError("installed wheel RECORD is missing")
    records: dict[Path, str] = {}
    for relative, encoded, _ in csv.reader(io.StringIO(text)):
        if not encoded.startswith("sha256="):
            continue
        digest = base64.urlsafe_b64decode(encoded.removeprefix("sha256=") + "==").hex()
        records[Path(distribution.locate_file(relative)).resolve()] = digest
    return records


def _role(relative: str) -> tuple[str, str, bool]:
    parts = relative.split("/")
    if relative == "sitecustomize.py":
        return "source-build-control", "project-release-control", False
    if relative == "conftest.py":
        return "release-test-harness", "release-verification", False
    if parts[0] == "tests":
        return "release-test", "release-verification", True
    if parts[0] == "runtime":
        return "installed-runtime", "engineering_bootstrap", True
    if parts[0] == "builders":
        return "installed-builder", "engineering_bootstrap.builders", True
    if parts[0] == "templates" and len(parts) >= 2 and parts[1] == "generated":
        return "installed-generator-template", "generated-artifact-reconciliation", True
    if (
        parts[:2] == [".px", "skills"]
        and len(parts) >= 5
        and "scripts" in parts
    ):
        return "installed-skill-tool", parts[2], True
    if parts[0] == "scripts":
        return "source-build-control", "project-release-control", False
    if parts[0] == "examples":
        return "source-example", "public-demonstration", False
    return "unknown", "unowned", False


def certify_python_surfaces(
    root: Path,
    exact_tool_certification: dict[str, Any],
    *,
    require_map_current: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    source_checkout = (root / "pyproject.toml").is_file() and (root / "tests").is_dir()
    if not source_checkout:
        ownership_path = root / "registry" / "python_surface_ownership.json"
        if not ownership_path.is_file():
            return {
                "schema_version": "1.0",
                "valid": False,
                "python_file_count": 0,
                "syntax_valid_count": 0,
                "errors": ["installed Python surface ownership map is missing"],
                "records": [],
            }
        ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        package_root = Path(__file__).resolve().parent
        try:
            record_hashes = _installed_record_hashes()
        except (importlib.metadata.PackageNotFoundError, OSError, ValueError) as error:
            return {
                "schema_version": "1.0",
                "valid": False,
                "python_file_count": 0,
                "syntax_valid_count": 0,
                "errors": [str(error)],
                "records": [],
            }
        expected: dict[str, tuple[Path, dict[str, Any]]] = {}
        for record in ownership.get("records", ()):
            source_path = str(record.get("path", ""))
            role = str(record.get("role", ""))
            if role == "installed-runtime" and source_path.startswith("runtime/"):
                installed = package_root / source_path.removeprefix("runtime/")
                key = "engineering_bootstrap/" + source_path.removeprefix("runtime/")
            elif role == "installed-builder" and source_path.startswith("builders/"):
                installed = (
                    package_root / "builders" / source_path.removeprefix("builders/")
                )
                key = "engineering_bootstrap/builders/" + source_path.removeprefix(
                    "builders/"
                )
            elif role in {
                "installed-skill-tool",
                "installed-generator-template",
            } and record.get("packaged"):
                installed = root / source_path
                key = "share/engineering-bootstrap/" + source_path
            else:
                continue
            expected[key] = (installed, record)

        records: list[dict[str, Any]] = []
        errors: list[str] = []
        observed: set[str] = set()
        candidates = [
            *(
                path
                for path in package_root.rglob("*.py")
                if "__pycache__" not in path.parts
            ),
            *(path for path in root.rglob("*.py") if "__pycache__" not in path.parts),
        ]
        for path in sorted(candidates, key=lambda item: item.as_posix().casefold()):
            if path.is_relative_to(package_root):
                relative = (
                    "engineering_bootstrap/" + path.relative_to(package_root).as_posix()
                )
            else:
                relative = (
                    "share/engineering-bootstrap/" + path.relative_to(root).as_posix()
                )
            projection = expected.get(relative)
            if projection is None:
                if (
                    path.is_relative_to(package_root)
                    and path.resolve() in record_hashes
                ):
                    package_relative = path.relative_to(package_root).as_posix()
                    is_builder = package_relative.startswith("builders/")
                    record = {
                        "path": (
                            "builders/" + package_relative.removeprefix("builders/")
                        )
                        if is_builder
                        else "runtime/" + package_relative,
                        "role": "installed-builder"
                        if is_builder
                        else "installed-runtime",
                        "owner": "engineering_bootstrap.builders"
                        if is_builder
                        else "engineering_bootstrap",
                        "packaged": True,
                        "validation_level": "wheel-record-and-artifact-manifest",
                        "evidence": ["wheel RECORD", "canonical artifact manifest"],
                        "syntax_valid": True,
                    }
                else:
                    errors.append(
                        f"{relative}: installed Python file is absent from ownership map"
                    )
                    continue
            else:
                _, record = projection
                observed.add(relative)
            actual_digest = _digest(path)
            recorded_digest = record_hashes.get(path.resolve())
            if recorded_digest is None:
                errors.append(
                    f"{relative}: installed Python file is absent from wheel RECORD"
                )
            elif actual_digest != recorded_digest:
                errors.append(
                    f"{relative}: installed Python file differs from wheel RECORD"
                )
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
            except (OSError, SyntaxError, UnicodeError) as error:
                errors.append(f"{relative}: {type(error).__name__}: {error}")
            records.append(
                {
                    **record,
                    "installed_path": relative,
                    "installed_sha256": actual_digest,
                }
            )
        missing = sorted(set(expected) - observed)
        errors.extend(
            f"{path}: mapped packaged Python file is missing from installation"
            for path in missing
        )
        mirrored = [
            name for name in ("runtime", "builders", "tests") if (root / name).exists()
        ]
        errors.extend(
            f"lean runtime installation contains forbidden shared {name} tree"
            for name in mirrored
        )
        return {
            "schema_version": "1.0",
            "valid": not errors,
            "python_file_count": len(records),
            "syntax_valid_count": len(records)
            - sum(
                1
                for error in errors
                if "SyntaxError" in error or "UnicodeError" in error
            ),
            "source_python_file_count": ownership.get("python_file_count"),
            "packaged_file_count": len(expected),
            "distribution_model": "lean-runtime-wheel-complete-sdist",
            "mirrored_runtime_source_count": len(mirrored),
            "errors": errors,
            "records": records,
        }
    tests = sorted((root / "tests").glob("test_*.py"))
    test_text = {
        path.relative_to(root).as_posix(): path.read_text(
            encoding="utf-8", errors="replace"
        )
        for path in tests
    }
    direct_paths = {
        record["target"]
        for record in exact_tool_certification.get("results", ())
        if record["positive_behavior"]["passed"]
    }
    direct_paths.update(
        record["target"]
        for record in exact_tool_certification.get("wrapper_results", ())
        if record["behavior"]["passed"]
    )
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix().casefold()):
        if not _source_python_candidate(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        role, owner, packaged = _role(relative)
        syntax_error = None
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as error:
            syntax_error = f"{type(error).__name__}: {error}"
            errors.append(f"{relative}: {syntax_error}")
        references = sorted(
            name
            for name, text in test_text.items()
            if path.name in text or relative in text
        )
        if role in {"release-test", "release-test-harness"}:
            evidence = [relative]
            level = "executable-test"
        elif relative in direct_paths:
            evidence = [
                "runtime/exact_tool_certification.py",
                "tests/test_exact_tool_certification.py",
            ]
            level = "direct-isolated-behavior"
        elif references:
            evidence = references
            level = "evidence-association"
        elif role in {"installed-runtime", "installed-builder"}:
            evidence = ["tests", "tests/test_installed_wheel_e2e.py"]
            level = "full-suite-and-installed-integration"
        elif role == "source-build-control":
            evidence = [
                "structural AST validation",
                "project-management release boundary",
            ]
            level = "source-only-structural"
        else:
            evidence = []
            level = "unvalidated"
        if role == "unknown":
            errors.append(f"{relative}: unknown Python surface")
        if (
            packaged
            and role == "installed-skill-tool"
            and level not in {"direct-isolated-behavior", "evidence-association"}
        ):
            errors.append(
                f"{relative}: packaged skill tool lacks direct behavioral evidence"
            )
        records.append(
            {
                "path": relative,
                "sha256": _digest(path),
                "bytes": path.stat().st_size,
                "role": role,
                "owner": owner,
                "packaged": packaged,
                "validation_level": level,
                "evidence": evidence,
                "syntax_valid": syntax_error is None,
            }
        )
    role_counts: dict[str, int] = {}
    validation_counts: dict[str, int] = {}
    for record in records:
        role_counts[record["role"]] = role_counts.get(record["role"], 0) + 1
        validation_counts[record["validation_level"]] = (
            validation_counts.get(record["validation_level"], 0) + 1
        )
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
        "evidence_association_count": validation_counts.get("evidence-association", 0),
        "source_only_structural_count": validation_counts.get(
            "source-only-structural", 0
        ),
        "map_current": map_current,
        "role_counts": dict(sorted(role_counts.items())),
        "validation_counts": dict(sorted(validation_counts.items())),
        "errors": errors,
        "records": records,
    }
