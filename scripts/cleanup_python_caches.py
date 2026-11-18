"""Move disposable Python/test caches into recoverable quarantine."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.repository_scope import is_external_environment_relative  # noqa: E402
from runtime.bounded_walk import WalkLimits, bounded_walk  # noqa: E402


CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
BYTECODE_SUFFIXES = {".pyc", ".pyo"}


def _is_cleanup_excluded(relative: str) -> bool:
    """Prune external custody without pruning the cache targets themselves."""
    relative_path = Path(relative)
    if relative_path.parts and relative_path.parts[0].casefold() == ".pytest_cache":
        # Repository-root pytest custody is ignored by Git and excluded from
        # every product/export boundary. Do not require access to tool-owned
        # cache internals in order to certify source bytes.
        return True
    parts = tuple(
        part
        for part in relative_path.parts
        if part.casefold() not in CACHE_DIRECTORIES
    )
    return bool(parts) and is_external_environment_relative(Path(*parts))


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def cleanup(
    root: Path, *, apply: bool = False, quarantine_root: Path | None = None
) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir() or resolved == Path(resolved.anchor):
        raise ValueError("root must be an explicit non-filesystem-root directory")
    quarantine_base = (
        quarantine_root
        or (resolved / ".agentic_engineering_os_px" / "quarantine" / "disposable-cache")
    )
    if not quarantine_base.is_absolute():
        quarantine_base = resolved / quarantine_base
    quarantine_base = quarantine_base.resolve()
    if quarantine_base == resolved or quarantine_base == Path(quarantine_base.anchor):
        raise ValueError(
            "quarantine root must be a bounded directory distinct from the workspace root"
        )
    # PX-OS-1067: the quarantine root receives every relocated cache, so it is a destination
    # this producer writes. Confine it to the explicitly selected project, rather than the
    # directory containing this installed tool. A managed project can live elsewhere.
    from runtime.confined_output import confined_path, confined_move

    quarantine_base = confined_path(
        resolved, quarantine_base, label="quarantine_root"
    )
    walk = bounded_walk(
        resolved,
        limits=WalkLimits(max_files=100_000, max_depth=128, max_bytes=2 * 1024**3),
        symlink_policy="skip",
        # Retained quarantine is input custody, never a new cleanup candidate.
        exclude=lambda relative: _inside(resolved / relative, quarantine_base)
        or _is_cleanup_excluded(relative),
    )
    directories = sorted(
        (
            entry.path
            for entry in walk.entries
            if entry.kind == "directory"
            and (entry.path.name.casefold() if sys.platform == "win32" else entry.path.name)
            in CACHE_DIRECTORIES
        ),
        key=lambda path: len(path.parts),
    )
    cache_directories = set(directories)
    # Moving a cache already moves all nested caches. Moving its children first
    # would create overlapping destinations and invalidate the recovery receipt.
    directories = [
        path for path in directories
        if not any(parent in cache_directories for parent in path.parents)
    ]
    if any(_inside(quarantine_base, path) for path in directories):
        raise ValueError("quarantine root must not be inside a selected cache directory")
    files = sorted(
        entry.path
        for entry in walk.files
        if entry.path.suffix.casefold() in BYTECODE_SUFFIXES
        and not any(parent in directories for parent in entry.path.parents)
    )
    for target in [*directories, *files]:
        target.resolve().relative_to(resolved)
    inventory = []
    covered_files = sorted(
        {
            entry.path
            for entry in walk.files
            if any(parent in directories for parent in entry.path.parents)
        }
        | set(files)
    )
    for path in covered_files:
        inventory.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "sha256": _digest(path),
                "bytes": path.stat().st_size,
            }
        )
    quarantine_destination = None
    if apply and (directories or files):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = quarantine_base / stamp
        destination.mkdir(parents=True, exist_ok=False)
        for directory in directories:
            if directory.exists():
                target = destination / directory.relative_to(resolved)
                # Confined relocation: the target is re-checked against the repository before
                # anything moves, and the move is a rename rather than a partial copy.
                confined_move(directory, target, root=resolved, label="quarantine_target")
        for path in files:
            if path.exists():
                target = destination / path.relative_to(resolved)
                confined_move(path, target, root=resolved, label="quarantine_target")
        for item in inventory:
            active = resolved / str(item["path"])
            quarantined = destination / str(item["path"])
            if (
                active.exists()
                or not quarantined.is_file()
                or _digest(quarantined) != item["sha256"]
            ):
                raise RuntimeError(
                    f"cache quarantine reconciliation failed: {item['path']}"
                )
        receipt = {
            "schema_version": "1.0",
            "operation": "recoverable_cache_quarantine",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source_root": ".",
            "quarantine_root": destination.relative_to(resolved).as_posix()
            if _inside(destination, resolved)
            else destination.as_posix(),
            "recovery": "Move a recorded quarantined path back to its original relative source path after review.",
            "records": inventory,
        }
        from runtime.confined_output import publish_json

        # `destination` is derived from the confined `quarantine_base`, so this receipt is
        # inside the repository; publishing it atomically means a crash cannot leave a
        # half-written recovery record pointing at moved files.
        publish_json(quarantine_base, destination / "receipt.json", receipt)
        quarantine_destination = str(receipt["quarantine_root"])
    return {
        "schema_version": "1.0",
        "root": ".",
        "apply": apply,
        "operation": "recoverable_cache_quarantine" if apply else "quarantine_dry_run",
        "cache_directory_count": len(directories),
        "bytecode_file_count": len(files),
        "inventoried_file_count": len(inventory),
        "quarantine_destination": quarantine_destination,
        "hard_delete": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--quarantine-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = None
    if args.output is not None:
        from runtime.confined_output import confined_path

        # Reject an invalid report destination before --apply can move caches.
        output = confined_path(root, args.output)
    result = cleanup(root, apply=args.apply, quarantine_root=args.quarantine_root)
    if output is not None:
        # Reports share the explicitly selected project's confinement boundary.
        from runtime.confined_output import publish_json

        publish_json(root, output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
