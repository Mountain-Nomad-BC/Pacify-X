"""Reconcile packaged Studio operation contracts to the canonical registry owner."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECTIONS = (
    Path("runtime/studio_operations.json"),
    Path("extension/resources/studio-operations.json"),
)


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root = root.resolve(strict=True)
    owner = root / "registry/studio_operations.json"
    payload = owner.read_bytes()
    changed: list[str] = []
    for relative in PROJECTIONS:
        target = root / relative
        if not target.is_file() or target.read_bytes() != payload:
            changed.append(relative.as_posix())
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
    return {
        "schema_version": "px.studio-operation-projections/1.0",
        "valid": not changed or not check,
        "check": check,
        "owner": "registry/studio_operations.json",
        "owner_sha256": hashlib.sha256(payload).hexdigest(),
        "projection_count": len(PROJECTIONS),
        "changed": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root, check=args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
