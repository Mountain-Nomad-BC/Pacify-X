"""Cluster normalized or high-confidence near-duplicate text records."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_common import hamming_hex, read_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-hamming", type=int, default=3)
    args = parser.parse_args()
    if not 0 <= args.max_hamming <= 16:
        raise ValueError("--max-hamming must be between 0 and 16")
    normalized: dict[str, list[dict]] = defaultdict(list)
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in read_jsonl(args.inventory):
        structure = item.get("structure", {})
        digest = structure.get("normalized_sha256")
        simhash = structure.get("simhash64")
        if digest:
            normalized[digest].append(item)
        if simhash:
            buckets[(item.get("extension", ""), simhash[:4])].append(item)
    clusters: list[dict] = []
    assigned: set[str] = set()
    for digest, items in sorted(normalized.items()):
        members = sorted({item["id"] for item in items})
        if len(members) > 1:
            clusters.append(
                {
                    "cluster_id": f"normalized-{digest[:16]}",
                    "method": "normalized_sha256",
                    "confidence": 1.0,
                    "members": members,
                }
            )
            assigned.update(members)
    for _, items in sorted(buckets.items()):
        ordered = sorted(items, key=lambda item: item["id"])
        for index, anchor in enumerate(ordered):
            if anchor["id"] in assigned:
                continue
            members = [anchor["id"]]
            for candidate in ordered[index + 1 :]:
                if candidate["id"] in assigned:
                    continue
                if (
                    hamming_hex(
                        anchor["structure"]["simhash64"],
                        candidate["structure"]["simhash64"],
                    )
                    <= args.max_hamming
                ):
                    members.append(candidate["id"])
            if len(members) > 1:
                members.sort()
                clusters.append(
                    {
                        "cluster_id": f"simhash-{anchor['id']}",
                        "method": "simhash64",
                        "confidence": round(1 - args.max_hamming / 64, 4),
                        "members": members,
                    }
                )
                assigned.update(members)
    clusters.sort(key=lambda item: item["cluster_id"])
    output = {
        "schema_version": "1.0",
        "cluster_count": len(clusters),
        "clustered_records": len(
            {member for item in clusters for member in item["members"]}
        ),
        "clusters": clusters,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "cluster_count": output["cluster_count"],
                "clustered_records": output["clustered_records"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
