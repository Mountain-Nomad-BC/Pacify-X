"""Build explicit dispositions for nonportable locators in historical evidence."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.evidence_portability import discover_historical_references  # noqa: E402


def main() -> int:
    records = discover_historical_references(ROOT)
    output = {"schema_version": "1.0", "reference_count": len(records), "records": records}
    (ROOT / "registry/historical_external_references.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "reference_count": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
