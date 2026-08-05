"""Refresh map-level hashes after a bounded mechanical sanitization pass."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def rehash(parts_root: Path) -> dict[str, object]:
    updated: list[dict[str, object]] = []
    for inventory in sorted(
        parts_root.rglob("inventory.jsonl"), key=lambda path: path.as_posix()
    ):
        summary = inventory.with_name("file_inventory_summary.json")
        if not summary.is_file():
            continue
        digest = hashlib.sha256(inventory.read_bytes()).hexdigest()
        payload = json.loads(summary.read_text(encoding="utf-8"))
        payload["inventory_sha256"] = digest
        summary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        markdown = inventory.with_name("file_inventory_summary.md")
        if markdown.is_file():
            lines = markdown.read_text(encoding="utf-8").splitlines()
            lines = [
                f"- Inventory SHA-256: `{digest}`"
                if line.startswith("- Inventory SHA-256:")
                else line
                for line in lines
            ]
            markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
        updated.append({"partition": inventory.parent.name, "inventory_sha256": digest})
    return {
        "schema_version": "1.0",
        "updated_count": len(updated),
        "partitions": updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = rehash(args.parts_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"updated_count": result["updated_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
