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

import json
import os
from pathlib import Path
from typing import Any, Mapping

MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


class ConfinementError(ValueError):
    """Raised when a caller-directed destination is not inside the repository root."""


def confined_path(root: Path, destination: Path, *, label: str = "output") -> Path:
    """Resolve `destination` and refuse anything not strictly inside `root`."""
    root = Path(root).resolve()
    candidate = Path(destination)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ConfinementError(f"{label} must stay inside the repository root: {resolved}") from error
    if not relative.parts:
        raise ConfinementError(f"{label} must be strictly below the repository root, not the root itself")
    # `..` cannot survive resolve(), but a symlinked destination could point back out.
    if Path(root, relative).is_symlink():
        raise ConfinementError(f"{label} must not be a symbolic link: {resolved}")
    return resolved


def confined_move(source: Path, destination: Path, *, label: str = "move") -> Path:
    """Move `source` to `destination` when the destination is inside the repository.

    Used by quarantine and preservation paths, which relocate files rather than publish
    payloads. The destination must be a confined, resolved path; the parent is created, and
    the move publishes by rename so a crash cannot leave a half-copied file.
    """
    import shutil as _shutil

    target = Path(destination)
    root = Path(__file__).resolve().parents[1]
    confined_path(root, target, label=label)
    target.parent.mkdir(parents=True, exist_ok=True)
    _shutil.move(str(Path(source)), str(target))
    return target


def publish_json(root: Path, destination: Path, payload: Mapping[str, Any] | Any, *, label: str = "output") -> Path:
    """Atomically publish `payload` as JSON at a confined, repository-relative destination."""
    target = confined_path(root, destination, label=label)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ConfinementError(f"{label} payload exceeds {MAX_PAYLOAD_BYTES} bytes")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return target
