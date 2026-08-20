#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import math
import random


def softmax(xs):
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [x / s for x in e]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=500)
    a = ap.parse_args()
    r = random.Random(11)
    bad = []
    for i in range(a.cases):
        xs = [r.uniform(-20, 20) for _ in range(r.randint(1, 30))]
        c = r.uniform(-100, 100)
        p, q = softmax(xs), softmax([x + c for x in xs])
        err = max(abs(x - y) for x, y in zip(p, q))
        if err > 1e-12:
            bad.append({"case": i, "error": err})
    print(
        json.dumps(
            {
                "property": "softmax translation invariance",
                "cases": a.cases,
                "failures": bad,
                "status": "PASS" if not bad else "FAIL",
            },
            indent=2,
        )
    )
    raise SystemExit(bool(bad))


if __name__ == "__main__":
    main()
