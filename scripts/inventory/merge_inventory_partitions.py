"""Merge deterministic inventory partitions without loading the corpus into memory."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import heapq
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline_common import canonical_json  # noqa: E402
from runtime.archive_io import reject_path_links  # noqa: E402
from runtime.secure_publish import atomic_write_bytes, atomic_write_stream  # noqa: E402


def _records(path: Path):
    previous_key = None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSONL: {error}"
                ) from error
            if not isinstance(record, dict) or any(
                not isinstance(record.get(field), str)
                for field in ("source_tree", "path", "id")
            ):
                raise ValueError(
                    f"{path}:{line_number}: inventory record requires string source_tree, path and id"
                )
            key = (record["source_tree"], record["path"], record["id"])
            if previous_key is not None and key < previous_key:
                raise ValueError(f"{path}:{line_number}: partition records are not sorted")
            previous_key = key
            yield (key, record)


def merge(inputs: list[Path], output: Path, summary_path: Path) -> dict:
    if not inputs:
        raise ValueError("at least one --input is required")
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing partition(s): " + ", ".join(missing))

    # Refuse lexical, symlink and hardlink aliases before opening any output.
    def same_file(left: Path, right: Path) -> bool:
        return left.resolve() == right.resolve() or (
            left.exists() and right.exists() and left.samefile(right)
        )

    if same_file(output, summary_path) or any(
        same_file(destination, source)
        for destination in (output, summary_path) for source in inputs
    ):
        raise ValueError("merge inputs, output and summary must be distinct files")

    resolved_output, resolved_summary = output.resolve(), summary_path.resolve()
    if resolved_output.is_relative_to(resolved_summary) or resolved_summary.is_relative_to(resolved_output):
        raise ValueError("merge destinations must be distinct files, not parent and child")
    # Both destinations must pass static shape/link checks before the inventory
    # is replaced. The secure publisher still rechecks each file at publication.
    for destination in (output, summary_path):
        reject_path_links(destination.absolute())
        for parent in destination.absolute().parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"merge destination parent is not a directory: {parent}")
        if destination.exists() and (
            not destination.is_file() or destination.stat().st_nlink != 1
        ):
            raise ValueError(f"merge destination must be a physical single-link regular file: {destination}")

    digest = hashlib.sha256()
    count = 0
    ids: set[str] = set()
    sources: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    iterators = [
        _records(path) for path in sorted(inputs, key=lambda item: item.as_posix())
    ]
    def write_inventory(handle):
        nonlocal count
        for _, record in heapq.merge(*iterators, key=lambda item: item[0]):
            record_id = record["id"]
            if record_id in ids:
                raise ValueError(f"duplicate inventory id: {record_id}")
            ids.add(record_id)
            line = canonical_json(record) + "\n"
            encoded = line.encode("utf-8")
            handle.write(encoded)
            digest.update(encoded)
            count += 1
            sources[record["source_tree"]] += 1
            kinds[record.get("content_kind", "unknown")] += 1
            domains[record.get("probable_domain", "unknown")] += 1
            extensions[record.get("extension") or "[none]"] += 1

    try:
        atomic_write_stream(output, write_inventory)
    finally:
        # A rejected record must not retain open partition handles on Windows.
        for iterator in iterators:
            iterator.close()

    summary = {
        "schema_version": "1.0",
        "record_count": count,
        "partition_count": len(inputs),
        "inventory_sha256": digest.hexdigest(),
        "duplicate_id_count": 0,
        "sources": dict(sorted(sources.items())),
        "content_kinds": dict(sorted(kinds.items())),
        "domains": dict(sorted(domains.items())),
        "extensions": dict(extensions.most_common()),
        "inputs": [
            path.as_posix() for path in sorted(inputs, key=lambda item: item.as_posix())
        ],
    }
    atomic_write_bytes(summary_path, (json.dumps(summary, indent=2) + "\n").encode("utf-8"))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(merge(args.input, args.output, args.summary), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
