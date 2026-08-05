#!/usr/bin/env python3
"""Reconcile every record in a JSONL source inventory with durable owners.

The reconciler never mutates the source.  It accepts historical disposition
documents, a current product root, and narrowly scoped supersession rules.  A
record is complete only when one of those evidence channels accounts for it.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_inventory(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            missing = {"path", "sha256", "source_tree"} - set(record)
            if missing:
                raise ValueError(
                    f"{path}:{line_number} lacks required fields: {sorted(missing)}"
                )
            records.append(record)
    return records


def disposition_records(document: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    records: list[dict[str, Any]] = []
    for key in ("records", "files"):
        value = document.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def historical_hash_index(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for path in paths:
        for record in disposition_records(load_json(path)):
            source_hash = record.get("source_sha256") or record.get("sha256")
            if not isinstance(source_hash, str) or len(source_hash) != 64:
                continue
            source_path = record.get("source_path") or record.get("path") or ""
            disposition = (
                record.get("disposition") or record.get("status") or "recorded"
            )
            index.setdefault(source_hash, []).append(
                {
                    "document": path.as_posix(),
                    "source_path": str(source_path),
                    "disposition": str(disposition),
                }
            )
    return index


def match_rule(
    record: dict[str, Any], rules: list[dict[str, Any]]
) -> dict[str, Any] | None:
    source_path = str(record["path"]).replace("\\", "/")
    source_tree = str(record["source_tree"])
    for rule in rules:
        expected_tree = rule.get("source_tree")
        if expected_tree and expected_tree != source_tree:
            continue
        if fnmatch.fnmatchcase(source_path, str(rule["path_glob"])):
            return rule
    return None


def reconcile(
    inventory_path: Path,
    current_root: Path,
    disposition_paths: list[Path],
    rules_path: Path | None = None,
) -> dict[str, Any]:
    inventory = load_inventory(inventory_path)
    history = historical_hash_index(disposition_paths)
    rules_document = load_json(rules_path) if rules_path else {"rules": []}
    rules = rules_document.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("rules document must contain a list named 'rules'")

    current_root = current_root.resolve()
    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for source in inventory:
        source_path = str(source["path"]).replace("\\", "/")
        source_hash = str(source["sha256"])
        result: dict[str, Any] = {
            "source_tree": source["source_tree"],
            "source_path": source_path,
            "source_sha256": source_hash,
            "bytes": source.get("bytes"),
        }

        if source_hash in history:
            result["disposition"] = "historical_disposition"
            result["evidence"] = history[source_hash]
        else:
            current_path = current_root.joinpath(*Path(source_path).parts)
            if current_path.is_file():
                current_hash = sha256_file(current_path)
                result["owner_path"] = current_path.relative_to(current_root).as_posix()
                result["owner_sha256"] = current_hash
                result["disposition"] = (
                    "current_owner_exact"
                    if current_hash == source_hash
                    else "current_owner_superseded"
                )
            else:
                rule = match_rule(source, rules)
                if rule:
                    owner_path = current_root / str(rule["owner_path"])
                    if not owner_path.is_file():
                        raise ValueError(
                            f"rule {rule.get('id')} owner does not exist: {owner_path}"
                        )
                    result.update(
                        {
                            "disposition": str(rule["disposition"]),
                            "rule_id": str(rule["id"]),
                            "owner_path": owner_path.relative_to(
                                current_root
                            ).as_posix(),
                            "owner_sha256": sha256_file(owner_path),
                            "reason": str(rule["reason"]),
                        }
                    )
                else:
                    result["disposition"] = "unresolved"

        counts[result["disposition"]] += 1
        results.append(result)

    unresolved = counts["unresolved"]
    report = {
        "schema_version": "1.0",
        "inventory": {
            "path": inventory_path.resolve().as_posix(),
            "sha256": sha256_file(inventory_path),
            "record_count": len(inventory),
        },
        "current_root": current_root.as_posix(),
        "historical_disposition_documents": [
            {"path": path.resolve().as_posix(), "sha256": sha256_file(path)}
            for path in disposition_paths
        ],
        "rules": {
            "path": rules_path.resolve().as_posix() if rules_path else None,
            "sha256": sha256_file(rules_path) if rules_path else None,
        },
        "summary": {
            "total": len(results),
            "by_disposition": dict(sorted(counts.items())),
            "unresolved": unresolved,
            "complete": unresolved == 0,
        },
        "records": results,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--current-root", required=True, type=Path)
    parser.add_argument("--disposition", action="append", default=[], type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    report = reconcile(
        args.inventory,
        args.current_root,
        args.disposition,
        args.rules,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 1 if args.require_complete and report["summary"]["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
