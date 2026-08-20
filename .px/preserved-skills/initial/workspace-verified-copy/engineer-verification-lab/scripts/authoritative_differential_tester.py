#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import math
import random


def softmax_a(xs):
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    s = sum(ex)
    return [x / s for x in ex]


def softmax_b(xs):
    m = max(xs)
    den = math.fsum(math.exp(x - m) for x in xs)
    return [math.exp(x - m) / den for x in xs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=1000)
    a = ap.parse_args()
    r = random.Random(4)
    bad = []
    for i in range(a.cases):
        xs = [r.uniform(-100, 100) for _ in range(r.randint(1, 100))]
        x, y = softmax_a(xs), softmax_b(xs)
        err = max(abs(a - b) for a, b in zip(x, y))
        if err > 1e-12:
            bad.append({"case": i, "error": err})
    print(
        json.dumps(
            {
                "cases": a.cases,
                "mismatches": bad,
                "status": "PASS" if not bad else "FAIL",
            },
            indent=2,
        )
    )
    raise SystemExit(bool(bad))


if __name__ == "__main__":
    main()
