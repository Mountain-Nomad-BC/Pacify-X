"""Group exact duplicates without deleting source records."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_common import read_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    total = 0
    for item in read_jsonl(args.inventory):
        total += 1
        groups[(item["sha256"], int(item["bytes"]))].append(item)
    duplicates = []
    for (digest, size), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        members = sorted({item["id"] for item in items})
        duplicates.append({"group_id": f"exact-{digest[:16]}", "sha256": digest, "bytes": size, "count": len(members), "members": members})
    output = {"schema_version": "1.0", "inventory_records": total, "group_count": len(duplicates), "duplicate_records": sum(item["count"] for item in duplicates), "groups": duplicates}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("inventory_records", "group_count", "duplicate_records")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
