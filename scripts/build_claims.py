from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.build_claims import (  # noqa: E402
    CLAIMS_PATH,
    expected_build_claims,
    validate_build_claims,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or check canonical PX build claims"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.apply:
        # Compute before creating the prepared file: registry/**/* is itself a
        # claimed denominator, so the transaction temporary must not inflate it.
        claims = expected_build_claims(root)
        target = root / CLAIMS_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.prepared")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(claims, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    report = validate_build_claims(root)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
