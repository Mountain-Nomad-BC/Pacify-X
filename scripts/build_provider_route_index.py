"""Build the native direct-provider-route source index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.provider_gateway import build_provider_route_index  # noqa: E402
from runtime.guarded_registry_projection import publish_guarded_registry_projection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args()
    result = build_provider_route_index(ROOT)
    publish_guarded_registry_projection(ROOT, "registry/provider_route_scan.json", result,
        admission_event_id=args.admission_event_id)
    print(json.dumps({"valid": result["report"]["valid"], "files": len(result["records"]), "violations": result["report"]["violation_count"]}))
    return 0 if result["report"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
