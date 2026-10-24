"""Canonical engineering-OS control directory name, with legacy compatibility.

Owner decision (2026-10-04)
--------------------------
``.agentic_engineering_os_px`` is the canonical control directory name for this
repository and for every project PX manages going forward. ``.engineering-bootstrap``
is the legacy name. It is accepted for **reading** only, so historical state and
immutable evidence stay reachable, but nothing new is written to it.

Why this module exists instead of a search-and-replace
------------------------------------------------------
The legacy name is embedded in more than just paths:

* 63 hash-verified evidence receipts embed the literal path
  ``.engineering-bootstrap/test-evidence/...`` and bind its sha256;
* thousands of preserved evidence artifacts live under that tree;
* roughly thirty runtime modules construct paths under it.

Renaming the tree would silently break every one of those recorded references,
which is evidence-custody destruction rather than a refactor. So the canonical
name is established here as a single owner that every consumer resolves through,
and migration happens in bounded slices against that owner.

The contract
------------
* :func:`resolve` prefers the canonical directory and falls back to the legacy
  one, so a partially migrated tree still works in both directions.
* :func:`control_path` is the only sanctioned way to build a control path.
* :func:`is_control_relative` classifies a repository-relative path without
  assuming a single spelling.
* :func:`legacy_references` enumerates legacy spellings for migration tooling.

This module never moves, copies, deletes or rewrites anything. It resolves
names only. Migration is explicit, admitted work performed by other owners.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

CANONICAL_CONTROL_DIR = ".agentic_engineering_os_px"
LEGACY_CONTROL_DIR = ".engineering-bootstrap"

#: Owner decision 2026-10-04: ALL of the former "engineering-bootstrap" naming
#: changes to match. That spans three namespaces, so the installed data
#: directory and the public console script are declared here too rather than
#: being spelled inline wherever they appear.
CANONICAL_DISTRIBUTION_DIR = "agentic-engineering-os-px"
LEGACY_DISTRIBUTION_DIR = "engineering-bootstrap"

CANONICAL_CONSOLE_SCRIPT = "agentic-engineering-os-px"
LEGACY_CONSOLE_SCRIPT = "engineering-bootstrap"

#: The importable distribution name. Source imports stay on ``runtime``; this is
#: only the name the distribution is installed under, per [tool.setuptools]
#: package-dir in pyproject.toml.
CANONICAL_DISTRIBUTION_PACKAGE = "agentic_engineering_os_px"
LEGACY_DISTRIBUTION_PACKAGE = "engineering_bootstrap"

#: Legacy name first so a naive scan reports the superseding name first too.
CONTROL_DIR_NAMES: tuple[str, ...] = (CANONICAL_CONTROL_DIR, LEGACY_CONTROL_DIR)

#: Names that must all agree on the canonical spelling going forward.
CANONICAL_NAMES: tuple[str, ...] = (
    CANONICAL_CONTROL_DIR,
    CANONICAL_DISTRIBUTION_DIR,
    CANONICAL_CONSOLE_SCRIPT,
    CANONICAL_DISTRIBUTION_PACKAGE,
)

#: Canonical name wins when both directories exist. This is deliberate: a
#: half-migrated tree must not serve stale legacy state as if it were current.
CANONICAL_FIRST = True

MAX_CONTROL_PATH_SEGMENTS = 32
MAX_CONTROL_SEGMENT_CHARS = 128


class EngineeringOsPathError(ValueError):
    """Raised when a requested control path is not resolvable."""


def _bounded_segments(parts: tuple[str, ...]) -> tuple[str, ...]:
    if not parts:
        return ()
    if len(parts) > MAX_CONTROL_PATH_SEGMENTS:
        raise EngineeringOsPathError("control path has too many segments")
    bounded: list[str] = []
    for part in parts:
        if not isinstance(part, str) or not part.strip():
            raise EngineeringOsPathError("control path segment must be nonempty text")
        if len(part) > MAX_CONTROL_SEGMENT_CHARS:
            raise EngineeringOsPathError("control path segment exceeds its bound")
        candidate = PurePosixPath(part)
        if candidate.is_absolute() or any(
            segment in {"..", "."} for segment in candidate.parts
        ):
            raise EngineeringOsPathError("control path segment must be relative")
        bounded.append(candidate.as_posix())
    return tuple(bounded)


def control_root(root: Path) -> Path:
    """Return the canonical control directory for a repository root.

    This is the location new state is written to. It does not need to exist
    yet; creating it is the caller's admitted business.
    """
    return Path(root) / CANONICAL_CONTROL_DIR


def legacy_control_root(root: Path) -> Path:
    """Return the legacy control directory, for reading preserved history."""
    return Path(root) / LEGACY_CONTROL_DIR


def _entry_count(directory: Path) -> int:
    """Count a directory's immediate entries, treating any read error as empty."""
    try:
        with os.scandir(directory) as entries:
            return sum(1 for _ in entries)
    except OSError:
        return 0


def resolve(root: Path, *parts: str) -> Path:
    """Resolve a control path, preferring the canonical directory.

    Both spellings can be real at once: the canonical directory holds new state
    while the legacy directory holds the preserved evidence tree, including the
    hash-verified receipts whose recorded paths must keep resolving. So existence
    alone cannot decide. For a directory request the spelling holding more entries
    wins, which keeps the evidence tree reachable instead of hiding it behind a
    nearly-empty canonical directory; ties keep canonical. For a file request the
    spelling that actually holds the file wins. New state still defaults to
    canonical when neither spelling has the path.
    """
    segments = _bounded_segments(parts)
    canonical = Path(root) / Path(CANONICAL_CONTROL_DIR, *segments) if segments else (
        Path(root) / CANONICAL_CONTROL_DIR
    )
    legacy = Path(root) / Path(LEGACY_CONTROL_DIR, *segments) if segments else (
        Path(root) / LEGACY_CONTROL_DIR
    )
    if canonical.is_dir() and legacy.is_dir():
        # Both spellings hold a directory. Prefer whichever actually holds the
        # preserved content, so recorded evidence references stay resolvable.
        if _entry_count(canonical) >= _entry_count(legacy):
            return canonical
        return legacy
    if canonical.exists():
        return canonical
    if legacy.exists():
        return legacy
    # Neither exists: return the canonical target so new state lands in the
    # canonical location by default rather than in the legacy one.
    return canonical


def exists(root: Path, *parts: str) -> bool:
    """True when the requested control path exists under either spelling."""
    return resolve(root, *parts).exists()


def _head_segment(relative: str) -> str:
    """Return the first path segment, normalized.

    ``str.lstrip('./')`` is wrong here: it strips CHARACTERS, so it would eat
    the leading dot of ``.agentic_engineering_os_px`` and the name could never
    match itself. Only a literal leading ``./`` may be removed.
    """
    normalized = relative.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.split("/", 1)[0]


def is_control_relative(relative: str) -> bool:
    """Classify a repository-relative path as control-relative or not.

    Accepts both spellings so migration tooling and boundary checks keep working
    across a partially migrated tree.
    """
    if not isinstance(relative, str) or not relative.strip():
        return False
    return _head_segment(relative) in CONTROL_DIR_NAMES


def uses_canonical_name(relative: str) -> bool:
    """True when the path is already spelled with the canonical name."""
    if not isinstance(relative, str) or not relative.strip():
        return False
    return _head_segment(relative) == CANONICAL_CONTROL_DIR


def legacy_references(relative: str) -> bool:
    """True when a path or literal still carries the legacy spelling."""
    return isinstance(relative, str) and LEGACY_CONTROL_DIR in relative


def distribution_data_dir(data_root: Path) -> Path:
    """Resolve the installed framework data directory, preferring canonical.

    Installs laid down before the rename keep the legacy directory name. Both
    are accepted so an existing installation continues to work, but the
    canonical spelling is probed first so a freshly installed copy is found.
    """
    data_root = Path(data_root)
    canonical = data_root / "share" / CANONICAL_DISTRIBUTION_DIR
    legacy = data_root / "share" / LEGACY_DISTRIBUTION_DIR
    if (canonical / "bootstrap" / "startup.toml").is_file():
        return canonical
    if (legacy / "bootstrap" / "startup.toml").is_file():
        return legacy
    # Neither is installed; report the canonical target so failures name the
    # spelling the project now standardizes on.
    return canonical


def policy_snapshot() -> dict[str, object]:
    """Exact naming policy, suitable for a manifest or an evidence record."""
    return {
        "schema_version": "px.engineering-os-paths/1.0",
        "canonical_control_dir": CANONICAL_CONTROL_DIR,
        "legacy_control_dir": LEGACY_CONTROL_DIR,
        "control_dir_names": list(CONTROL_DIR_NAMES),
        "canonical_distribution_dir": CANONICAL_DISTRIBUTION_DIR,
        "legacy_distribution_dir": LEGACY_DISTRIBUTION_DIR,
        "canonical_console_script": CANONICAL_CONSOLE_SCRIPT,
        "legacy_console_script": LEGACY_CONSOLE_SCRIPT,
        "canonical_distribution_package": CANONICAL_DISTRIBUTION_PACKAGE,
        "legacy_distribution_package": LEGACY_DISTRIBUTION_PACKAGE,
        "canonical_first": CANONICAL_FIRST,
        "legacy_write_allowed": False,
        "legacy_read_allowed": True,
        "rule": (
            "New state is written under the canonical control directory only. "
            "The legacy directory is read for preserved history and immutable "
            "evidence, whose recorded references keep resolving. No bulk rename "
            "is performed: migration is explicit, admitted, reversible work. "
            "The installed data directory and the public console script adopt "
            "the canonical spelling, while an install laid down under the legacy "
            "spelling stays readable so it is not bricked."
        ),
    }