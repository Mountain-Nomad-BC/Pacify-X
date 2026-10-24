"""Build the closed-world registry/workflow ownership and reachability inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.guarded_registry_projection import publish_guarded_registry_projection
from runtime.artifact_reachability import build_artifact_reachability  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args()
    value = build_artifact_reachability(ROOT)
    publish_guarded_registry_projection(ROOT, "registry/artifact_reachability.json", value,
        admission_event_id=args.admission_event_id)
    print(json.dumps({"valid": True, "record_count": value["record_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
