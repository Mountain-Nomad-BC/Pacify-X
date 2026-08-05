from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from runtime.release_evidence import build_evidence_manifest, verify_evidence_manifest
from runtime.release_artifacts import classify_tree, verify_frozen_product
from runtime.release_identity import capture_git_identity, validate_version_surfaces
from runtime.release_signing import (
    bind_content_digest,
    public_key_fingerprint,
    sign_certificate,
    verify_certificate_signature,
)


def _run(root: Path, *args: str) -> None:
    subprocess.run(
        list(args), cwd=root, check=True, text=True, capture_output=True, timeout=30
    )


def _repository() -> Path:
    root = Path(tempfile.mkdtemp()) / "repository"
    root.mkdir()
    _run(root, "git", "init", "-q")
    _run(root, "git", "config", "user.name", "Release Test")
    _run(root, "git", "config", "user.email", "release@example.invalid")
    _run(
        root,
        "git",
        "remote",
        "add",
        "origin",
        "git@github.com:Mountain-Nomad-BC/Pacify-X.git",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="1.2.3"\n', encoding="utf-8"
    )
    (root / "runtime").mkdir()
    (root / "runtime/version.py").write_text('VERSION = "1.2.3"\n', encoding="utf-8")
    (root / "README.md").write_text("**Current release:** v1.2.3\n", encoding="utf-8")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-qm", "release source")
    _run(root, "git", "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    return root


def test_certificate_is_bound_to_git_commit_and_tag() -> None:
    root = _repository()
    result = capture_git_identity(root, version="1.2.3")
    assert result["valid"], result["errors"]
    assert len(result["commit_sha"]) >= 40 and len(result["tree_sha"]) >= 40
    assert result["tag"] == "v1.2.3" and result["tag_object_type"] == "tag"


def test_dirty_tree_fails_before_release_staging() -> None:
    root = _repository()
    (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    result = capture_git_identity(root, version="1.2.3")
    assert not result["valid"] and result["dirty"]


def test_wrong_repository_identity_fails() -> None:
    root = _repository()
    _run(
        root,
        "git",
        "remote",
        "set-url",
        "origin",
        "git@github.com:other/repository.git",
    )
    result = capture_git_identity(root, version="1.2.3")
    assert not result["valid"]
    assert any("repository identity" in error for error in result["errors"])


def test_tag_not_pointing_to_head_fails() -> None:
    root = _repository()
    (root / "later.txt").write_text("later\n", encoding="utf-8")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-qm", "later")
    result = capture_git_identity(root, version="1.2.3")
    assert not result["valid"]
    assert any("does not point to HEAD" in error for error in result["errors"])


def test_release_version_mismatch_fails_before_staging() -> None:
    root = _repository()
    result = validate_version_surfaces(root, asserted="1.2.4")
    assert not result["valid"]
    assert any("asserted release" in error for error in result["errors"])


def test_readme_release_projection_is_generated() -> None:
    root = _repository()
    assert validate_version_surfaces(root)["valid"]
    (root / "README.md").write_text("**Current release:** v9.9.9\n", encoding="utf-8")
    result = validate_version_surfaces(root)
    assert not result["valid"]
    assert any("README" in error for error in result["errors"])


def test_git_tree_change_during_run_aborts_certification() -> None:
    root = _repository()
    (root / "policies").mkdir()
    (root / "policies/release-artifact-policy.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "policy_version": "1.0.0",
                "product_roots": ["policies", "runtime"],
                "product_root_files": ["README.md", "pyproject.toml"],
                "evidence_roots": [],
                "intermediate_names": [".git"],
                "intermediate_name_suffixes": [],
                "intermediate_suffixes": [],
                "control_output_paths": [],
                "evidence_allowed_suffixes": [".json"],
                "unclassified_policy": "fail_closed",
            }
        ),
        encoding="utf-8",
    )
    frozen = classify_tree(root)
    assert frozen["valid"], frozen["errors"]
    (root / "runtime/version.py").write_text('VERSION = "1.2.4"\n', encoding="utf-8")
    assert not verify_frozen_product(root, frozen)["valid"]


def _signing_fixture() -> tuple[Path, Path, Path, dict]:
    root = Path(tempfile.mkdtemp())
    private = root / "release_ed25519"
    _run(
        root,
        "ssh-keygen",
        "-q",
        "-t",
        "ed25519",
        "-N",
        "",
        "-C",
        "release-test",
        "-f",
        str(private),
    )
    fingerprint = public_key_fingerprint(Path(str(private) + ".pub"))
    public_line = Path(str(private) + ".pub").read_text(encoding="utf-8").strip()
    policy = root / "trust.json"
    policy.write_text(
        json.dumps(
            {
                "trusted_signers": [
                    {
                        "identity": "pacify-x-release",
                        "publisher": "Mountain-Nomad-BC",
                        "fingerprint": fingerprint,
                        "public_key": public_line,
                    }
                ],
                "revoked_fingerprints": [],
            }
        ),
        encoding="utf-8",
    )
    return (
        root,
        private,
        policy,
        {"schema_version": "3.0", "release": "1.2.3", "status": "self_certified"},
    )


def test_certificate_signature_verification() -> None:
    root, private, policy, value = _signing_fixture()
    signature = root / "certificate.json.sig"
    certificate = sign_certificate(value, private_key=private, signature_path=signature)
    assert verify_certificate_signature(
        certificate, signature_path=signature, trust_policy_path=policy
    )["valid"]


def test_recomputed_untrusted_checksum_does_not_authenticate_certificate() -> None:
    root, private, policy, value = _signing_fixture()
    signature = root / "certificate.json.sig"
    certificate = sign_certificate(value, private_key=private, signature_path=signature)
    certificate["release"] = "9.9.9"
    certificate = bind_content_digest(certificate)
    assert not verify_certificate_signature(
        certificate, signature_path=signature, trust_policy_path=policy
    )["valid"]


def test_wrong_signing_identity_fails() -> None:
    root, private, policy, value = _signing_fixture()
    signature = root / "certificate.json.sig"
    certificate = sign_certificate(value, private_key=private, signature_path=signature)
    policy_value = json.loads(policy.read_text(encoding="utf-8"))
    policy_value["trusted_signers"][0]["publisher"] = "Different Publisher"
    policy.write_text(json.dumps(policy_value), encoding="utf-8")
    assert not verify_certificate_signature(
        certificate, signature_path=signature, trust_policy_path=policy
    )["valid"]


def test_unsigned_release_certificate_is_rejected() -> None:
    root, _, policy, value = _signing_fixture()
    assert not verify_certificate_signature(
        value, signature_path=root / "missing.sig", trust_policy_path=policy
    )["valid"]


def test_revoked_signing_identity_is_rejected() -> None:
    root, private, policy, value = _signing_fixture()
    signature = root / "certificate.json.sig"
    certificate = sign_certificate(value, private_key=private, signature_path=signature)
    policy_value = json.loads(policy.read_text(encoding="utf-8"))
    policy_value["revoked_fingerprints"] = [certificate["signature"]["key_fingerprint"]]
    policy.write_text(json.dumps(policy_value), encoding="utf-8")
    assert not verify_certificate_signature(
        certificate, signature_path=signature, trust_policy_path=policy
    )["valid"]


def test_evidence_manifest_is_deterministic() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "tests.xml").write_text("<testsuites/>\n", encoding="utf-8")
    roles = {
        "tests.xml": {
            "type": "junit",
            "required": True,
            "generation_gate": "full_tests",
            "producer": "pytest 9",
        }
    }
    first = build_evidence_manifest(
        root, roles=roles, generated_utc="2026-08-03T00:00:00Z"
    )
    second = build_evidence_manifest(
        root, roles=roles, generated_utc="2026-08-03T00:00:00Z"
    )
    assert first == second and first["valid"]


@pytest.mark.parametrize("mutation", ["edit", "delete", "rename"])
def test_evidence_file_tampering_revokes_certificate(mutation: str) -> None:
    root = Path(tempfile.mkdtemp())
    evidence = root / "tests.xml"
    evidence.write_text("<testsuites/>\n", encoding="utf-8")
    roles = {
        "tests.xml": {
            "type": "junit",
            "required": True,
            "generation_gate": "full_tests",
            "producer": "pytest",
        }
    }
    manifest = build_evidence_manifest(
        root, roles=roles, generated_utc="2026-08-03T00:00:00Z"
    )
    if mutation == "edit":
        evidence.write_text("changed\n", encoding="utf-8")
    elif mutation == "delete":
        evidence.unlink()
    else:
        shutil.move(str(evidence), str(root / "renamed.xml"))
    assert not verify_evidence_manifest(root, manifest)["valid"]


def test_missing_required_evidence_fails_verification() -> None:
    root = Path(tempfile.mkdtemp())
    manifest = build_evidence_manifest(
        root, roles={"missing.json": {"type": "report", "required": True}}
    )
    assert not manifest["valid"]


def test_evidence_manifest_path_escape_is_rejected() -> None:
    root = Path(tempfile.mkdtemp())
    manifest = build_evidence_manifest(
        root, roles={"../outside.json": {"type": "report", "required": True}}
    )
    assert not manifest["valid"]


def test_historical_certificate_evidence_remains_addressable() -> None:
    project = Path(__file__).resolve().parents[1]
    for version in ("0.6.1", "0.6.2"):
        assert (project / f"evidence/release-certification-{version}.json").is_file()
        assert (project / f"evidence/release-revocation-{version}.json").is_file()
