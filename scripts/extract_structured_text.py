"""Project structural metadata for every text format in an inventory.

The upstream inventory owns format detection and structure extraction for code,
Markdown, JSON, YAML, TOML, CSV, and plain text. This stage filters all records
classified as text; it does not restrict extraction to Markdown.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_common import read_jsonl, write_jsonl  # noqa: E402


def extract(inventory: Path, output: Path) -> tuple[int, str]:
    records = []
    for item in read_jsonl(inventory):
        if item.get("content_kind") != "text":
            continue
        records.append({
            key: item[key]
            for key in ("id", "source_tree", "path", "sha256", "probable_domain", "domain_confidence")
        } | {"format": Path(str(item["path"])).suffix.casefold() or "plain-text", "structure": item.get("structure", {})})
    records.sort(key=lambda item: (item["source_tree"], item["path"], item["id"]))
    return write_jsonl(output, records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count, digest = extract(args.inventory, args.output)
    print({"record_count": count, "sha256": digest})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
