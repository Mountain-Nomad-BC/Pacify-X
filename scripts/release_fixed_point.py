from __future__ import annotations

import argparse
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_certification import copy_clean_product
from runtime.release_preflight import fixed_point


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    policy = json.loads(
        (root / "policies/release-preflight.json").read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="px-release-fixed-point-") as directory:
        clean = Path(directory) / "product"
        copy_clean_product(root, clean)
        result = fixed_point(clean, policy["rebuild_authorities"])
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
