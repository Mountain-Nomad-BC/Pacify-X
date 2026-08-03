from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = "PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane."


def test_product_naming_is_explicit_and_consistent() -> None:
    assert IDENTITY in (ROOT / "README.md").read_text(encoding="utf-8")
    assert IDENTITY in (ROOT / "docs/release-process.md").read_text(encoding="utf-8")
    assert IDENTITY in (ROOT / "evidence/README.md").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "engineering-loop-bootstrap"
    assert "PACIFY-X" in project["description"]
    cli = (ROOT / "runtime/cli.py").read_text(encoding="utf-8")
    assert "PACIFY-X package and command-line control plane" in cli


def test_status_language_does_not_claim_independent_certification() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Status:** Certified deployment-ready" not in readme
    assert "**Status:** Full repair implemented and validated; exact signed publication pending" in readme
    assert "independent certification" in (ROOT / "evidence/README.md").read_text(encoding="utf-8")


def test_evidence_authority_index_identifies_revocation_and_limitations() -> None:
    index = (ROOT / "evidence/README.md").read_text(encoding="utf-8")
    for required in (
        "Current authority", "Revoked certificates", "Signing trust policy",
        "Verification command", "Limitations and audit disposition",
        "release-revocation-0.6.2.json",
    ):
        assert required in index


def test_public_governance_files_are_present_and_project_specific() -> None:
    required = (
        "SECURITY.md", "CONTRIBUTING.md", ".github/CODEOWNERS",
        ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/capability_request.yml", ".github/dependabot.yml",
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
