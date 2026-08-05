"""Rebuild the compact, deterministic capability-query metadata index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.semantic_index import build_semantic_index  # noqa: E402 -- local source bootstrap


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_semantic_index(args.root)
    output = args.output or args.root / "registry" / "semantic_capability_index.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "valid": True,
                "record_count": payload["record_count"],
                "revision": payload["revision"],
                "output": str(output),
            }
        )
    )
