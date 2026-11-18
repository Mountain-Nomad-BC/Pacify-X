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
from pathlib import Path, PurePosixPath
import shutil

from .repository_scope import is_external_environment_relative


def copy_clean_product(source: Path, destination: Path) -> None:
    """Materialize the exact clean product boundary used by finalization.
    
    INVARIANT: If operational_gap_ledger.head.json exists and references a delta,
    that exact delta file MUST be preserved in the copy. Deltas are runtime
    checkpoint dependencies, not disposable mutable projections.
    """
    source = source.resolve()
    
    # Identify required deltas before deciding what to exclude. A retained head
    # cannot authorize copying arbitrary host/evidence custody into the product.
    from .archive_io import reject_path_links
    from .operational_gap_ledger import DELTA_DIRECTORY_RELATIVE, _referenced_delta_paths

    required_deltas = set()
    head_path = source / "registry" / "operational_gap_ledger.head.json"
    if head_path.is_file():
        reject_path_links(head_path)
        head = json.loads(head_path.read_text(encoding="utf-8"))
        if not isinstance(head, dict):
            raise ValueError("retained ledger head must be an object")
        prefix = DELTA_DIRECTORY_RELATIVE.parts
        for raw in _referenced_delta_paths(head):
            reference = PurePosixPath(raw.replace("\\", "/"))
            if (reference.is_absolute() or ".." in reference.parts
                    or reference.parts[:len(prefix)] != prefix
                    or len(reference.parts) <= len(prefix)):
                raise ValueError("retained ledger delta must stay in the canonical checkpoint directory")
            delta = source / reference.as_posix()
            reject_path_links(delta)
            if not delta.is_file():
                raise ValueError("required ledger delta is missing: " + reference.as_posix())
            required_deltas.add(reference.as_posix())

    preserved_dependencies = required_deltas | {
        parent.as_posix() for relative in required_deltas
        for parent in PurePosixPath(relative).parents if parent.parts
    }
    if required_deltas:
        # A delta-dependent head and its referenced images form one retained
        # persistence unit; copying only either half creates an orphan.
        preserved_dependencies.add(head_path.relative_to(source).as_posix())
    
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
            if relative_posix in preserved_dependencies:
                ignored.discard(name)
                continue
            
            # The finalizer holds this mutable control file while it freezes the
            # product.  Copying the locked byte fails on Windows, and the release
            # policy already excludes the file from product identity.
            if relative_posix.casefold() == ".agentic_engineering_os_px/release.lock":
                ignored.add(name)
            elif is_external_environment_relative(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)
