from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.evidence_index import build_index, publish_index


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--artifact", type=Path, action="append", default=[]); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(); root = args.root.resolve()
    if args.apply: _, _, value = publish_index(root, artifacts=args.artifact)
    else: value = build_index(root, artifacts=args.artifact)
    print(json.dumps(value, indent=2)); return 0 if value["valid"] else 2


if __name__ == "__main__": raise SystemExit(main())
