"""Build and sign durable, chunked complete-release evidence assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.evidence_custody import build_evidence_custody, verify_evidence_custody
from runtime.release_signing import sign_certificate, verify_certificate_signature
from scripts.reconcile_cohesion_cards import _validate_installed_proof


def _covered(path: Path, inputs: list[Path]) -> bool:
    path = path.resolve(strict=True)
    for item in inputs:
        item = item.resolve(strict=True)
        if item == path or (item.is_dir() and path.is_relative_to(item)):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--locator-base", required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--vsix", type=Path, required=True)
    parser.add_argument("--installed-summary", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=90 * 1024 * 1024)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    certificate = args.certificate.resolve(strict=True)
    signature = certificate.with_suffix(".json.sig")
    if not signature.is_file() or signature.is_symlink():
        raise ValueError("release certificate signature is absent")
    vsix = args.vsix.resolve(strict=True)
    summary = args.installed_summary.resolve(strict=True)
    proof = _validate_installed_proof(root, summary.relative_to(root))
    certificate_value = json.loads(certificate.read_text(encoding="utf-8"))
    if (
        proof["campaign_id"] != args.candidate_id
        or (root / str(proof["artifact"]["path"])).resolve(strict=True) != vsix
        or certificate_value.get("release") != args.release
        or certificate_value.get("product_digest") != proof["source_product_digest"]
        or certificate_value.get("harness_digest") != proof["source_harness_digest"]
        or certificate_value.get("source_control", {}).get("commit_sha")
        != args.source_commit
    ):
        raise ValueError(
            "certificate, installed-operational proof, and VSIX identity do not agree"
        )
    inputs = list(args.input)
    for required in (certificate, signature, vsix, summary):
        if not _covered(required, inputs):
            inputs.append(required)
    receipt = build_evidence_custody(
        inputs,
        release=args.release,
        source_commit=args.source_commit,
        output_dir=args.output,
        work_dir=args.work_dir,
        locator_base=args.locator_base,
        chunk_size=args.chunk_size,
        certificate=certificate,
        subjects={"vsix": vsix, "installed_operational_summary": summary},
    )
    receipt["subjects"]["installed_operational_summary"].update(
        {
            key: proof[key]
            for key in (
                "schema_version",
                "campaign_id",
                "release_identity_sha256",
                "source_product_digest",
                "source_harness_digest",
                "artifact",
            )
        }
    )
    path = args.output / f"pacify-x-v{args.release}-complete-evidence-custody.json"
    signature = path.with_suffix(".json.sig")
    signed = sign_certificate(
        receipt, private_key=args.signing_key, signature_path=signature
    )
    path.write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8", newline="\n")
    verification = verify_evidence_custody(signed, args.output)
    authentication = verify_certificate_signature(
        signed,
        signature_path=signature,
        trust_policy_path=root / "policies/release-trust.json",
    )
    valid = verification["valid"] and authentication["valid"]
    print(
        json.dumps(
            {
                "valid": valid,
                "receipt": str(path),
                "custody": verification,
                "authentication": authentication,
            },
            indent=2,
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
