#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import random


def kv(layers, batches, tokens, heads, dimensions, partitions):
    return 2 * layers * batches * tokens * heads * dimensions * partitions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=17)
    a = ap.parse_args()
    r = random.Random(a.seed)
    failures = []
    for i in range(a.cases):
        layers, batches, tokens, heads, dimensions, partitions = [
            r.randint(1, maximum) for maximum in [200, 16, 100000, 256, 512, 4]
        ]
        base = kv(layers, batches, tokens, heads, dimensions, partitions)
        if kv(layers, batches, tokens + 1, heads, dimensions, partitions) <= base:
            failures.append({"case": i, "property": "monotonic_tokens"})
        if kv(layers, batches, tokens, heads, dimensions, partitions) != kv(
            layers, batches, tokens, heads, dimensions, partitions
        ):
            failures.append({"case": i, "property": "deterministic"})
    print(
        json.dumps(
            {
                "cases": a.cases,
                "failures": failures,
                "status": "PASS" if not failures else "FAIL",
            },
            indent=2,
        )
    )
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
