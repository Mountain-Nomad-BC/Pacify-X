#!/usr/bin/env python3
"""Validate durable owner/test coverage for every source planning card."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


CARD = re.compile(r"(?m)^##\s+(PC-\d+)\b")
ALLOWED = {"operational", "operational_bounded", "external_evidence_only"}


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(
    coverage_path: Path, product_root: Path, source_path: Path | None = None
) -> dict[str, Any]:
    document = json.loads(coverage_path.read_text(encoding="utf-8-sig"))
    records = document.get("records", [])
    ids: list[str] = []
    errors: list[str] = []
    for record in records:
        card_id = str(record.get("id", ""))
        ids.append(card_id)
        if not re.fullmatch(r"PC-\d+", card_id):
            errors.append(f"invalid card id: {card_id}")
        if record.get("status") not in ALLOWED:
            errors.append(f"{card_id}: invalid status")
        for field in ("owners", "tests"):
            paths = record.get(field, [])
            if not paths:
                errors.append(f"{card_id}: missing {field}")
            for relative in paths:
                if not (product_root / str(relative)).is_file():
                    errors.append(f"{card_id}: missing {field[:-1]} {relative}")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate card ids: {duplicates}")
    source_ids: list[str] | None = None
    source_hash: str | None = None
    if source_path:
        source_ids = CARD.findall(
            source_path.read_text(encoding="utf-8-sig", errors="replace")
        )
        source_hash = hash_file(source_path)
        missing = sorted(set(source_ids) - set(ids))
        extra = sorted(set(ids) - set(source_ids))
        if missing:
            errors.append(f"unmapped source cards: {missing}")
        if extra:
            errors.append(f"coverage cards absent from source: {extra}")
    return {
        "schema_version": "1.0",
        "coverage_sha256": hash_file(coverage_path),
        "source_sha256": source_hash,
        "source_card_count": len(source_ids) if source_ids is not None else None,
        "coverage_card_count": len(records),
        "errors": errors,
        "complete": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--product-root", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.coverage, args.product_root.resolve(), args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
