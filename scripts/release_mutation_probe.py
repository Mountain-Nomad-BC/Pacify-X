from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.engine_identity import build_engine_identity
from runtime.release_artifacts import classify_tree
from runtime.release_preflight import mutation_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--probe",
        choices=(
            "generated-builders",
            "test-smoke",
            "installed-smoke",
            "dashboard-read",
            "completion-read",
            "release-metadata",
            "all-safe-probes",
        ),
        default="all-safe-probes",
    )
    args = parser.parse_args()
    result = mutation_probe(
        args.root.resolve(),
        (lambda root: classify_tree(root), lambda root: build_engine_identity(root)),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
