"""Shared product-source boundary for repository-wide audits."""

from __future__ import annotations

from pathlib import Path


EXTERNAL_ENVIRONMENT_ROOTS = frozenset({"Python", "node_modules", ".tmp"})
EXTERNAL_ENVIRONMENT_PARTS = frozenset({"node_modules", ".vscode-test"})
DERIVED_CUSTODY_ROOTS = frozenset(
    {
        "diagnostics",
        "environment",
        "project-map",
        "project-map-history",
        "project-map-lock-history",
        "quarantine",
        "operation-bus",
        "resource-lifecycle",
    }
)


def is_external_environment_relative(relative: str | Path) -> bool:
    """Identify non-product dependency or retained-custody trees without scanning them."""
    parts = Path(relative).parts
    if not parts:
        return False
    top = parts[0]
    normalized_top = top.casefold()
    return (
        top in EXTERNAL_ENVIRONMENT_ROOTS
        or normalized_top.startswith(".tmp")
        or normalized_top.startswith("tmp_")
        or normalized_top.startswith(".vscodecounter")
        or top.startswith(".venv")
        or any(part in EXTERNAL_ENVIRONMENT_PARTS for part in parts)
        or any(part.startswith(".venv") for part in parts)
        or top == ".git"
        or parts[:2]
        in {
            (".px", "preserved-skills"),
            (".px", "preserved-extension-installations"),
        }
        or (
            len(parts) >= 2
            and parts[0] == ".engineering-bootstrap"
            and parts[1] in DERIVED_CUSTODY_ROOTS
        )
    )


def is_project_source(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return not is_external_environment_relative(relative)
