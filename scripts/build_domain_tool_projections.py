"""Generate or check the seven portable domain-wrapper projections."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


OWNERS = (
    "analyze-repository-intelligence",
    "engineer-verification-lab",
    "govern-operating-kernel",
    "govern-runtime-protocol-deployment",
    "manage-revocable-certification",
    "operate-memory-retrieval-observability",
    "secure-agent-supply-chain",
)


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root = root.resolve()
    source = root / "templates/generated/domain_tool.py"
    expected = source.read_bytes()
    stale: list[str] = []
    for owner in OWNERS:
        target = root / ".agents/skills" / owner / "scripts/domain_tool.py"
        if not target.is_file() or target.read_bytes() != expected:
            stale.append(target.relative_to(root).as_posix())
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(expected)
    return {
        "schema_version": "1.0", "valid": not stale if check else True,
        "owner": source.relative_to(root).as_posix(), "owner_sha256": hashlib.sha256(expected).hexdigest(),
        "projection_count": len(OWNERS), "stale": stale, "check": check,
    }


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(".")); parser.add_argument("--check", action="store_true")
    args = parser.parse_args(); result = reconcile(args.root, check=args.check); print(json.dumps(result, indent=2)); return 0 if result["valid"] else 1


if __name__ == "__main__": raise SystemExit(main())
