from __future__ import annotations

import argparse
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_certification import copy_clean_product
from runtime.release_preflight import audit_clean_boundary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix="px-release-boundary-") as directory:
        clean = Path(directory) / "product"
        copy_clean_product(root, clean)
        result = audit_clean_boundary(root, clean)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
