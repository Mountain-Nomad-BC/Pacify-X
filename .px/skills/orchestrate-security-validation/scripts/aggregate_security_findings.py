#!/usr/bin/env python3
"""Aggregate scanner envelopes without copying scanner payloads into the summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

STATUSES = {"pass", "fail", "blocked", "skipped", "uncertain"}


def _digest(value: object) -> str:
    material = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def aggregate(root: Path) -> dict:
    records: list[dict] = []
    errors: list[dict] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            status = str(data.get("status", "uncertain")).lower()
            status = status if status in STATUSES else "uncertain"
            findings = data.get("findings", [])
            if not isinstance(findings, list):
                raise ValueError("findings must be a list")
            tool = str(data.get("tool", path.stem))
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                records.append(
                    {
                        "tool": tool,
                        "status": status,
                        "severity": str(finding.get("severity", "unknown")).lower(),
                        "location": str(finding.get("location", "unknown")),
                        "message_sha256": _digest(finding.get("message", finding)),
                    }
                )
            if not findings:
                records.append(
                    {
                        "tool": tool,
                        "status": status,
                        "severity": "none",
                        "location": "scanner",
                        "message_sha256": _digest(data.get("summary", status)),
                    }
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(
                {"file": path.name, "status": "blocked", "error": type(exc).__name__}
            )
    records.sort(
        key=lambda item: (item["tool"], item["location"], item["message_sha256"])
    )
    counts = Counter(item["status"] for item in records)
    return {
        "schema_version": "1.0",
        "complete": not errors,
        "eligible_scanners": len(list(root.glob("*.json"))),
        "reported_records": len(records),
        "status_counts": {key: counts.get(key, 0) for key in sorted(STATUSES)},
        "records": records,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(args.input.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"complete": result["complete"], "records": result["reported_records"]}
        )
    )
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
