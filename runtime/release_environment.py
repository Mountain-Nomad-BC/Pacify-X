"""Fail-fast, complete release-toolchain compatibility report."""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
import platform
import sys
from typing import Any


def validate_release_environment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    lock_path = root / "requirements-release.lock"
    required = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "==" in stripped:
            name, version = stripped.split("==", 1)
            required[name.casefold()] = version
    installed = {}
    errors = []
    for distribution, expected in sorted(required.items()):
        try:
            actual = importlib.metadata.version(distribution)
            installed[distribution] = actual
            if actual != expected:
                errors.append(f"{distribution}: installed {actual}, required {expected}")
        except importlib.metadata.PackageNotFoundError:
            installed[distribution] = None
            errors.append(f"{distribution}: missing; install the release dependency group")
    if sys.version_info < (3, 11):
        errors.append("Python 3.11 or newer is required")
    return {
        "schema_version": "1.0", "valid": not errors, "python": platform.python_version(),
        "platform": platform.platform(), "required_count": len(required), "installed": installed,
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(), "errors": errors,
    }
