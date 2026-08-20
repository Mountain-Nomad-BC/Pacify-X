#!/usr/bin/env python3
"""Scan a bounded tree for credential-shaped literals without echoing values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from engineering_bootstrap.secret_scanning import scan_secret_shapes  # type: ignore[import-not-found]  # noqa: E402
except ModuleNotFoundError:
    from runtime.secret_scanning import scan_secret_shapes  # noqa: E402


scan = scan_secret_shapes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review-registry", type=Path)
    args = parser.parse_args()
    result = scan(args.root, review_registry=args.review_registry)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
