#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("current")
    ap.add_argument("--threshold", type=float, default=0.1)
    a = ap.parse_args()
    b = json.loads(Path(a.baseline).read_text())
    c = json.loads(Path(a.current).read_text())
    changes = {}
    for k, v in b.items():
        if isinstance(v, (int, float)) and isinstance(c.get(k), (int, float)):
            changes[k] = {
                "baseline": v,
                "current": c[k],
                "relative_change": (c[k] - v) / abs(v) if v else None,
                "alert": abs(c[k] - v) > a.threshold * max(abs(v), 1e-9),
            }
    print(
        json.dumps(
            {"changes": changes, "alert": any(x["alert"] for x in changes.values())},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
