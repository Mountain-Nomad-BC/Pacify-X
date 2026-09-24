from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.nsai_knowledge import build_nsai_index, pretty_json_bytes, write_nsai_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministically build the derived PX NSAI navigation index.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Fail if index.json is absent or differs from a deterministic rebuild.")
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    library = root / "knowledge" / "nsai"
    generated = build_nsai_index(library, contract_root=root / "contracts")
    target = library / "index.json"
    expected = pretty_json_bytes(generated)
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            print(json.dumps({"valid": False, "reason": "derived_index_stale"}, indent=2, sort_keys=True))
            return 1
        print(json.dumps({"valid": True, "object_count": generated["object_count"], "library_sha256": generated["library_sha256"]}, indent=2, sort_keys=True))
        return 0
    write_nsai_index(library, contract_root=root / "contracts")
    print(json.dumps({"valid": True, "object_count": generated["object_count"], "library_sha256": generated["library_sha256"], "path": target.relative_to(root).as_posix()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
