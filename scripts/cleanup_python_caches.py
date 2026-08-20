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


CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
BYTECODE_SUFFIXES = {".pyc", ".pyo"}


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
        or (resolved / ".engineering-bootstrap" / "quarantine" / "disposable-cache")
    ).resolve()
    preserved_skills = (resolved / ".px" / "preserved-skills").resolve()
    if quarantine_base == resolved or quarantine_base == Path(quarantine_base.anchor):
        raise ValueError(
            "quarantine root must be a bounded directory distinct from the workspace root"
        )
    directories = sorted(
        (
            path
            for path in resolved.rglob("*")
            if path.is_dir()
            and path.name in CACHE_DIRECTORIES
            and not is_external_environment_relative(path.relative_to(resolved))
            and not _inside(path.resolve(), quarantine_base)
            and not _inside(path.resolve(), preserved_skills)
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    files = sorted(
        path
        for path in resolved.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in BYTECODE_SUFFIXES
        and not is_external_environment_relative(path.relative_to(resolved))
        and not _inside(path.resolve(), quarantine_base)
        and not _inside(path.resolve(), preserved_skills)
        and not any(parent in directories for parent in path.parents)
    )
    for target in [*directories, *files]:
        target.resolve().relative_to(resolved)
    inventory = []
    covered_files = sorted(
        {
            path
            for directory in directories
            for path in directory.rglob("*")
            if path.is_file()
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
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(directory), str(target))
        for path in files:
            if path.exists():
                target = destination / path.relative_to(resolved)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
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
        (destination / "receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
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
    result = cleanup(args.root, apply=args.apply, quarantine_root=args.quarantine_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
