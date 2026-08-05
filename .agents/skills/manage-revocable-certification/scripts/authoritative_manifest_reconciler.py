#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.resolve() != Path(a.out).resolve():
            files.append(
                {
                    "path": str(p.relative_to(root)).replace("\\", "/"),
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
            )
    m = {
        "root": root.name,
        "file_count": len(files),
        "total_bytes": sum(x["bytes"] for x in files),
        "files": files,
    }
    Path(a.out).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {"file_count": len(files), "total_bytes": m["total_bytes"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
