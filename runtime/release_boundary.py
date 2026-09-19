"""Canonical clean-product materialization shared by preflight and finalization.

IMPORTANT: Operational gap ledger deltas are runtime checkpoint dependencies.
Wherever an operational_gap_ledger.head.json is retained, its exact referenced
delta files MUST also be preserved through any sanitation, reconstruction, or
archive operation.

This is an invariant: a retained delta-dependent head and its referenced deltas
form one persistence unit.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from .repository_scope import is_external_environment_relative


def copy_clean_product(source: Path, destination: Path) -> None:
    """Materialize the exact clean product boundary used by finalization.
    
    INVARIANT: If operational_gap_ledger.head.json exists and references a delta,
    that exact delta file MUST be preserved in the copy. Deltas are runtime
    checkpoint dependencies, not disposable mutable projections.
    """
    source = source.resolve()
    
    # Identify required deltas before deciding what to exclude
    required_deltas = set()
    head_path = source / "registry" / "operational_gap_ledger.head.json"
    if head_path.is_file():
        try:
            head = json.load(head_path.open(encoding="utf-8"))
            if isinstance(head, dict):
                delta_projection = head.get("delta_projection")
                if delta_projection and isinstance(delta_projection, dict):
                    delta_path = delta_projection.get("path")
                    if delta_path:
                        # Normalize to relative form for comparison
                        required_deltas.add(str(delta_path).replace("\\", "/"))
        except (OSError, json.JSONDecodeError):
            # If we can't read the head, don't assume deltas are safe to omit
            pass
    
    generated = shutil.ignore_patterns(
        ".git",
        ".quarantine",  # Boundary protection: retained historical evidence with preserved junctions
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "*.pyc",
        "*.pyo",
        ".test-orchestration.lock",
        "*.egg-info",
        "build",
        "dist",
        "evidence",
        "release-transaction.json",
    )

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative_directory = Path(directory).resolve().relative_to(source)
        ignored = set(generated(directory, names))
        for name in names:
            relative = relative_directory / name
            relative_posix = relative.as_posix()
            
            # INVARIANT: Preserve required operational ledger deltas
            if relative_posix in required_deltas:
                ignored.discard(name)
                continue
            
            # The finalizer holds this mutable control file while it freezes the
            # product.  Copying the locked byte fails on Windows, and the release
            # policy already excludes the file from product identity.
            if relative_posix.casefold() == ".engineering-bootstrap/release.lock":
                ignored.add(name)
            elif is_external_environment_relative(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)
