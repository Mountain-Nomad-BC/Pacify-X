"""Incrementally build the PX-native certification-group manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.test_profiles import build_test_group_index  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the PX-native certification-group manifest."
    )
    parser.parse_args(argv)
    result = build_test_group_index(ROOT)
    target = ROOT / "registry/test_group_index.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("test_file_count", "tracked_python_file_count", "verified_file_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
