"""One-shot governance repair: admit the four semantic contracts into ownership.

This merges the staged fragment in .agentic_engineering_os_px/registers into
registry/contract_ownership.json without reordering, renaming or rewriting any
pre-existing record, and recomputes contract_count from the merged corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "contract_ownership.json"
FRAGMENT = (
    ROOT / ".agentic_engineering_os_px" / "registers" / "_semantic-ownership-fragment.json"
)


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    fragment = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    records = registry["records"]
    existing = {record["path"] for record in records}

    added = []
    for record in fragment["records"]:
        if record["path"] in existing:
            print(f"already present, left untouched: {record['path']}")
            continue
        records.append(record)
        added.append(record["path"])

    records.sort(key=lambda item: item["path"])
    registry["records"] = records
    registry["contract_count"] = len(records)

    REGISTRY.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"added: {added}")
    print(f"contract_count: {registry['contract_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())