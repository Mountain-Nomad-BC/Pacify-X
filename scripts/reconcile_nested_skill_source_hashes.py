"""Reconcile nested skill descriptors to their exact acquired source images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from runtime.archive_io import reject_path_links
from runtime.bounded_walk import WalkLimits, bounded_walk
from runtime.input_files import (
    check_deadline,
    contained_file,
    cooperative_deadline,
    read_file_image,
)
from runtime.json_io import decode_json_object


INDEX_NAMES = frozenset(
    {
        "capability-index.json",
        "capabilities-index.json",
        "scripts-index.json",
        "workflow-index.json",
        "orchestration-index.json",
    }
)
MAX_INDEX_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 4096
COLLECTION_KEYS = (
    "records",
    "workflows",
    "orchestrations",
    "capabilities",
    "scripts",
    "formulas",
)


def _index_paths(root: Path, deadline: float) -> list[Path]:
    skills = root / ".px/skills"
    reject_path_links(skills)

    def excluded(relative: str) -> bool:
        parts = relative.split("/")
        return (
            len(parts) == 2
            and parts[1] != "references"
            or len(parts) >= 3
            and (len(parts) != 3 or parts[2] not in INDEX_NAMES)
        )

    walked = bounded_walk(
        skills,
        limits=WalkLimits(
            max_files=MAX_RECORDS,
            max_depth=3,
            max_bytes=64 * 1024 * 1024,
            max_entries=MAX_RECORDS * 4,
            max_directories=MAX_RECORDS,
            max_duration_seconds=max(0.001, deadline - time.monotonic()),
        ),
        exclude=excluded,
    )
    return sorted(item.path for item in walked.files if item.path.name in INDEX_NAMES)


def _image(root: Path, relative: str, deadline: float, limit: int) -> bytes:
    path, info = contained_file(root, relative)
    return bytes(read_file_image(path, info, limit=limit, deadline=deadline))


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    """Update descriptor ``sha256`` fields without altering lineage fields."""

    resolved = root.resolve(strict=True)
    deadline = cooperative_deadline()
    outputs: dict[Path, bytes] = {}
    stale: list[dict[str, str]] = []
    record_count = 0
    total_source_bytes = 0
    source_digests: dict[str, str] = {}
    index_paths = _index_paths(resolved, deadline)
    for index_path in index_paths:
        relative_index = index_path.relative_to(resolved).as_posix()
        raw_index = _image(resolved, relative_index, deadline, MAX_INDEX_BYTES)
        payload = decode_json_object(raw_index, max_bytes=MAX_INDEX_BYTES)
        present = [key for key in COLLECTION_KEYS if key in payload]
        if len(present) > 1:
            raise ValueError(
                f"nested skill index collection is ambiguous: {relative_index}"
            )
        records = payload.get(present[0], []) if present else []
        if not isinstance(records, list):
            raise ValueError(f"nested skill index records are invalid: {relative_index}")
        changed = False
        for item in records:
            check_deadline(deadline)
            record_count += 1
            if record_count > MAX_RECORDS or not isinstance(item, dict):
                raise ValueError("nested skill descriptor denominator is invalid")
            if "sha256" not in item:
                # Named workflow source_sha256 values are lineage identifiers.
                # They are validated against their named source records by the
                # cognitive compiler and must never be rewritten as byte hashes.
                continue
            relative_source = str(item.get("path") or "")
            actual = source_digests.get(relative_source)
            if actual is None:
                source = _image(resolved, relative_source, deadline, MAX_SOURCE_BYTES)
                total_source_bytes += len(source)
                if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
                    raise ValueError(
                        "nested skill source denominator exceeds byte budget"
                    )
                actual = hashlib.sha256(source).hexdigest()
                source_digests[relative_source] = actual
            declared = item.get("sha256")
            if declared != actual:
                stale.append(
                    {
                        "index": relative_index,
                        "id": str(item.get("id") or ""),
                        "path": relative_source,
                        "declared": str(declared or ""),
                        "actual": actual,
                    }
                )
                item["sha256"] = actual
                changed = True
        if changed:
            outputs[index_path] = (
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
    if not check:
        for path, payload in outputs.items():
            prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
            prepared.write_bytes(payload)
            os.replace(prepared, path)
    return {
        "schema_version": "px.nested-skill-source-hash-reconciliation/1.0",
        "valid": not stale if check else True,
        "check": check,
        "index_count": len(index_paths),
        "record_count": record_count,
        "distinct_source_count": len(source_digests),
        "source_bytes": total_source_bytes,
        "changed_indices": sorted(
            path.relative_to(resolved).as_posix() for path in outputs
        ),
        "stale": stale,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root, check=args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
