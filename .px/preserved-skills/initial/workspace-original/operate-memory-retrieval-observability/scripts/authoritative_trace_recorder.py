#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--name", required=True)
    ap.add_argument("--parent")
    ap.add_argument("--status", default="OK")
    ap.add_argument("--attrs", default="{}")
    a = ap.parse_args()
    p = Path(a.trace)
    stable = json.dumps(
        [a.name, a.parent, a.status, json.loads(a.attrs)], sort_keys=True
    )
    identity = hashlib.sha256(stable.encode()).hexdigest()
    d = json.loads(p.read_text()) if p.exists() else {"trace_id": identity, "spans": []}
    span = {
        "span_id": identity[:16],
        "parent_span_id": a.parent,
        "name": a.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": a.status,
        "attributes": json.loads(a.attrs),
    }
    d["spans"].append(span)
    p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
    print(json.dumps(span, indent=2))


if __name__ == "__main__":
    main()
