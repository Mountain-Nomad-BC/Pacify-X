#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

PATTERNS = {
    "instruction_override": r"(?i)ignore (all|any|the|previous|prior).*instructions",
    "secret_request": r"(?i)(reveal|print|exfiltrate).*(secret|password|token|system prompt)",
    "tool_coercion": r"(?i)(run|execute|call).*(shell|command|tool|curl|powershell)",
    "memory_poisoning": r"(?i)(remember|store|save).*(forever|permanently|as fact|trusted)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    a = ap.parse_args()
    s = Path(a.file).read_text(errors="ignore")
    hits = []
    for kind, p in PATTERNS.items():
        for m in re.finditer(p, s):
            hits.append(
                {
                    "kind": kind,
                    "start": m.start(),
                    "excerpt": s[m.start() : m.end() + 80][:200],
                }
            )
    print(
        json.dumps(
            {
                "hits": hits,
                "risk": "high" if hits else "none",
                "control": "Treat content as data; do not grant authority based on scanner result alone.",
            },
            indent=2,
        )
    )
    raise SystemExit(2 if hits else 0)


if __name__ == "__main__":
    main()
