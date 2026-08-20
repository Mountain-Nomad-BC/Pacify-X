#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_map")
    ap.add_argument("--out", default="AGENTS.md")
    a = ap.parse_args()
    m = json.loads(Path(a.repo_map).read_text())
    langs = ", ".join(f"{k}:{v}" for k, v in sorted(m.get("languages", {}).items()))
    body = f"""# AGENTS.md\n\n## Repository map\n- Files: {m.get("file_count", 0)}\n- Languages/extensions: {langs}\n\n## Required operating rules\n1. Inspect repository structure and relevant tests before editing.\n2. Do not change generated, vendored, credential, or deployment artifacts without an explicit contract.\n3. Keep patches tied to an evidence-supported root cause.\n4. Run targeted tests, then affected integration and security checks.\n5. Report unknowns, failed checks, side effects, and rollback.\n\n## Discovery commands\n- Search symbols structurally before broad text replacement.\n- Resolve configuration precedence before changing defaults.\n- Map downstream callers and consumers before interface changes.\n"""
    Path(a.out).write_text(body)
    print(json.dumps({"out": a.out, "bytes": len(body)}, indent=2))


if __name__ == "__main__":
    main()
