#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def h(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", action="append", default=[])
    ap.add_argument("--claim-ledger")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    b = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [{"path": x, "sha256": h(x)} for x in sorted(a.artifact)],
        "claim_ledger": a.claim_ledger,
        "limitations": [],
    }
    Path(a.out).write_text(json.dumps(b, indent=2, sort_keys=True) + "\n")
    print(json.dumps(b, indent=2))


if __name__ == "__main__":
    main()
