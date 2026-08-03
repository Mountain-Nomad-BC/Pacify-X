"""Reconcile inventory partition maps into a campaign-level evidence report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build_report(parts_root: Path, *, excluded_ids: set[str] | None = None) -> dict[str, object]:
    excluded_ids = excluded_ids or set()
    parts: list[dict[str, object]] = []
    total_records = total_errors = total_discovered = 0
    digest = hashlib.sha256()
    for directory in sorted((path for path in parts_root.iterdir() if path.is_dir()), key=lambda path: path.name):
        if directory.name in excluded_ids:
            continue
        summary_path = directory / "file_inventory_summary.json"
        inventory_path = directory / "inventory.jsonl"
        if not summary_path.is_file() or not inventory_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        discovered = sum(int(root.get("files_discovered", 0)) for root in summary.get("roots", ()))
        records = int(summary.get("record_count", 0))
        errors = int(summary.get("error_count", 0))
        reconciled = all(root.get("reconciled") is True for root in summary.get("roots", ())) and discovered == records + errors
        part = {
            "id": directory.name,
            "records": records,
            "errors": errors,
            "files_discovered": discovered,
            "reconciled": reconciled,
            "inventory_sha256": summary.get("inventory_sha256"),
            "map": (directory / "inventory.jsonl").as_posix(),
            "error_log": (directory / "file_inventory_errors.jsonl").as_posix(),
        }
        parts.append(part)
        total_records += records
        total_errors += errors
        total_discovered += discovered
        digest.update(json.dumps(part, sort_keys=True, separators=(",", ":")).encode())
    return {
        "schema_version": "1.0", "partition_count": len(parts), "record_count": total_records,
        "error_count": total_errors, "files_discovered": total_discovered,
        "reconciled": total_discovered == total_records + total_errors and all(part["reconciled"] for part in parts),
        "campaign_sha256": digest.hexdigest(), "excluded_partition_ids": sorted(excluded_ids), "partitions": parts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-id", action="append", default=[])
    args = parser.parse_args()
    report = build_report(args.parts_root, excluded_ids=set(args.exclude_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("partition_count", "record_count", "error_count", "files_discovered", "reconciled", "campaign_sha256")}, indent=2))
    return 0 if report["reconciled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
