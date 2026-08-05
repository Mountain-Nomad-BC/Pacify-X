#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff")
    ap.add_argument("--allowed", action="append", default=[])
    ap.add_argument("--max-lines", type=int, default=500)
    a = ap.parse_args()
    diff = (
        Path(a.diff).read_text()
        if a.diff
        else subprocess.check_output(
            ["git", "diff", "--no-ext-diff"], text=True, timeout=30
        )
    )
    files = []
    changed = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:])
        elif (line.startswith("+") or line.startswith("-")) and not line.startswith(
            ("+++", "---")
        ):
            changed += 1
    denied = [
        f for f in files if a.allowed and not any(Path(f).match(p) for p in a.allowed)
    ]
    ok = not denied and changed <= a.max_lines
    print(
        json.dumps(
            {
                "allowed": ok,
                "files": files,
                "denied_files": denied,
                "changed_lines": changed,
                "max_lines": a.max_lines,
            },
            indent=2,
        )
    )
    raise SystemExit(0 if ok else 4)


if __name__ == "__main__":
    main()
