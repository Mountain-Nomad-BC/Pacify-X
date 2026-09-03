"""Independent authority checks for repository-context release gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any


RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT = (
    ".engineering-bootstrap/processing-order/repair-campaign.json",
    ".engineering-bootstrap/processing-order/release-identity.json",
    "evidence/README.md",
    "evidence/externalized-payload-index.json",
    "registry/corrective_release_ledger.json",
    "registry/operational_gap_ledger.head.json",
    "registry/operational_gap_ledger.jsonl",
    "registry/operational_gap_ledger.snapshot.json",
)


def validate_release_gate_repository_context(root: Path) -> dict[str, Any]:
    """Fail early unless repository-context release gates have their authorities."""
    resolved = root.resolve()
    missing: list[str] = []
    if not (resolved / ".git").exists():
        missing.append(".git")
    missing.extend(
        relative
        for relative in RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT
        if not (resolved / relative).is_file()
    )
    return {
        "schema_version": "px.release-gate-repository-context/1.0",
        "valid": not missing,
        "required": [".git", *RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT],
        "missing": missing,
        "errors": [
            f"authenticated release repository context is missing: {relative}"
            for relative in missing
        ],
    }
