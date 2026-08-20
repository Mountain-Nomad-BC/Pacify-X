#!/usr/bin/env python3
"""Reconcile every SKILL.md identity in inventory metadata without loading all bodies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def reconcile(
    inventory_path: Path,
    structured_path: Path,
    catalog_path: Path,
    specialty_path: Path,
    aliases_path: Path,
) -> dict[str, Any]:
    skill_records: dict[str, dict[str, Any]] = {}
    for record in iter_jsonl(inventory_path):
        path = str(record["path"]).replace("\\", "/")
        if path.lower() == "skill.md" or path.lower().endswith("/skill.md"):
            skill_records[str(record["id"])] = record

    frontmatter: dict[str, dict[str, Any]] = {}
    for record in iter_jsonl(structured_path):
        record_id = str(record["id"])
        if record_id in skill_records:
            value = record.get("structure", {}).get("frontmatter", {})
            frontmatter[record_id] = value if isinstance(value, dict) else {}

    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8-sig"))
    current = {str(item["id"]) for item in catalog.get("skills", [])}
    specialty_doc = json.loads(specialty_path.read_text(encoding="utf-8-sig"))
    specialties = {str(item["id"]): item for item in specialty_doc.get("records", [])}
    alias_doc = json.loads(aliases_path.read_text(encoding="utf-8-sig"))
    aliases = {str(item["source_id"]): item for item in alias_doc.get("aliases", [])}
    vendor_prefixes = tuple(str(x) for x in alias_doc.get("vendor_source_prefixes", []))

    known_targets = current
    for item in list(specialties.values()) + list(aliases.values()):
        targets = item.get("active_semantic_mappings") or item.get("targets") or []
        missing = sorted(set(map(str, targets)) - known_targets)
        if missing:
            raise ValueError(
                f"unknown target skill(s) for {item.get('id') or item.get('source_id')}: {missing}"
            )

    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    identities: dict[str, set[str]] = defaultdict(set)
    for record_id, source in skill_records.items():
        path = str(source["path"]).replace("\\", "/")
        value = frontmatter.get(record_id, {}).get("name")
        identity = canonical(
            value if isinstance(value, str) and value.strip() else path.split("/")[-2]
        )
        source_hash = str(source["sha256"])
        identities[identity].add(source_hash)
        result = {
            "id": record_id,
            "source_tree": source["source_tree"],
            "source_path": path,
            "source_sha256": source_hash,
            "identity": identity,
        }
        if identity in current:
            result.update(disposition="current_catalog", targets=[identity])
        elif identity in specialties:
            item = specialties[identity]
            result.update(
                disposition="specialty_reconciled",
                targets=item.get("active_semantic_mappings", []),
                delivery_state=item.get("delivery_state"),
            )
        elif identity in aliases:
            item = aliases[identity]
            result.update(
                disposition=f"alias_{item['disposition']}", targets=item["targets"]
            )
        elif vendor_prefixes and str(source["source_tree"]).startswith(vendor_prefixes):
            result.update(
                disposition="vendor_reference_only",
                targets=["audit-source-capabilities", "quarantine-external-tools"],
            )
        else:
            result.update(disposition="unresolved", targets=[])
        counts[result["disposition"]] += 1
        results.append(result)

    unresolved = counts["unresolved"]
    return {
        "schema_version": "1.0",
        "inputs": {
            "inventory_sha256": hash_file(inventory_path),
            "structured_text_sha256": hash_file(structured_path),
            "catalog_sha256": hash_file(catalog_path),
            "specialty_admission_sha256": hash_file(specialty_path),
            "aliases_sha256": hash_file(aliases_path),
        },
        "summary": {
            "skill_files": len(results),
            "unique_identities": len(identities),
            "unique_content_hashes": len({r["source_sha256"] for r in results}),
            "identity_variant_counts": dict(
                sorted((k, len(v)) for k, v in identities.items())
            ),
            "by_disposition": dict(sorted(counts.items())),
            "unresolved": unresolved,
            "complete": unresolved == 0 and len(frontmatter) == len(skill_records),
            "structured_records_matched": len(frontmatter),
        },
        "records": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--structured-text", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--specialty-admission", required=True, type=Path)
    parser.add_argument("--aliases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = reconcile(
        args.inventory,
        args.structured_text,
        args.catalog,
        args.specialty_admission,
        args.aliases,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 1 if args.require_complete and not report["summary"]["complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
