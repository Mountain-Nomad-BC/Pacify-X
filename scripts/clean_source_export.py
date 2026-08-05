"""Create a deterministic, non-destructive source handoff archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}
ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def included_files(root: Path, output: Path | None = None) -> tuple[Path, ...]:
    resolved_output = output.resolve() if output else None
    records = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if (
            EXCLUDED_DIRS.intersection(relative.parts)
            or not path.is_file()
            or path.is_symlink()
            or path.suffix.casefold() in EXCLUDED_SUFFIXES
            or (resolved_output is not None and path.resolve() == resolved_output)
        ):
            continue
        records.append(path)
    return tuple(
        sorted(records, key=lambda item: item.relative_to(root).as_posix().casefold())
    )


def create_clean_export(root: Path, output: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    output = output.resolve()
    files = included_files(root, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            info = zipfile.ZipInfo(relative, ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
            records.append(
                {
                    "path": relative,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    payload = {
        "schema_version": "1.0",
        "file_count": len(records),
        "records_sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "hard_delete": False,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_clean_export(args.root, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
