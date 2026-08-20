#!/usr/bin/env python3
"""Reconcile every finding in historical incomplete-implementation reports."""

from __future__ import annotations

import argparse
import fnmatch
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


def reconcile(
    report_path: Path, source_root: Path, policy_path: Path
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    hashes: dict[Path, str] = {}
    for finding in report.get("findings", []):
        relative = str(finding["path"]).replace("\\", "/")
        decision = next(
            (
                rule
                for rule in policy.get("rules", [])
                if fnmatch.fnmatchcase(relative, str(rule["path_glob"]))
            ),
            None,
        )
        result = {
            "finding_id": finding["id"],
            "source_path": relative,
            "line": finding["line"],
            "rule": finding["rule"],
        }
        source = source_root.joinpath(*Path(relative).parts)
        if source.is_file():
            if source not in hashes:
                hashes[source] = hash_file(source)
            result["source_sha256"] = hashes[source]
        else:
            result["source_missing"] = True
        if decision:
            result.update(
                disposition=decision["disposition"],
                disposition_rule=decision["id"],
                targets=decision.get("targets", []),
            )
        else:
            result.update(disposition="unresolved", targets=[])
        counts[result["disposition"]] += 1
        results.append(result)
    unresolved = counts["unresolved"]
    return {
        "schema_version": "1.0",
        "inputs": {
            "report_sha256": hash_file(report_path),
            "policy_sha256": hash_file(policy_path),
        },
        "summary": {
            "findings": len(results),
            "unique_source_files": len(hashes),
            "by_disposition": dict(sorted(counts.items())),
            "unresolved": unresolved,
            "complete": unresolved == 0
            and len(results) == int(report.get("finding_count", -1)),
        },
        "records": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.report, args.source_root, args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True))
    return 1 if args.require_complete and not result["summary"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
