from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_preflight import evidence_portability
from runtime.input_files import directory_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        root = directory_root(args.root)
        result = evidence_portability(root)
    except (OSError, ValueError, TypeError):
        result = {"valid": False, "failures": [{"code": "RP-INP-001", "message": "Invalid preflight policy or original project root."}]}
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
