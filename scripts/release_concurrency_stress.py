from __future__ import annotations

import argparse
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_preflight import concurrency_stress


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="px-release-concurrency-") as directory:
        result = concurrency_stress(
            Path(directory), iterations=args.iterations, seed=args.seed
        )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
