"""Create a deterministic full-tree freeze manifest for concurrent-mutation gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def snapshot(root: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        stat = path.stat()
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": file_hash(path),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return records


def tree_hash(records: list[dict[str, object]]) -> str:
    payload = "\n".join(
        f"{item['path']}\0{item['sha256']}\0{item['bytes']}\0{item['mtime_ns']}"
        for item in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-alias", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit("freeze root must be a directory")
    records = snapshot(root)
    payload = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_alias": args.source_alias,
        "file_count": len(records),
        "tree_sha256": tree_hash(records),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"file_count": len(records), "tree_sha256": payload["tree_sha256"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
