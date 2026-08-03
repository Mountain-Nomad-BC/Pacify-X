"""Build the exact executable-effect ownership registry."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.effect_surface import discover_effect_surfaces  # noqa: E402


def main() -> int:
    records = discover_effect_surfaces(ROOT)
    output = {"schema_version": "1.0", "record_count": len(records), "records": records}
    path = ROOT / "registry/effect_surface_ownership.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "record_count": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
