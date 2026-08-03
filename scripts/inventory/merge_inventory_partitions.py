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
from pipeline_common import canonical_json  # noqa: E402


def _records(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {error}") from error
            yield ((record["source_tree"], record["path"], record["id"]), record)


def merge(inputs: list[Path], output: Path, summary_path: Path) -> dict:
    if not inputs:
        raise ValueError("at least one --input is required")
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing partition(s): " + ", ".join(missing))

    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    ids: set[str] = set()
    sources: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    iterators = [_records(path) for path in sorted(inputs, key=lambda item: item.as_posix())]
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for _, record in heapq.merge(*iterators, key=lambda item: item[0]):
            record_id = record["id"]
            if record_id in ids:
                raise ValueError(f"duplicate inventory id: {record_id}")
            ids.add(record_id)
            line = canonical_json(record) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
            sources[record["source_tree"]] += 1
            kinds[record.get("content_kind", "unknown")] += 1
            domains[record.get("probable_domain", "unknown")] += 1
            extensions[record.get("extension") or "[none]"] += 1

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
        "inputs": [path.as_posix() for path in sorted(inputs, key=lambda item: item.as_posix())],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
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
