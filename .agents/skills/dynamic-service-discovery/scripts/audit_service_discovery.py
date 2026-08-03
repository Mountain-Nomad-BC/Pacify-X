#!/usr/bin/env python3
"""Conservative static warnings for long-lived cached service addresses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

TEXT_SUFFIXES = {".conf", ".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
ADDRESS = re.compile(r"(?i)\b(?:proxy_pass|upstream|endpoint|address|host)\b[^\n]*(?:\d{1,3}\.){3}\d{1,3}")
DISCOVERY = re.compile(r"(?i)\b(?:resolver|service[_-]?discovery|dns[_-]?ttl|ttl|registry|resolve)\b")
EXCLUDES = {".git", ".venv", "node_modules", "vendor", "dist", "build", "quarantine"}


def audit(root: Path, max_bytes: int = 1_000_000) -> dict:
    findings: list[dict] = []
    scanned = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDES)
        for name in sorted(files, key=str.casefold):
            path = Path(current, name)
            if path.suffix.lower() not in TEXT_SUFFIXES or path.is_symlink() or path.stat().st_size > max_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            scanned += 1
            if ADDRESS.search(text) and not DISCOVERY.search(text):
                rel = path.relative_to(root).as_posix()
                findings.append(
                    {
                        "id": hashlib.sha256(f"{rel}:cached-address".encode()).hexdigest()[:16],
                        "path": rel,
                        "rule": "cached-network-identity-without-visible-refresh",
                        "status": "review_required",
                    }
                )
    return {"schema_version": "1.0", "complete": True, "files_scanned": scanned, "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files_scanned": result["files_scanned"], "findings": len(result["findings"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
