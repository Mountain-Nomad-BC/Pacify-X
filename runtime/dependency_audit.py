"""Validate packaged Python dependency closure against project declarations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any


def validate_dependency_closure(root: Path) -> dict[str, Any]:
    root = root.resolve()
    registry_path = root / "registry/python_dependency_ownership.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    runtime_dependencies = {item.split("=", 1)[0].casefold() for item in project.get("dependencies", [])}
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
        elif classification == "test_only" and distribution not in optional.get("test", set()) and distribution not in optional.get("release", set()):
            errors.append(f"undeclared test distribution: {record['distribution']}")
    lock_path = root / "requirements-release.lock"
    lock = {
        line.split("==", 1)[0].casefold(): line.split("==", 1)[1]
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "==" in line
    }
    required_release = optional.get("release", set())
    if required_release != set(lock):
        errors.append(f"release lock mismatch: missing={sorted(required_release-set(lock))} extra={sorted(set(lock)-required_release)}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "module_count": len(registry["records"]),
        "unclassified": sum(item["classification"] == "unclassified" for item in registry["records"]),
        "runtime_dependency_count": len(runtime_dependencies),
        "release_dependency_count": len(required_release),
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "errors": errors,
    }
