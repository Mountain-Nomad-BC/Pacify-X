#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    inv = json.loads(Path(a.inventory).read_text())
    required = [
        "models",
        "tokenizers",
        "adapters",
        "datasets",
        "prompts",
        "policies",
        "tools",
        "runtimes",
        "evaluations",
        "external_services",
    ]
    stable = {
        "bomFormat": "AI-BOM",
        "specVersion": "1.0",
        "components": {k: inv.get(k, []) for k in required},
        "missing_categories": [k for k in required if k not in inv],
    }
    bom = {
        **stable,
        "created": datetime.now(timezone.utc).isoformat(),
        "canonical_sha256": hashlib.sha256(
            json.dumps(stable, sort_keys=True).encode()
        ).hexdigest(),
    }
    Path(a.out).write_text(json.dumps(bom, indent=2, sort_keys=True) + "\n")
    print(json.dumps(bom, indent=2))


if __name__ == "__main__":
    main()
