"""Build every canonical graph and its deterministic provenance manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.graph_registry import write_graph_artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    print(json.dumps(write_graph_artifacts(root, args.out), indent=2))
