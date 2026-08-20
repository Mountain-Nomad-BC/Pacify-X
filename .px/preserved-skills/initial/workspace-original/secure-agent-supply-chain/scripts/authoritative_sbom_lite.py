#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    comps = []
    for f in [
        "requirements.txt",
        "pyproject.toml",
        "package-lock.json",
        "package.json",
        "Cargo.lock",
        "go.mod",
    ]:
        p = root / f
        if p.exists():
            comps.append(
                {
                    "manifest": f,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
            )
    bom = {
        "bomFormat": "CycloneDX-compatible-lite",
        "specVersion": "1.6",
        "metadata": {"component": {"name": root.name, "type": "application"}},
        "manifests": comps,
        "limitations": [
            "Use Syft, CycloneDX tooling, or SPDX tooling for a standards-complete SBOM."
        ],
    }
    Path(a.out).write_text(json.dumps(bom, indent=2) + "\n")
    print(json.dumps(bom, indent=2))


if __name__ == "__main__":
    main()
