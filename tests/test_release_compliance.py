"""Tests for the release compliance gate.

The gate must be trustworthy in both directions: it must catch a missing required document or a
forbidden compliance claim, and it must not produce noise on the real tree.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import scripts.verify_release_compliance as compliance  # noqa: E402
import scripts.verify_release_invariants as invariants  # noqa: E402


def test_gate_passes_on_the_real_tree() -> None:
    result = compliance.verify(ROOT)
    assert result["valid"], [r for r in result["results"] if not r["passed"]]


def test_every_required_document_is_present() -> None:
    result = compliance.check_required_documents(ROOT)
    assert result["passed"], {"missing": result["missing"], "trivial": result["trivial"]}
    assert result["present_count"] == result["required_count"]


def test_empty_tree_fails_the_gate(tmp_path: Path) -> None:
    # A missing required document must fail the gate.
    result = compliance.check_required_documents(tmp_path)
    assert result["passed"] is False
    assert len(result["missing"]) == result["required_count"]


def test_partial_document_tree_fails_the_gate(tmp_path: Path) -> None:
    # One real document is not enough; every required document must exist.
    first_relative = compliance.REQUIRED_ROOT_DOCS[0][0]
    (tmp_path / first_relative).write_text("# real content\n", encoding="utf-8")
    result = compliance.check_required_documents(tmp_path)
    assert result["passed"] is False
    assert len(result["missing"]) == result["required_count"] - 1
    assert result["present_count"] == 1


def test_policy_artifact_must_be_valid_json(tmp_path: Path) -> None:
    (tmp_path / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / "registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / "policies/release-invariants.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "registry/system_one_decision_policy.json").write_text("{}", encoding="utf-8")
    result = compliance.check_policy_artifacts(tmp_path)
    assert result["passed"] is False
    assert result["invalid"]


# ---------------------------------------------------------------------------
# Forbidden claims: the scanner must fire on a real claim and stay quiet on a denial
# ---------------------------------------------------------------------------

CLAIM_CASES = [
    ("bare claim is flagged", "This product is SOC 2 compliant.", True),
    ("gdpr claim is flagged", "PACIFY-X is GDPR compliant.", True),
    ("hipaa claim is flagged", "Our platform is HIPAA compliant.", True),
    ("denial is not flagged", "PACIFY-X does not claim to be GDPR compliant.", False),
    ("not-claimed list is not flagged", '{"not_claimed": ["GDPR compliant"]}', False),
    ("scoped statement is not flagged", "PACIFY-X is not certified for HIPAA compliant use.", False),
]


def _scan_text_for_claims(text: str) -> list[dict]:
    # Apply the forbidden-claim rules to a single document body.
    findings: list[dict] = []
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.casefold()
        for pattern, label in compliance.FORBIDDEN_CLAIMS:
            if not re.search(pattern, line, re.IGNORECASE):
                continue
            if any(marker in lowered for marker in compliance.NEGATION_MARKERS):
                continue
            findings.append({"line": number, "claim": label, "text": line.strip()})
    return findings


@pytest.mark.parametrize(
    "description,text,should_find",
    CLAIM_CASES,
    ids=[case[0] for case in CLAIM_CASES],
)
def test_claim_detection_both_directions(description: str, text: str, should_find: bool) -> None:
    findings = _scan_text_for_claims(text)
    assert bool(findings) is should_find, f"{description}: {findings}"


def test_exempt_paths_are_exempt() -> None:
    # Documents whose purpose is to deny or assess a framework must be exempt from the claim scan.
    exempt = compliance.CLAIM_EXEMPT_PATHS
    assert "docs/compliance/" in exempt
    assert "DISCLAIMER.md" in exempt
    assert "policies/release-invariants.json" in exempt


def test_version_consistency_check_shape() -> None:
    result = compliance.check_version_consistency(ROOT)
    assert "sources" in result
    assert "problems" in result
    # The tree must not carry contradictory version sources.
    assert result["passed"], result["problems"]


def test_invariants_manifest_is_not_a_compliance_claim_source() -> None:
    # The invariants manifest lists frameworks only to deny them.
    manifest = json.loads((ROOT / "policies/release-invariants.json").read_text(encoding="utf-8"))
    assert manifest["not_claimed"], "the not_claimed list must not be empty"
    for entry in manifest["not_claimed"]:
        assert "compliant" in entry or "certified" in entry or "certification" in entry


# ---------------------------------------------------------------------------
# The project's own contact address is not third-party PII
# ---------------------------------------------------------------------------


def test_project_security_contact_is_allowed_in_disclosure_docs() -> None:
    # The address appears in SECURITY.md and the disclosure documents; that is its purpose.
    # A scanner that flagged it would train people to ignore the PII check.
    manifest = invariants._load_manifest(ROOT)
    inv = invariants._invariant(manifest, "no-machine-specific-paths-or-pii")
    contact_allow = inv.get("project_contact_allowlist", [])
    assert contact_allow, "the project contact allowlist must be declared"
    assert "bjc274@gmail.com" in contact_allow
    result = invariants.check_pii(ROOT, manifest)
    assert result["passed"], result["findings"]


def test_a_third_party_email_is_still_flagged() -> None:
    # A genuine third-party personal address must still be caught.
    manifest = invariants._load_manifest(ROOT)
    inv = invariants._invariant(manifest, "no-machine-specific-paths-or-pii")
    allow = tuple(inv.get("false_positive_allowlist_terms", ()))
    contact_allow = tuple(inv.get("project_contact_allowlist", ()))
    line = "contact: someone.else@realcompany.com"
    flagged = False
    for _name, pattern in invariants.PII_SHAPES:
        match = pattern.search(line)
        if not match:
            continue
        if any(token in match.group(0) or token in line.casefold() for token in allow):
            continue
        if any(token in line for token in contact_allow):
            continue
        flagged = True
    assert flagged is True