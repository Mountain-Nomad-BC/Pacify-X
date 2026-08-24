"""Validate packaged Python dependency closure against project declarations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any


def _lock_hash_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line and not line.startswith("--hash"):
            current = line.split("==", 1)[0].casefold()
            counts.setdefault(current, 0)
        if current is not None:
            counts[current] += line.count("--hash=sha256:")
    return counts


def validate_dependency_closure(root: Path) -> dict[str, Any]:
    root = root.resolve()
    registry_path = root / "registry/python_dependency_ownership.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    runtime_dependencies = {
        item.split("=", 1)[0].casefold() for item in project.get("dependencies", [])
    }
    optional = {
        group: {item.split("=", 1)[0].casefold() for item in values}
        for group, values in project.get("optional-dependencies", {}).items()
    }
    errors: list[str] = []
    for record in registry["records"]:
        classification = record["classification"]
        distribution = str(record.get("distribution") or "").casefold()
        if classification == "unclassified":
            errors.append(f"unclassified packaged import: {record['module']}")
        elif classification == "required" and distribution not in runtime_dependencies:
            errors.append(f"undeclared runtime distribution: {record['distribution']}")
        elif (
            classification == "test_only"
            and distribution not in optional.get("test", set())
            and distribution not in optional.get("release", set())
        ):
            errors.append(f"undeclared test distribution: {record['distribution']}")
    lock_path = root / "requirements-release.lock"
    lock_text = lock_path.read_text(encoding="utf-8")
    lock = {
        line.split("==", 1)[0].casefold(): line.split("==", 1)[1]
        for line in lock_text.splitlines()
        if line and not line.startswith("#") and "==" in line
    }
    lock_hash_counts = _lock_hash_counts(lock_text)
    required_release = optional.get("release", set())
    if required_release != set(lock):
        errors.append(
            f"release lock mismatch: missing={sorted(required_release - set(lock))} extra={sorted(set(lock) - required_release)}"
        )
    unhashed = sorted(name for name in lock if lock_hash_counts.get(name, 0) < 1)
    if unhashed:
        errors.append(f"release lock entries without hashes: {unhashed}")
    platform_policy = json.loads(
        (root / "policies/platform-support.json").read_text(encoding="utf-8")
    )
    matrix_size = len(platform_policy.get("python_minors", ())) * len(
        platform_policy.get("ci_runners", {})
    )
    for distribution in ("coverage", "pyyaml"):
        if lock_hash_counts.get(distribution, 0) < matrix_size:
            errors.append(
                f"{distribution} hash allowlist does not cover the supported Python/OS matrix"
            )
    if lock_hash_counts.get("ruff", 0) < len(platform_policy.get("ci_runners", {})):
        errors.append("ruff hash allowlist does not cover the supported OS matrix")
    build_requirements = set(config.get("build-system", {}).get("requires", ()))
    if build_requirements != {"setuptools==84.0.0"}:
        errors.append("build-system backend must be exact-pinned to setuptools==84.0.0")
    lock_install = "python -m pip install --require-hashes -r requirements-release.lock"
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/scheduled-assurance.yml",
    ):
        if lock_install not in (root / relative).read_text(encoding="utf-8"):
            errors.append(f"{relative} does not install the authoritative hash lock")
    release_workflow = (root / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    if (
        "python -m pip download --require-hashes -r requirements-release.lock"
        not in release_workflow
    ):
        errors.append(
            ".github/workflows/release.yml does not materialize the authoritative hash lock"
        )
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "module_count": len(registry["records"]),
        "unclassified": sum(
            item["classification"] == "unclassified" for item in registry["records"]
        ),
        "runtime_dependency_count": len(runtime_dependencies),
        "release_dependency_count": len(required_release),
        "build_requirements": sorted(build_requirements),
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "lock_hash_counts": lock_hash_counts,
        "errors": errors,
    }
