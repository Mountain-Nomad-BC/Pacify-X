"""Build a deterministic specialty map from source candidates and the active registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--skill-catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    catalog = tomllib.loads(args.skill_catalog.read_text(encoding="utf-8"))
    active = {
        item["id"]
        for item in catalog["skills"]
        if item.get("status") in {"active", "admitted"}
    }
    categories: dict[str, list[dict]] = {}
    for candidate in queue["candidates"]:
        record = {
            "id": candidate["id"],
            "priority": candidate.get("priority", "P9"),
            "purpose": candidate.get("purpose", ""),
            "state": "active" if candidate["id"] in active else "mapped_deferred",
            "activation": "registry" if candidate["id"] in active else "admission_required",
        }
        categories.setdefault(candidate.get("category", "uncategorized"), []).append(record)
    represented = {item["id"] for items in categories.values() for item in items}
    framework_only = sorted(active - represented)
    output = {
        "schema_version": "1.0",
        "loading_rule": "Expose category and purpose metadata at startup; load a skill body only after selection and admission.",
        "candidate_count": len(represented),
        "active_candidate_count": len(active & represented),
        "deferred_candidate_count": len(represented - active),
        "framework_only_active": framework_only,
        "categories": [
            {
                "id": category,
                "specialties": sorted(items, key=lambda item: (item["priority"], item["id"])),
            }
            for category, items in sorted(categories.items())
        ],
    }
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("candidate_count", "active_candidate_count", "deferred_candidate_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
