"""Run the canonical producer census and optionally retain the exact document.

Usage:
    python -m runtime.producer_census                      # print, write nothing
    python docs/repair/evidence/px-os-1067-run-census.py <out.json>

This is the retained launcher for PX-OS-1067 evidence runs. It writes only the
explicitly named artifact and never mutates registries or product source.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from runtime.producer_census import census  # noqa: E402


def main() -> int:
    started = time.time()
    document = census(ROOT)
    document["elapsed_seconds"] = round(time.time() - started, 1)
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.is_absolute():
            target = ROOT / target
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        print(json.dumps({"target": str(target), "elapsed_seconds": document["elapsed_seconds"]}))
    else:
        print(json.dumps(document, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
