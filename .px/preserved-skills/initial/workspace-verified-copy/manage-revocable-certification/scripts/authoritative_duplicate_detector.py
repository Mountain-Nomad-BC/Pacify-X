#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path


def toks(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def sim(a, b):
    x, y = toks(a), toks(b)
    return len(x & y) / max(1, len(x | y))


def load(root):
    rows = []
    for p in Path(root).rglob("skill.json"):
        try:
            d = json.loads(p.read_text())
            rows.append(
                {"id": d["id"], "summary": d.get("summary", ""), "path": str(p)}
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError):
            continue
    for p in Path(root).rglob("skill.yaml"):
        if any(r["path"] == str(p.with_suffix(".json")) for r in rows):
            continue
        txt = p.read_text(errors="ignore")
        mid = re.search(r'^id:\s*["\']?([^"\'\n]+)', txt, re.M)
        ms = re.search(r'^summary:\s*["\']?([^\n]+)', txt, re.M)
        if mid:
            rows.append(
                {
                    "id": mid.group(1).strip(),
                    "summary": ms.group(1).strip(" \"'") if ms else "",
                    "path": str(p),
                }
            )
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("left")
    ap.add_argument("right")
    ap.add_argument("--threshold", type=float, default=0.35)
    a = ap.parse_args()
    left_rows, right_rows = load(a.left), load(a.right)
    hits = []
    for x in left_rows:
        for y in right_rows:
            s = (
                1.0
                if x["id"] == y["id"]
                else sim(x["id"] + " " + x["summary"], y["id"] + " " + y["summary"])
            )
            if s >= a.threshold:
                hits.append(
                    {
                        "left": x,
                        "right": y,
                        "similarity": s,
                        "classification": "exact-id"
                        if x["id"] == y["id"]
                        else "semantic-overlap",
                    }
                )
    print(
        json.dumps(
            {
                "left_count": len(left_rows),
                "right_count": len(right_rows),
                "candidates": sorted(hits, key=lambda z: -z["similarity"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
