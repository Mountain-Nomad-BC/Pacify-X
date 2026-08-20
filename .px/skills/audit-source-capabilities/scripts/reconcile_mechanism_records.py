#!/usr/bin/env python3
"""Reconcile every record emitted by the source capability scanner."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconcile(report_path: Path, mappings_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    mapping_doc = json.loads(mappings_path.read_text(encoding="utf-8-sig"))
    mappings = mapping_doc.get("mappings", {})
    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for source in report.get("records", []):
        mechanisms = tuple(map(str, source.get("mechanisms", [])))
        missing = sorted(set(mechanisms) - set(mappings))
        targets = sorted(
            {
                target
                for mechanism in mechanisms
                for target in mappings.get(mechanism, [])
            }
        )
        if missing:
            disposition = "unresolved_mechanism"
        elif source.get("disposition") == "no_reusable_signal":
            disposition = "no_reusable_signal"
        elif source.get("disposition") == "oversize_review_required":
            disposition = "oversize_stream_scanned_and_mapped"
        else:
            disposition = "mechanisms_merged_to_capability_owners"
        counts[disposition] += 1
        results.append(
            {
                "source_path": source["path"],
                "source_sha256": source["sha256"],
                "mechanisms": list(mechanisms),
                "targets": targets,
                "disposition": disposition,
                "missing_mechanisms": missing,
            }
        )
    unresolved = counts["unresolved_mechanism"]
    expected = int(report.get("candidate_count", -1)) + sum(
        1
        for item in report.get("records", [])
        if item.get("disposition") == "no_reusable_signal"
    )
    return {
        "schema_version": "1.0",
        "inputs": {
            "report_sha256": hash_file(report_path),
            "mappings_sha256": hash_file(mappings_path),
        },
        "summary": {
            "records": len(results),
            "expected_records": expected,
            "by_disposition": dict(sorted(counts.items())),
            "unresolved": unresolved,
            "complete": unresolved == 0 and len(results) == expected,
        },
        "records": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--mappings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.report, args.mappings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True))
    return 1 if args.require_complete and not result["summary"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
