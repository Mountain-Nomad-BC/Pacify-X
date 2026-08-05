#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def load(p):
    if not p:
        return {}
    if p.endswith(".json"):
        return json.loads(Path(p).read_text())
    d = {}
    for line in Path(p).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--default")
    ap.add_argument("--config", action="append", default=[])
    ap.add_argument("--cli")
    a = ap.parse_args()
    chain = []
    val = a.default
    chain.append({"source": "default", "value": val})
    for f in a.config:
        d = load(f)
        if a.key in d:
            val = d[a.key]
            chain.append({"source": f, "value": val})
    if a.key in os.environ:
        val = os.environ[a.key]
        chain.append({"source": "environment", "value": val})
    if a.cli is not None:
        val = a.cli
        chain.append({"source": "cli", "value": val})
    print(
        json.dumps({"key": a.key, "resolved": val, "precedence_chain": chain}, indent=2)
    )


if __name__ == "__main__":
    main()
