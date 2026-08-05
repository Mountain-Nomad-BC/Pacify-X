"""Deterministic fast/full/release test profile resolution."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .test_runner import validate_timeout


def resolve_test_profile(root: Path, name: str) -> dict[str, Any]:
    root = root.resolve()
    config = json.loads(
        (root / "registry/test_profiles.json").read_text(encoding="utf-8")
    )
    if name not in config["profiles"]:
        raise ValueError(f"unknown test profile: {name}")
    all_tests = sorted(
        path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")
    )
    profile = config["profiles"][name]
    timeout = validate_timeout(profile.get("timeout_seconds"))
    if name == "release":
        source_name = "full"
    else:
        source_name = name
    excluded = set(config["profiles"][source_name].get("exclude_files", []))
    unknown_exclusions = sorted(excluded - set(all_tests))
    if unknown_exclusions:
        raise ValueError(
            "test profile contains unknown exclusions: " + ", ".join(unknown_exclusions)
        )
    members = [path for path in all_tests if path not in excluded]
    return {
        "schema_version": "1.0",
        "valid": True,
        "profile": name,
        "discovered_test_files": len(all_tests),
        "member_count": len(members),
        "members": members,
        "excluded": sorted(excluded),
        "safe_default": "Every new tests/test_*.py file is automatically included in full and release.",
        "timeout_seconds": timeout,
        "profile_budget_seconds": timeout,
        "duration_reporting": 50,
        "gates": profile.get("gates", []),
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--durations=50",
            "-p",
            "no:cacheprovider",
            *members,
        ],
    }
