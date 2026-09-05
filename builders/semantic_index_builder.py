"""Canonical builder entry point for the semantic capability index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.semantic_index import build_semantic_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output", type=Path, default=Path("registry/semantic_capability_index.json")
    )
    args = parser.parse_args()
    payload = build_semantic_index(args.root)
    target = args.root.resolve() / args.output
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
