from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_preflight import feedback_audit, load_preflight_input_policy
from runtime.input_files import directory_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        root = directory_root(args.root)
        policy = load_preflight_input_policy(root)
        result = feedback_audit(root, policy["post_certification_writes"])
    except (OSError, ValueError, TypeError):
        result = {"valid": False, "failures": [{"code": "RP-INP-001", "message": "Invalid preflight policy or original project root."}]}
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
