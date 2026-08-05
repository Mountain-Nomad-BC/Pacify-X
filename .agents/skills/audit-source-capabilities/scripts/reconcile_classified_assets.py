#!/usr/bin/env python3
"""Assign a durable disposition to every classified source-asset record and error."""

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


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def classify_error(record: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    message = str(record.get("error", ""))
    path = str(record.get("path", "")).lower()
    for rule in policy.get("inventory_error_classes", []):
        contains = rule.get("contains")
        suffixes = tuple(str(value).lower() for value in rule.get("path_suffixes", []))
        if contains and str(contains) not in message:
            continue
        if suffixes and not path.endswith(suffixes):
            continue
        return {"rule_id": str(rule["id"]), "disposition": str(rule["disposition"])}
    return {
        "rule_id": "default",
        "disposition": str(policy["default_inventory_error_disposition"]),
    }


def reconcile(
    inventory_path: Path,
    classified_path: Path,
    policy_path: Path,
    skill_report_path: Path,
    direct_audit_paths: list[Path],
    error_paths: list[Path],
) -> dict[str, Any]:
    inventory = {str(record["id"]): record for record in iter_jsonl(inventory_path)}
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    terminal = policy.get("terminal_classes", {})
    capability = policy.get("capability_classes", {})
    skill_report = json.loads(skill_report_path.read_text(encoding="utf-8-sig"))
    skills = {str(record["id"]): record for record in skill_report.get("records", [])}

    direct: dict[str, list[dict[str, Any]]] = {}
    for path in direct_audit_paths:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        for record in document.get("records", []):
            digest = record.get("sha256")
            if isinstance(digest, str):
                direct.setdefault(digest, []).append(
                    {
                        "report_sha256": hash_file(path),
                        "disposition": record.get("disposition"),
                        "mechanisms": record.get("mechanisms", []),
                    }
                )

    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    seen_ids: set[str] = set()
    for source in iter_jsonl(classified_path):
        record_id = str(source["id"])
        if record_id in seen_ids:
            raise ValueError(f"duplicate classified id: {record_id}")
        seen_ids.add(record_id)
        raw = inventory.get(record_id)
        if raw is None:
            raise ValueError(f"classified id missing from inventory: {record_id}")
        class_name = str(source["class"])
        result: dict[str, Any] = {
            "id": record_id,
            "source_tree": source["source_tree"],
            "source_path": source["path"],
            "source_sha256": source["sha256"],
            "content_kind": raw.get("content_kind"),
            "class": class_name,
            "domain": source.get("probable_domain"),
        }
        if record_id in skills:
            skill = skills[record_id]
            result.update(
                disposition=f"skill_body_{skill['disposition']}",
                targets=skill.get("targets", []),
                skill_identity=skill.get("identity"),
            )
        elif class_name in terminal:
            result.update(terminal[class_name])
        elif class_name in capability:
            result.update(capability[class_name])
        else:
            result.update(disposition="unresolved_class", targets=[])
        if source["sha256"] in direct:
            result["direct_scan_evidence"] = direct[source["sha256"]]
        counts[str(result["disposition"])] += 1
        results.append(result)

    missing_classifications = sorted(set(inventory) - seen_ids)
    error_results: list[dict[str, Any]] = []
    error_counts: Counter[str] = Counter()
    for path in error_paths:
        for source in iter_jsonl(path):
            decision = classify_error(source, policy)
            error_counts[decision["disposition"]] += 1
            error_results.append(
                {
                    "source_tree": source.get("source_tree"),
                    "source_path": source.get("path"),
                    **decision,
                }
            )

    unresolved = counts["unresolved_class"] + len(missing_classifications)
    unresolved_errors = error_counts[str(policy["default_inventory_error_disposition"])]
    return {
        "schema_version": "1.0",
        "inputs": {
            "inventory_sha256": hash_file(inventory_path),
            "classified_sha256": hash_file(classified_path),
            "policy_sha256": hash_file(policy_path),
            "skill_report_sha256": hash_file(skill_report_path),
            "direct_audit_reports": [hash_file(path) for path in direct_audit_paths],
            "error_logs": [
                {"sha256": hash_file(path), "records": sum(1 for _ in iter_jsonl(path))}
                for path in error_paths
            ],
        },
        "summary": {
            "inventory_records": len(inventory),
            "classified_records": len(results),
            "by_disposition": dict(sorted(counts.items())),
            "direct_scan_matches": sum(
                1 for item in results if "direct_scan_evidence" in item
            ),
            "missing_classifications": len(missing_classifications),
            "inventory_errors": len(error_results),
            "inventory_errors_by_disposition": dict(sorted(error_counts.items())),
            "unresolved": unresolved,
            "unresolved_inventory_errors": unresolved_errors,
            "complete": unresolved == 0
            and unresolved_errors == 0
            and len(results) == len(inventory),
        },
        "missing_classification_ids": missing_classifications,
        "records": results,
        "inventory_error_records": error_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--classified", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--skill-report", required=True, type=Path)
    parser.add_argument("--direct-audit", action="append", default=[], type=Path)
    parser.add_argument("--error-log", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = reconcile(
        args.inventory,
        args.classified,
        args.policy,
        args.skill_report,
        args.direct_audit,
        args.error_log,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 1 if args.require_complete and not report["summary"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
