"""Create one content-addressed, deduplicated catalog while mapping every ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _entry_map(archive: Path) -> tuple[str, list[dict[str, object]]]:
    entries: list[dict[str, object]] = []
    with ZipFile(archive) as handle:
        for item in handle.infolist():
            if item.is_dir():
                continue
            entries.append(
                {
                    "path_sha256": _sha_bytes(
                        item.filename.replace("\\", "/").encode()
                    ),
                    "bytes": item.file_size,
                    "compressed_bytes": item.compress_size,
                    "crc32": f"{item.CRC:08x}",
                }
            )
    entries.sort(key=lambda item: str(item["path_sha256"]))
    tree = _sha_bytes(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    )
    return tree, entries


def build_catalog(root: Path) -> dict[str, object]:
    root = root.resolve()
    unique: dict[str, dict[str, object]] = {}
    occurrences: list[dict[str, object]] = []
    for archive in sorted(root.rglob("*.zip")):
        relative = archive.relative_to(root).as_posix()
        archive_sha = _sha_bytes(archive.read_bytes())
        occurrence = {
            "source_path_sha256": _sha_bytes(relative.encode()),
            "archive_sha256": archive_sha,
            "bytes": archive.stat().st_size,
            "status": "mapped",
        }
        try:
            tree, entries = _entry_map(archive)
            if archive_sha not in unique:
                unique[archive_sha] = {
                    "archive_sha256": archive_sha,
                    "bytes": archive.stat().st_size,
                    "entry_tree_sha256": tree,
                    "entry_count": len(entries),
                    "entries": entries,
                }
        except BadZipFile:
            occurrence["status"] = "invalid_zip"
        occurrences.append(occurrence)
    return {
        "schema_version": "2.0",
        "mapping": "one occurrence per ZIP; identical archive bytes share one entry map",
        "source_occurrence_count": len(occurrences),
        "unique_archive_count": len(unique),
        "occurrences": occurrences,
        "archives": [unique[key] for key in sorted(unique)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    catalog = build_catalog(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: catalog[key]
                for key in ("source_occurrence_count", "unique_archive_count")
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
