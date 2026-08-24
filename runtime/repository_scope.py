"""Shared product-source boundary for repository-wide audits."""

from __future__ import annotations

from pathlib import Path


EXTERNAL_ENVIRONMENT_ROOTS = frozenset({"Python", "node_modules", ".tmp"})
CANONICAL_WORKSPACE_CUSTODY_ROOTS = frozenset(
    {"projects", "projects_tracking", "repo_quarantine", "shared_capabilities"}
)
EXTERNAL_ENVIRONMENT_PARTS = frozenset({"node_modules", ".vscode-test"})
DERIVED_CUSTODY_ROOTS = frozenset(
    {
        ".lock-recovery-receipts",
        "coordination",
        "diagnostics",
        "environment",
        "project-map",
        "project-map-history",
        "project-map-history-archives",
        "project-map-lock-history",
        "runtime-core",
        "quarantine",
        "operation-bus",
        "resource-lifecycle",
        "studios",
    }
)
LOCAL_TEST_EVIDENCE_ROOTS = frozenset(
    {
        "adversarial-repair-gates",
        "github-reconciliation-gates",
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
        or top in CANONICAL_WORKSPACE_CUSTODY_ROOTS
        or normalized_top.startswith(".tmp")
        or normalized_top.startswith("tmp_")
        or normalized_top.startswith(".vscodecounter")
        or top.startswith(".venv")
        or any(part in EXTERNAL_ENVIRONMENT_PARTS for part in parts)
        or any(part.startswith(".venv") for part in parts)
        or top == ".git"
        or parts[:2]
        in {
            (".px", "global-skill-isolation"),
            (".px", "preserved-skills"),
            (".px", "preserved-extension-installations"),
        }
        or (
            len(parts) >= 2
            and parts[0] == ".engineering-bootstrap"
            and parts[1] in DERIVED_CUSTODY_ROOTS
        )
        or (
            len(parts) >= 3
            and parts[:2] == (".engineering-bootstrap", "test-evidence")
            and parts[2] in LOCAL_TEST_EVIDENCE_ROOTS
        )
    )


def is_project_source(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return not is_external_environment_relative(relative)
