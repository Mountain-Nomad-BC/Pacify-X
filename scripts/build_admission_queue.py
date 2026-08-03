"""Build a candidate-only admission queue from existing skill maps and manifests."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*([^\n]+)$", text, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maps", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidates: dict[str, dict] = {}
    with (args.maps / "LLM_hybrid_rag" / "SKILL_INDEX.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candidates[row["skill_id"]] = {
                "id": row["skill_id"], "category": row["category"], "priority": row["priority"],
                "purpose": row["purpose"], "source_ids": row["source_ids"].split(";"),
                "status": "candidate", "disposition": "defer", "required_before_promotion": [
                    "manifest_match", "io_contract", "effect_review", "dependency_review", "validation_evidence", "approval"
                ],
            }
    for manifest in (args.maps / "LLM_hybrid_rag").glob("manifest*.yaml"):
        text = manifest.read_text(encoding="utf-8")
        skill_id = scalar(text, "id")
        if skill_id:
            record = candidates.setdefault(skill_id, {"id": skill_id, "status": "candidate", "disposition": "defer"})
            record.update({key: value for key, value in {"version": scalar(text, "version"), "owner": scalar(text, "owner"), "category": scalar(text, "category"), "priority": scalar(text, "priority")}.items() if value})
            record["manifest"] = str(manifest.relative_to(args.maps)).replace("\\", "/")
    output = {"schema_version": "1.0", "candidate_count": len(candidates), "candidates": sorted(candidates.values(), key=lambda item: (item.get("priority", "P9"), item["id"]))}
    args.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
