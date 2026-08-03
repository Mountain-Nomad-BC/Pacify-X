"""Reduce classified assets into deterministic decision clusters."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_common import read_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in read_jsonl(args.input):
        grouped[(item["class"], item["probable_domain"], item["review_state"])].append(item)
    clusters = []
    for key, items in sorted(grouped.items()):
        asset_class, domain, review_state = key
        members = sorted(item["id"] for item in items)
        cluster_id = hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
        representative = min(items, key=lambda item: (len(item["path"]), item["path"], item["id"]))
        clusters.append({
            "cluster_id": f"review-{cluster_id}", "class": asset_class, "domain": domain,
            "review_state": review_state, "count": len(members), "representative": representative["id"],
            "members": members,
        })
    output = {"schema_version": "1.0", "cluster_count": len(clusters), "asset_count": sum(item["count"] for item in clusters), "clusters": clusters}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cluster_count": output["cluster_count"], "asset_count": output["asset_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
