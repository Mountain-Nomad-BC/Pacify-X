"""Build the native direct-provider-route source index."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.provider_gateway import build_provider_route_index  # noqa: E402


def main() -> int:
    result = build_provider_route_index(ROOT)
    target = ROOT / "registry/provider_route_scan.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"valid": result["report"]["valid"], "files": len(result["records"]), "violations": result["report"]["violation_count"]}))
    return 0 if result["report"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
