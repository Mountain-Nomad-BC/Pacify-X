"""Build explicit dispositions for nonportable locators in historical evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.guarded_registry_projection import publish_guarded_registry_projection
from runtime.evidence_portability import (  # noqa: E402
    PRODUCT_STRUCTURED_ROOTS,
    discover_historical_references,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args()
    records = discover_historical_references(
        ROOT, structured_roots=PRODUCT_STRUCTURED_ROOTS
    )
    output = {
        "schema_version": "1.0",
        "reference_count": len(records),
        "records": records,
    }
    publish_guarded_registry_projection(ROOT, "registry/historical_external_references.json", output,
        admission_event_id=args.admission_event_id)
    print(json.dumps({"valid": True, "reference_count": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
