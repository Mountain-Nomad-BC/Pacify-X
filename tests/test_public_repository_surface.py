from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = "PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane."


def test_product_naming_is_explicit_and_consistent() -> None:
    assert IDENTITY in (ROOT / "README.md").read_text(encoding="utf-8")
    assert IDENTITY in (ROOT / "docs/release-process.md").read_text(encoding="utf-8")
    assert IDENTITY in (ROOT / "evidence/README.md").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert project["name"] == "engineering-loop-bootstrap"
    assert "PACIFY-X" in project["description"]
    cli = (ROOT / "runtime/cli.py").read_text(encoding="utf-8")
    assert "PACIFY-X package and command-line control plane" in cli


def test_status_language_does_not_claim_independent_certification() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Status:** Certified deployment-ready" not in readme
    assert (
        "**Status:** Signed self-certified release published; public assets reproduced and verified"
        in readme
    )
    assert "independent certification" in (ROOT / "evidence/README.md").read_text(
        encoding="utf-8"
    )


def test_readme_defaults_to_063_without_a_revocation_warning() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[!WARNING]" not in readme
    assert "0.6.2" not in readme
    assert "git clone --branch v0.6.3 --single-branch" in readme
    assert "immutable certified source tag" in readme


def test_public_release_receipt_matches_canonical_certificate_and_signature() -> None:
    release_root = ROOT / "evidence/releases/0.6.3"
    receipt = json.loads(
        (release_root / "public-release-verification.json").read_text(encoding="utf-8")
    )
    certificate_path = release_root / "certificate.json"
    signature_path = release_root / "certificate.json.sig"
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    assets = {item["filename"]: item for item in receipt["public_assets"]}

    assert receipt["valid"] is True
    assert receipt["release"] == certificate["release"] == "0.6.3"
    assert (
        receipt["source_control"]["commit_sha"]
        == certificate["source_control"]["commit_sha"]
    )
    assert receipt["certificate"]["product_digest"] == certificate["product_digest"]
    assert (
        receipt["certificate"]["trusted_key_fingerprint"]
        == certificate["signature"]["key_fingerprint"]
    )
    assert (
        assets["certificate.json"]["sha256"]
        == hashlib.sha256(certificate_path.read_bytes()).hexdigest()
    )
    assert (
        assets["certificate.json.sig"]["sha256"]
        == hashlib.sha256(signature_path.read_bytes()).hexdigest()
    )
    for artifact in certificate["artifacts"]:
        assert assets[artifact["filename"]]["sha256"] == artifact["sha256"]
        assert assets[artifact["filename"]]["size_bytes"] == artifact["size_bytes"]


def test_evidence_authority_index_identifies_revocation_and_limitations() -> None:
    index = (ROOT / "evidence/README.md").read_text(encoding="utf-8")
    for required in (
        "Current authority",
        "Revoked certificates",
        "Signing trust policy",
        "Verification command",
        "Limitations and audit disposition",
        "release-revocation-0.6.2.json",
    ):
        assert required in index


def test_public_governance_files_are_present_and_project_specific() -> None:
    required = (
        "SECURITY.md",
        "CONTRIBUTING.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/capability_request.yml",
        ".github/dependabot.yml",
        "docs/release-process.md",
    )
    for relative in required:
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.stat().st_size > 20, relative
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "effect-grant" in security
    assert "revocation" in security
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "No hard deletion" in contributing or "do not hard-delete" in contributing


def test_release_wheelhouse_is_outside_the_classified_source_tree() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'Join-Path $env:RUNNER_TEMP "pacify-x-release-wheelhouse"' in workflow
    assert "PACIFY_X_RELEASE_WHEELHOUSE=$wheelhouse" in workflow
    assert "--wheelhouse $env:PACIFY_X_RELEASE_WHEELHOUSE" in workflow
    assert 'Join-Path $env:RUNNER_TEMP "pacify-x-release-artifacts"' in workflow
    assert "PACIFY_X_RELEASE_ARTIFACT_DIR=$artifactDir" in workflow
    assert "--artifact-dir $env:PACIFY_X_RELEASE_ARTIFACT_DIR" in workflow
    assert 'Join-Path $env:RUNNER_TEMP "pacify-x-release-result.json"' in workflow
    assert 'Join-Path $env:RUNNER_TEMP "pacify-x-release-verification.json"' in workflow
    assert "Tee-Object release-result.json" not in workflow
    assert "Tee-Object release-verification.json" not in workflow
    assert 'icacls $keyPath /inheritance:r /grant:r "${env:USERNAME}:(R,W)"' in workflow
    assert "ssh-keygen -y -f $keyPath" in workflow
    assert 'WriteAllText("${keyPath}.pub"' in workflow
    assert "release signing key is not trusted by repository policy" in workflow
    assert "-Path wheelhouse" not in workflow
    assert "-d wheelhouse" not in workflow
    assert "New-Item -ItemType Directory -Path release-artifacts" not in workflow
    assert "package_release_evidence.py" in workflow
    assert (
        "complete-evidence-custody" not in workflow
        or "Package durable complete evidence custody" in workflow
    )


def test_governed_ci_runs_independent_receipted_assurance_gates() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "gate: [contracts, dependencies, platform, lint, generated, registry, licensing, structural]"
        in workflow
    )
    assert "gates run --gate ${{ matrix.gate }}" in workflow
    assert "needs: assurance-gates" in workflow


def test_assurance_workflows_do_not_build_the_project_before_source_audits() -> None:
    exact_tools = "python -m pip install --require-hashes -r requirements-release.txt"
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/scheduled-assurance.yml",
    ):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        assert exact_tools in workflow
        assert "python -m pip install .[release]" not in workflow
