#!/usr/bin/env python3
"""Resolve every staged capability candidate through an explicit, deterministic policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any


ALLOWED_DISPOSITIONS = {
    "ADOPT",
    "MERGE",
    "WRAP",
    "REFERENCE",
    "SUPERSEDE",
    "DEFER",
    "REJECT",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _matches(rule: dict[str, Any], candidate: dict[str, Any]) -> bool:
    when = rule.get("when", {})
    if when.get("presence") and candidate.get("presence") != when["presence"]:
        return False
    if when.get("kinds") and candidate.get("kind") not in when["kinds"]:
        return False
    if when.get("ids") and candidate.get("id") not in when["ids"]:
        return False
    if when.get("id_regex") and not re.search(
        when["id_regex"], candidate.get("id", "")
    ):
        return False
    source_text = "\n".join(
        str(item.get("path", "")) for item in candidate.get("sources", [])
    )
    if when.get("source_contains") and when["source_contains"] not in source_text:
        return False
    return True


def _catalog_ids(path: Path) -> set[str]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {str(item["id"]) for item in data.get("skills", [])}


def reconcile(
    candidate_path: Path, policy_path: Path, catalog_path: Path
) -> dict[str, Any]:
    source = json.loads(candidate_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    candidates = source.get("candidates", [])
    rules = policy.get("rules", [])
    owners = _catalog_ids(catalog_path)
    seen: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for candidate in sorted(
        candidates, key=lambda item: (str(item.get("kind")), str(item.get("id")))
    ):
        key = (str(candidate.get("kind", "")), str(candidate.get("id", "")))
        if not all(key) or key in seen:
            errors.append(
                {"candidate": list(key), "error": "missing-or-duplicate-identity"}
            )
            continue
        seen.add(key)
        matches = [rule for rule in rules if _matches(rule, candidate)]
        if not matches:
            errors.append({"candidate": list(key), "error": "no-disposition-rule"})
            continue
        max_priority = max(int(rule.get("priority", 0)) for rule in matches)
        selected = [
            rule for rule in matches if int(rule.get("priority", 0)) == max_priority
        ]
        if len(selected) != 1:
            errors.append(
                {
                    "candidate": list(key),
                    "error": "ambiguous-disposition",
                    "rules": [r.get("id") for r in selected],
                }
            )
            continue
        rule = selected[0]
        disposition = str(rule.get("disposition", "")).upper()
        targets = [str(value) for value in rule.get("targets", [])]
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(
                {
                    "candidate": list(key),
                    "error": "invalid-disposition",
                    "value": disposition,
                }
            )
            continue
        if candidate.get("presence") == "manifest-only" and disposition in {
            "ADOPT",
            "SUPERSEDE",
        }:
            errors.append(
                {
                    "candidate": list(key),
                    "error": "absent-artifact-cannot-be-implementation-evidence",
                }
            )
            continue
        unknown = sorted(set(targets) - owners)
        if unknown:
            errors.append(
                {
                    "candidate": list(key),
                    "error": "unknown-target-owner",
                    "targets": unknown,
                }
            )
            continue
        if (
            disposition in {"ADOPT", "MERGE", "WRAP", "REFERENCE", "SUPERSEDE"}
            and not targets
        ):
            errors.append({"candidate": list(key), "error": "owner-required"})
            continue
        records.append(
            {
                "kind": key[0],
                "id": key[1],
                "presence": candidate.get("presence"),
                "disposition": disposition,
                "targets": targets,
                "rule": rule["id"],
                "rationale": rule["rationale"],
                "preserve": rule.get("preserve", []),
                "tests_required": rule.get("tests_required", []),
                "sources": candidate.get("sources", []),
            }
        )

    expected = len(candidates)
    counts = Counter(record["disposition"] for record in records)
    return {
        "schema_version": "1.0",
        "inputs": {
            "candidate_inventory_sha256": _sha256(candidate_path),
            "policy_sha256": _sha256(policy_path),
            "catalog_sha256": _sha256(catalog_path),
        },
        "summary": {
            "expected_candidates": expected,
            "resolved_candidates": len(records),
            "unresolved_candidates": expected - len(records),
            "errors": len(errors),
            "complete": len(records) == expected and not errors,
            "by_disposition": dict(sorted(counts.items())),
        },
        "records": records,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = reconcile(args.candidates, args.policy, args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 1 if args.require_complete and not report["summary"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
