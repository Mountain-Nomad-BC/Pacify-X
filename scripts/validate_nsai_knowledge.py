from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.nsai_knowledge import audit_nsai_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the PX NSAI single-object knowledge library.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allow-stale-index", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    result = audit_nsai_library(
        root / "knowledge" / "nsai",
        contract_root=root / "contracts",
        require_index_match=not args.allow_stale_index,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
