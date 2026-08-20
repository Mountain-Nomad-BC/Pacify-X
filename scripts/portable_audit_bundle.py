from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.portable_audit_bundle import (  # noqa: E402
    build_portable_audit_bundle,
    verify_portable_audit_bundle,
)


def _inputs(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or label in result:
            raise ValueError("each --input must be a unique label=path")
        result[label] = Path(raw_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify a portable PX audit ZIP")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--input", action="append", required=True)
    build.add_argument("--output-zip", type=Path, required=True)
    build.add_argument("--checksum", type=Path, required=True)
    build.add_argument("--prerequisites", type=Path, required=True)
    build.add_argument("--attestation", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--checksum", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_portable_audit_bundle(
            _inputs(args.input),
            output_zip=args.output_zip,
            checksum_path=args.checksum,
            prerequisites=args.prerequisites,
            attestation=args.attestation,
        )
    else:
        result = verify_portable_audit_bundle(args.bundle, args.checksum)
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

