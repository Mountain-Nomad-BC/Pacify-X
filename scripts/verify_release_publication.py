"""Verify and restore a locally certified, signed publication custody bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

from runtime.evidence_custody import reconstruct_evidence_custody
from runtime.release_signing import verify_certificate_signature


SHA256 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
CANDIDATE = re.compile(
    r"^pacify-x-certification-\d{8}-final[1-9]\d*-single$"
)


class PublicationBlocked(RuntimeError):
    """The downloaded draft assets are not the exact certified release."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationBlocked(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one(root: Path, name: str) -> Path:
    if not name or Path(name).name != name:
        raise PublicationBlocked("custody lookup name is unsafe")
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    if len(matches) != 1 or matches[0].is_symlink():
        raise PublicationBlocked(f"custody must contain exactly one regular {name}")
    return matches[0]


def _subject(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, dict):
        raise PublicationBlocked(f"signed {label} subject is missing")
    relative = str(value.get("archive_path") or "")
    if not relative or "\\" in relative or Path(relative).is_absolute():
        raise PublicationBlocked(f"signed {label} archive path is unsafe")
    path = (root / Path(relative)).resolve(strict=True)
    try:
        path.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise PublicationBlocked(f"signed {label} escapes custody") from exc
    if not path.is_file() or path.is_symlink():
        raise PublicationBlocked(f"signed {label} is not a regular file")
    if (
        value.get("sha256") != _sha256(path)
        or ("size" in value and value.get("size") != path.stat().st_size)
    ):
        raise PublicationBlocked(f"signed {label} subject bytes differ")
    return path


def _restore_release_tree(source: Path, target: Path, *, replace: bool) -> None:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    prepared = parent / f".{target.name}.{uuid4().hex}.new"
    backup = parent / f".{target.name}.{uuid4().hex}.old"
    moved = False
    try:
        shutil.copytree(source, prepared)
        if target.exists():
            if not replace:
                raise PublicationBlocked("repository release evidence target already exists")
            os.replace(target, backup)
            moved = True
        os.replace(prepared, target)
        if moved:
            shutil.rmtree(backup)
    except BaseException:
        if moved and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if prepared.exists():
            shutil.rmtree(prepared)


def verify_publication(
    *,
    assets: Path,
    output: Path,
    repository: Path,
    release: str,
    source_commit: str,
    candidate_id: str | None = None,
    vsix_name: str,
    vsix_sha256: str,
    vsix_size: int,
    replace_release_evidence: bool = False,
) -> dict[str, Any]:
    assets = assets.resolve(strict=True)
    repository = repository.resolve(strict=True)
    output = output.resolve()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release):
        raise PublicationBlocked("release must be an exact semantic version")
    if not COMMIT.fullmatch(source_commit):
        raise PublicationBlocked("source commit is invalid")
    if Path(vsix_name).name != vsix_name or not vsix_name.endswith(".vsix"):
        raise PublicationBlocked("VSIX name is unsafe")
    if not SHA256.fullmatch(vsix_sha256) or vsix_size <= 0:
        raise PublicationBlocked("VSIX identity is invalid")
    receipt_path = assets / f"pacify-x-v{release}-complete-evidence-custody.json"
    signature_path = receipt_path.with_suffix(".json.sig")
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise PublicationBlocked("signed custody receipt is missing")
    receipt = _object(receipt_path)
    signature = verify_certificate_signature(
        receipt,
        signature_path=signature_path,
        trust_policy_path=repository / "policies/release-trust.json",
    )
    if signature.get("valid") is not True:
        raise PublicationBlocked("custody receipt signature is invalid")
    if (
        receipt.get("schema_version") != "1.1"
        or receipt.get("receipt_type") != "complete_release_evidence_custody"
        or receipt.get("release") != release
        or receipt.get("source_commit") != source_commit
    ):
        raise PublicationBlocked("custody receipt release/source binding is invalid")
    chunks = receipt.get("chunks")
    if not isinstance(chunks, list):
        raise PublicationBlocked("custody chunk denominator is malformed")
    expected_asset_names = {
        receipt_path.name,
        signature_path.name,
        vsix_name,
        *(str(row.get("filename") or "") for row in chunks if isinstance(row, dict)),
    }
    actual_assets = list(assets.iterdir())
    if (
        "" in expected_asset_names
        or any(not path.is_file() or path.is_symlink() for path in actual_assets)
        or {path.name for path in actual_assets} != expected_asset_names
        or len(actual_assets) != len(expected_asset_names)
    ):
        raise PublicationBlocked("draft release asset denominator is not exact")
    reconstruction = reconstruct_evidence_custody(receipt, assets, output)
    if reconstruction.get("valid") is not True:
        raise PublicationBlocked("custody chunks or safe reconstruction are invalid")

    subjects = receipt.get("subjects")
    if not isinstance(subjects, dict) or set(subjects) != {
        "vsix",
        "installed_operational_summary",
    }:
        raise PublicationBlocked("custody subject denominator is not exact")
    bundled_vsix = _subject(output, subjects["vsix"], "VSIX")
    if (
        bundled_vsix.name != vsix_name
        or _sha256(bundled_vsix) != vsix_sha256
        or bundled_vsix.stat().st_size != vsix_size
    ):
        raise PublicationBlocked("certified VSIX identity differs from publication input")
    vsix = assets / vsix_name
    if (
        not vsix.is_file()
        or vsix.is_symlink()
        or _sha256(vsix) != vsix_sha256
        or vsix.stat().st_size != vsix_size
        or vsix.read_bytes() != bundled_vsix.read_bytes()
    ):
        raise PublicationBlocked("standalone draft VSIX differs from signed custody")
    installed_summary = _subject(
        output,
        subjects["installed_operational_summary"],
        "installed-operational summary",
    )
    summary_subject = subjects["installed_operational_summary"]
    signed_candidate_id = str(summary_subject.get("campaign_id") or "")
    if not CANDIDATE.fullmatch(signed_candidate_id):
        raise PublicationBlocked("signed candidate identity is malformed")
    if candidate_id is not None and candidate_id != signed_candidate_id:
        raise PublicationBlocked("supplied candidate differs from signed custody")
    candidate_id = signed_candidate_id
    summary = _object(installed_summary)
    expected_artifact = {
        "path": f"extension/dist/{vsix_name}",
        "sha256": vsix_sha256,
        "size": vsix_size,
    }
    members = summary.get("members")
    if (
        summary.get("schema_version") != "px.installed-operational-run-summary/1.1"
        or summary.get("campaign_id") != candidate_id
        or summary.get("all_passed") is not True
        or summary.get("retries") != 0
        or summary.get("cross_platform_smokes_parallel") is not True
        or summary.get("windows_hosts_serialized") is not True
        or summary.get("artifact") != expected_artifact
        or not isinstance(members, list)
        or len(members) != 3
        or {row.get("member") for row in members if isinstance(row, dict)}
        != {
            "windows-exact-vsix-smoke",
            "ubuntu-exact-vsix-smoke",
            "exhaustive-installed-exact-vsix-host-walk",
        }
        or any(not isinstance(row, dict) or row.get("exit_code") != 0 for row in members)
        or any(row.get("artifact_unchanged") is not True for row in members)
        or any(row.get("process_tree_closed_verified") is not True for row in members)
    ):
        raise PublicationBlocked("installed-operational summary is not exact passing evidence")
    exhaustive = next(
        row
        for row in members
        if row.get("member") == "exhaustive-installed-exact-vsix-host-walk"
    )
    if any(
        exhaustive.get(key) != expected
        for key, expected in {
            "terminal_state": "completed",
            "operationally_complete": True,
            "scope_complete": True,
            "issue_count": 0,
            "blocking_issue_count": 0,
            "host_error_count": 0,
            "profile_failure_count": 0,
            "workspace_reclaimed": True,
        }.items()
    ):
        raise PublicationBlocked("installed exhaustive-host denominator is incomplete")
    for key in (
        "schema_version",
        "campaign_id",
        "release_identity_sha256",
        "source_product_digest",
        "source_harness_digest",
        "artifact",
    ):
        if summary_subject.get(key) != summary.get(key):
            raise PublicationBlocked(f"signed summary subject {key} binding differs")

    binding = receipt.get("certificate_binding")
    if not isinstance(binding, dict):
        raise PublicationBlocked("custody receipt certificate binding is absent")
    certificate_path = _subject(
        output,
        {
            "archive_path": binding.get("archive_path"),
            "sha256": binding.get("certificate_sha256"),
        },
        "release certificate",
    )
    certificate = _object(certificate_path)
    certificate_paths = [
        path
        for path in output.rglob("certificate.json")
        if path.is_file() and not path.is_symlink()
    ]
    if certificate_paths != [certificate_path]:
        raise PublicationBlocked("custody must contain exactly one release certificate")
    signature_name = str(certificate.get("signature", {}).get("path") or "")
    if Path(signature_name).name != signature_name:
        raise PublicationBlocked("release certificate signature path is unsafe")
    certificate_signature = certificate_path.parent / signature_name
    certificate_check = verify_certificate_signature(
        certificate,
        signature_path=certificate_signature,
        trust_policy_path=repository / "policies/release-trust.json",
    )
    if certificate_check.get("valid") is not True:
        raise PublicationBlocked("release certificate signature is invalid")
    if (
        certificate.get("status") != "self_certified"
        or certificate.get("release") != release
        or certificate.get("source_control", {}).get("commit_sha") != source_commit
    ):
        raise PublicationBlocked("release certificate source binding is invalid")
    if (
        binding.get("certificate_sha256") != _sha256(certificate_path)
        or binding.get("release") != release
        or binding.get("product_digest") != certificate.get("product_digest")
        or binding.get("harness_digest") != certificate.get("harness_digest")
        or binding.get("release_commit") != source_commit
        or summary.get("source_product_digest") != certificate.get("product_digest")
        or summary.get("source_harness_digest") != certificate.get("harness_digest")
    ):
        raise PublicationBlocked("custody receipt certificate binding is invalid")

    artifacts = certificate.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2 or {
        item.get("type") for item in artifacts if isinstance(item, dict)
    } != {"wheel", "sdist"}:
        raise PublicationBlocked("release certificate artifact denominator is invalid")
    filenames = [str(item.get("filename") or "") for item in artifacts]
    if len(filenames) != len(set(filenames)):
        raise PublicationBlocked("release certificate artifact names are not unique")
    artifact_paths: list[Path] = []
    for item in artifacts:
        filename = str(item.get("filename") or "")
        path = _one(output, filename)
        if (
            Path(filename).name != filename
            or item.get("sha256") != _sha256(path)
            or item.get("size_bytes") != path.stat().st_size
        ):
            raise PublicationBlocked(f"certified Python artifact differs: {filename}")
        artifact_paths.append(path)
    artifact_parents = {path.parent for path in artifact_paths}
    if len(artifact_parents) != 1:
        raise PublicationBlocked("certified Python artifacts do not share one directory")

    release_tree = certificate_path.parent
    restored_release = repository / "evidence/releases" / release
    _restore_release_tree(
        release_tree,
        restored_release,
        replace=replace_release_evidence,
    )
    return {
        "schema_version": "px.release-publication-verification/1.0",
        "valid": True,
        "release": release,
        "source_commit": source_commit,
        "candidate_id": candidate_id,
        "vsix": str(vsix),
        "vsix_sha256": vsix_sha256,
        "vsix_size": vsix_size,
        "installed_summary": str(installed_summary),
        "artifact_dir": str(next(iter(artifact_parents))),
        "restored_release_evidence": str(restored_release),
        "custody": reconstruction,
        "custody_signer": signature.get("identity"),
        "certificate_signer": certificate_check.get("identity"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument("--vsix-name", required=True)
    parser.add_argument("--vsix-sha256", required=True)
    parser.add_argument("--vsix-size", type=int, required=True)
    parser.add_argument("--replace-release-evidence", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_publication(
            assets=args.assets,
            output=args.output,
            repository=args.repository,
            release=args.release,
            source_commit=args.source_commit,
            candidate_id=args.candidate_id,
            vsix_name=args.vsix_name,
            vsix_sha256=args.vsix_sha256,
            vsix_size=args.vsix_size,
            replace_release_evidence=args.replace_release_evidence,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (PublicationBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"]},
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
