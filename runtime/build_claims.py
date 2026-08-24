"""Deterministic build facts used by documentation and release assertions."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
from typing import Any

from .release_identity import authoritative_version


CLAIMS_PATH = Path("registry/build_claims.json")
README_COUNT_LABELS = {
    "Runtime modules": "runtime_modules",
    "Contracts": "contracts",
    "Registry artifacts": "registry_artifacts",
    "Tool and support scripts": "tool_and_support_scripts",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _registry_artifact_count(root: Path) -> int:
    """Count source artifacts without admitting live hidden lock files."""

    return sum(
        1
        for path in (root / "registry").rglob("*")
        if path.is_file()
        and not (path.name.startswith(".") and path.suffix.casefold() == ".lock")
    )


def expected_build_claims(root: Path) -> dict[str, Any]:
    """Compute exact source-tree claims without trusting stored denominators."""
    root = root.resolve()
    skills = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    ).get("skills", ())
    agents = _json(root / "registry/agency_agent_registry.json").get("agents", ())
    cognitive = _json(root / "registry/cognitive_map_index.json")
    orchestrations = _json(root / "registry/skill_orchestrations.json").get(
        "workflows", ()
    )
    effects = _json(root / "registry/effect_surface_ownership.json").get("records", ())
    framework_scripts = len(tuple((root / "scripts").glob("*.py")))
    skill_scripts = len(tuple((root / ".px/skills").glob("*/scripts/*.py")))
    return {
        "schema_version": "px.build-claims/1.0",
        "version": authoritative_version(root),
        "counts": {
            "runtime_modules": len(tuple((root / "runtime").rglob("*.py"))),
            "contracts": len(tuple((root / "contracts").rglob("*.json"))),
            "registry_artifacts": _registry_artifact_count(root),
            "tool_and_support_scripts": framework_scripts + skill_scripts,
            "skills": len(skills),
            "agents": len(agents),
            "workflow_definitions": len(
                tuple((root / "orchestration/workflows").rglob("*.yaml"))
            ),
            "orchestrations": len(orchestrations),
            "test_modules": len(tuple((root / "tests").glob("test_*.py"))),
            "graph_records": len(cognitive.get("records", ())),
            "graph_edges": len(cognitive.get("edges", ())),
            "effect_surfaces": len(effects),
        },
        "sources": {
            "version": "pyproject.toml:project.version",
            "runtime_modules": "runtime/**/*.py",
            "contracts": "contracts/**/*.json",
            "registry_artifacts": "registry/**/* non-lock files",
            "tool_and_support_scripts": "scripts/*.py + .px/skills/*/scripts/*.py",
            "skills": "registry/skill_catalog.toml:skills",
            "agents": "registry/agency_agent_registry.json:agents",
            "workflow_definitions": "orchestration/workflows/**/*.yaml",
            "orchestrations": "registry/skill_orchestrations.json:workflows",
            "test_modules": "tests/test_*.py",
            "graph_records": "registry/cognitive_map_index.json:records",
            "graph_edges": "registry/cognitive_map_index.json:edges",
            "effect_surfaces": "registry/effect_surface_ownership.json:records",
        },
    }


def build_claim_drift(stored: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Return an exact diagnostic for a non-canonical stored claim set."""
    return (
        ["stored build claims differ from canonical source facts"]
        if stored != expected
        else []
    )


def update_readme_claims(root: Path, claims: dict[str, Any]) -> None:
    """Project canonical build denominators into the README table."""
    path = root.resolve() / "README.md"
    rendered = path.read_text(encoding="utf-8")
    for label, key in README_COUNT_LABELS.items():
        rendered, replacements = re.subn(
            rf"(?m)^\| {re.escape(label)} \| \d+ \|$",
            f"| {label} | {claims['counts'][key]} |",
            rendered,
        )
        if replacements != 1:
            raise ValueError(f"README build-claim row missing or ambiguous: {label}")
    path.write_text(rendered, encoding="utf-8", newline="\n")


def validate_build_claims(root: Path) -> dict[str, Any]:
    """Reject stored build facts or README denominators that drift from source."""
    root = root.resolve()
    expected = expected_build_claims(root)
    errors: list[str] = []
    path = root / CLAIMS_PATH
    try:
        stored = _json(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        stored = None
        errors.append(f"build claims unavailable: {error}")
    if stored is not None:
        errors.extend(build_claim_drift(stored, expected))
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"README unavailable: {error}")
    else:
        for label, key in README_COUNT_LABELS.items():
            match = re.search(rf"(?m)^\| {re.escape(label)} \| (\d+) \|$", readme)
            actual = expected["counts"][key]
            if match is None or int(match.group(1)) != actual:
                errors.append(f"README claim drift: {label} expected {actual}")
        if f"v{expected['version']}" not in readme:
            errors.append("README version claim drift")
    return {
        "schema_version": "px.build-claims-validation/1.0",
        "valid": not errors,
        "claims": expected,
        "errors": errors,
    }
