#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import random
import string

CASES = [
    "",
    "{",
    "[]",
    "null",
    '{"a":1}',
    '{"a":[' + ",".join("0" for _ in range(1000)) + "]}",
    '"\\ud800"',
    '{"__proto__":{"x":1}}',
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--seed", type=int, default=9)
    a = ap.parse_args()
    r = random.Random(a.seed)
    failures = []
    for i in range(a.cases):
        s = (
            r.choice(CASES)
            if i < len(CASES)
            else "".join(r.choice(string.printable) for _ in range(r.randint(0, 200)))
        )
        try:
            json.loads(s)
        except (ValueError, UnicodeError, RecursionError):
            continue
        except Exception as e:
            failures.append(
                {"case": i, "type": type(e).__name__, "input": repr(s[:80])}
            )
    print(
        json.dumps(
            {
                "executed": a.cases,
                "unexpected_failures": failures,
                "status": "PASS" if not failures else "FAIL",
            },
            indent=2,
        )
    )
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
