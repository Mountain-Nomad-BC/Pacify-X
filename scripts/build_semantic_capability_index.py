"""Rebuild the compact, deterministic capability-query metadata index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.semantic_index import build_semantic_index  # noqa: E402 -- local source bootstrap
from runtime.guarded_registry_projection import publish_guarded_registry_projection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    output = args.output or Path("registry/semantic_capability_index.json")
    output = output if output.is_absolute() else root / output
    relative = output.relative_to(root).as_posix()
    payload = build_semantic_index(root)
    publish_guarded_registry_projection(root, relative, payload,
        admission_event_id=args.admission_event_id)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
