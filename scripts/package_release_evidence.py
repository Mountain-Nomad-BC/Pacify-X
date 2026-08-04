"""Build and sign durable, chunked complete-release evidence assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.evidence_custody import build_evidence_custody, verify_evidence_custody
from runtime.release_signing import sign_certificate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--locator-base", required=True)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=90 * 1024 * 1024)
    args = parser.parse_args()
    receipt = build_evidence_custody(
        args.input,
        release=args.release,
        source_commit=args.source_commit,
        output_dir=args.output,
        work_dir=args.work_dir,
        locator_base=args.locator_base,
        chunk_size=args.chunk_size,
        certificate=args.certificate,
    )
    path = args.output / f"pacify-x-v{args.release}-complete-evidence-custody.json"
    signature = path.with_suffix(".json.sig")
    signed = sign_certificate(
        receipt, private_key=args.signing_key, signature_path=signature
    )
    path.write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8", newline="\n")
    verification = verify_evidence_custody(signed, args.output)
    print(
        json.dumps(
            {"valid": verification["valid"], "receipt": str(path), **verification},
            indent=2,
        )
    )
    return 0 if verification["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
