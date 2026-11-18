"""Confined, atomic publication for caller-directed report outputs.

PX-OS-1067 requires every caller-directed write to have an independently established
destination. These previously wrote `args.output` directly, which means:

* nothing stopped a destination from leaving the repository;
* a crash mid-write left a truncated report;
* the producer could not be granted an output root because it guaranteed nothing.

`confined_output` gives the six affected producers one shared, tested behaviour:

* the destination is made repository-relative and must resolve strictly inside the root
  (a root that equals the destination is refused, matching the output-root contract);
* a bounded JSON payload is written to a temp file in the destination's own directory,
  flushed, then published with `os.replace`;
* the failure path removes only the temp file this call created.

It never creates the root and never deletes anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .secure_publish import atomic_write_bytes
from .json_io import bounded_json_text

MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


class ConfinementError(ValueError):
    """Raised when a caller-directed destination is not inside the repository root."""


def confined_path(root: Path, destination: Path, *, label: str = "output") -> Path:
    """Resolve `destination` and refuse anything not strictly inside `root`."""
    root = Path(root).resolve()
    candidate = Path(destination)
    original = candidate if candidate.is_absolute() else root / candidate
    # Check original components: resolve() erases both internal and dangling
    # links, allowing an alias to mutate a different retained file in the root.
    from .archive_io import reject_path_links

    try:
        reject_path_links(original)
    except ValueError as error:
        raise ConfinementError(f"{label} must not contain symbolic links or junctions") from error
    resolved = original.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ConfinementError(f"{label} must stay inside the repository root: {resolved}") from error
    if not relative.parts:
        raise ConfinementError(f"{label} must be strictly below the repository root, not the root itself")
    return resolved


def confined_move(source: Path, destination: Path, *, label: str = "move", root: Path | None = None) -> Path:
    """Move between paths strictly inside the selected project (repository by default).

    Used by quarantine and preservation paths, which relocate files rather than publish
    payloads. The destination must be a confined, resolved path; the parent is created, and
    the move publishes by rename so a crash cannot leave a half-copied file.
    """
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    target = confined_path(root, destination, label=label)
    origin = confined_path(root, source, label="move source")
    if target.exists():
        raise ConfinementError(f"{label} destination already exists: {target}")
    if target.is_relative_to(origin):
        raise ConfinementError(f"{label} destination must not be inside its source")
    target.parent.mkdir(parents=True, exist_ok=True)
    # A cross-device rename must fail rather than silently copying and deleting
    # the original. Quarantine requires a complete relocated recovery image.
    origin.rename(target)
    return target


def publish_json(root: Path, destination: Path, payload: Mapping[str, Any] | Any, *, label: str = "output") -> Path:
    """Publish bounded strict JSON values at a confined, repository-relative destination.

    Payloads use JSON dictionaries/lists with string keys and finite numbers.
    Validation and rendering finish before staging or destination creation.
    """
    target = confined_path(root, destination, label=label)
    try:
        # Reserve the newline within the publication ceiling. The shared
        # renderer bounds structure and strings before encoder allocation.
        text = bounded_json_text(payload, max_bytes=MAX_PAYLOAD_BYTES - 1) + "\n"
        encoded = text.encode("utf-8")
    except ValueError as error:
        raise ConfinementError(f"{label} payload is not bounded valid JSON: {error}") from error
    # The registered secure publisher owns exclusive randomized staging and
    # cleanup. Never truncate or reclaim a pre-existing PID-named file here.
    atomic_write_bytes(target, encoded)
    return target
