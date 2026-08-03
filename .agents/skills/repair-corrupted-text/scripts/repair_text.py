#!/usr/bin/env python3
"""Apply reviewed exact string mappings to text or JSON without in-place writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _repair(value: object, mappings: list[tuple[str, str]], counts: dict[str, int]) -> object:
    if isinstance(value, str):
        for source, replacement in mappings:
            count = value.count(source)
            if count:
                value = value.replace(source, replacement)
                counts[source] = counts.get(source, 0) + count
        return value
    if isinstance(value, list):
        return [_repair(item, mappings, counts) for item in value]
    if isinstance(value, dict):
        return {key: _repair(item, mappings, counts) for key, item in value.items()}
    return value


def repair(input_path: Path, mapping_path: Path) -> tuple[bytes, dict]:
    raw = input_path.read_bytes()
    config = json.loads(mapping_path.read_text(encoding="utf-8"))
    replacements = config.get("replacements", {})
    if not isinstance(replacements, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in replacements.items()):
        raise ValueError("mapping replacements must be a string-to-string object")
    mappings = sorted(replacements.items(), key=lambda pair: (-len(pair[0]), pair[0]))
    counts: dict[str, int] = {}
    if input_path.suffix.lower() == ".json":
        value = json.loads(raw.decode("utf-8"))
        output = (json.dumps(_repair(value, mappings, counts), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    else:
        output = str(_repair(raw.decode("utf-8"), mappings, counts)).encode("utf-8")
    receipt = {
        "schema_version": "1.0",
        "mapping_version": str(config.get("version", "unversioned")),
        "input_sha256": _hash(raw),
        "output_sha256": _hash(output),
        "replacement_counts": counts,
        "changed": raw != output,
    }
    return output, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    output, receipt = repair(args.input.resolve(), args.mapping.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
