"""Build the exact executable-effect ownership registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.guarded_registry_projection import publish_guarded_registry_projection
from runtime.effect_surface import discover_effect_surfaces  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args()
    records = discover_effect_surfaces(ROOT)
    output = {"schema_version": "1.0", "record_count": len(records), "records": records}
    publish_guarded_registry_projection(ROOT, "registry/effect_surface_ownership.json", output,
        admission_event_id=args.admission_event_id)
    print(json.dumps({"valid": True, "record_count": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
