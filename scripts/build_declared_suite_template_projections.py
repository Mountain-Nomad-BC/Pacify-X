"""Generate or check declared-suite pack template projections."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


KINDS = ("certification", "task", "tool_contract")


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root = root.resolve(); owner_root = root / "templates/declared_suite/authoritative-pack"; stale = []; records = []
    for kind in KINDS:
        source = owner_root / f"{kind}.json"; expected = source.read_bytes(); digest = hashlib.sha256(expected).hexdigest()
        for pack in range(1, 8):
            target = root / "templates/declared_suite" / f"pack-{pack:02d}-{kind}.json"
            if not target.is_file() or target.read_bytes() != expected:
                stale.append(target.relative_to(root).as_posix())
                if not check: target.write_bytes(expected)
        records.append({"kind": kind, "owner": source.relative_to(root).as_posix(), "sha256": digest, "projections": 7})
    return {"schema_version": "1.0", "valid": not stale if check else True, "records": records, "projection_count": 21, "stale": stale, "check": check}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,default=Path(".")); parser.add_argument("--check",action="store_true")
    args=parser.parse_args(); result=reconcile(args.root,check=args.check); print(json.dumps(result,indent=2)); return 0 if result["valid"] else 1


if __name__ == "__main__": raise SystemExit(main())
