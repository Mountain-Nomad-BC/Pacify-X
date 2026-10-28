"""Publish or validate the canonical mutating-producer registry (Phase 1C).

Usage:
    python scripts/build_mutating_producer_registry.py --admission-event-id <id>  # publish
    python scripts/build_mutating_producer_registry.py --validate  # validate only

Publishing fails closed while any discovered mutating producer is unclassified.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.mutating_producer_registry import (  # noqa: E402
    MutatingProducerError,
    publish_registry,
    validate_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--admission-event-id", help="current explicit native write admission; required for publication")
    args = parser.parse_args()
    if not args.validate and not args.admission_event_id:
        parser.error("publication requires --admission-event-id")
    root = args.root.resolve()
    if args.validate:
        result = validate_registry(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    try:
        result = publish_registry(root, admission_event_id=args.admission_event_id)
    except MutatingProducerError as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())