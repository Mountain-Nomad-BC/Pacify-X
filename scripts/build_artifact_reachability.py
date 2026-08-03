"""Build the closed-world registry/workflow ownership and reachability inventory."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.artifact_reachability import build_artifact_reachability  # noqa: E402


def main() -> int:
    output = ROOT / "registry/artifact_reachability.json"
    value = build_artifact_reachability(ROOT)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "record_count": value["record_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
