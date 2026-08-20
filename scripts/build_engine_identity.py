#!/usr/bin/env python3
"""Publish the exact source-engine manifest used by installed-host receipts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.engine_identity import write_engine_identity


def main() -> int:
    path, value = write_engine_identity(ROOT)
    print(
        json.dumps(
            {
                "path": path.as_posix(),
                "file_total": value["file_total"],
                "tree_sha256": value["tree_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
