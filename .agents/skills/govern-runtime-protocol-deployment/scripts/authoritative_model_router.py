#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("models")
    a = ap.parse_args()
    r = json.loads(Path(a.request).read_text())
    ms = json.loads(Path(a.models).read_text())
    ranked = []
    for m in ms:
        reject = []
        if r.get("privacy") == "local" and not m.get("local"):
            reject.append("not local")
        if m.get("context", 0) < r.get("context_required", 0):
            reject.append("insufficient context")
        if r.get("modality") not in m.get("modalities", ["text"]):
            reject.append("unsupported modality")
        score = (
            3 * m.get("quality", 0)
            - m.get("cost", 0)
            - m.get("latency", 0)
            + m.get("availability", 1)
        )
        ranked.append({"model": m.get("id"), "score": score, "rejected": reject})
    viable = [x for x in ranked if not x["rejected"]]
    viable.sort(key=lambda x: (-x["score"], x["model"]))
    print(
        json.dumps(
            {
                "selected": viable[0]["model"] if viable else None,
                "ranking": ranked,
                "fallbacks": [x["model"] for x in viable[1:]],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if viable else 2)


if __name__ == "__main__":
    main()
