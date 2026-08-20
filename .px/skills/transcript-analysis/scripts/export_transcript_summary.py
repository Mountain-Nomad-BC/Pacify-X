"""Portable wrapper for deterministic canonical transcript CSV export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[4]
if (SOURCE_ROOT / "runtime").is_dir() and str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime.paths import framework_root  # noqa: E402
from runtime.transcript_analysis import export_selected_summary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--conversation-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = export_selected_summary(
        args.root or framework_root(),
        args.run,
        args.conversation_id,
        args.output,
        apply=args.apply,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
