"""Single runtime projection of the declared Python support policy."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Sequence


def load_platform_support(root: Path) -> dict[str, Any]:
    return json.loads(
        (root.resolve() / "policies/platform-support.json").read_text(encoding="utf-8")
    )


def python_minor_supported(version: Sequence[int], policy: dict[str, Any]) -> bool:
    minor = f"{int(version[0])}.{int(version[1])}"
    return minor in set(map(str, policy.get("python_minors", ())))


def runtime_python_status(
    root: Path, version: Sequence[int] | None = None
) -> dict[str, Any]:
    policy = load_platform_support(root)
    active = tuple(version or sys.version_info[:3])
    supported = python_minor_supported(active, policy)
    return {
        "supported": supported,
        "version": ".".join(map(str, active)),
        "requires_python": policy["python_requires"],
        "supported_minors": list(policy["python_minors"]),
        "reason": None if supported else "python_version_outside_supported_range",
    }
