"""Regression coverage for the compliance/release-invariant scanners.

Owner instruction (2026-09-23): preserve the false-positive scanner cases as regression
fixtures. A compliance scanner that repeatedly reports known-valid SSH syntax or UI fixture
strings will eventually train people to ignore it.

These tests pin BOTH directions:

  * true positives must be detected (so the scanner still works);
  * documented false positives must NOT be detected (so the scanner stays trustworthy).

Each false-positive case is a real string observed in this repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import scripts.verify_release_invariants as invariants  # noqa: E402


# ---------------------------------------------------------------------------
# False positives that MUST NOT be reported
# ---------------------------------------------------------------------------

# (description, line, predicate that must be False)
FALSE_POSITIVE_CASES = [
    (
        "ssh URL scheme in repository normalization is not an email address",
        '    if text.startswith("git@github.com:"):',
        lambda line: _pii_hit(line),
    ),
    (
        "UI preview fixture token is not a credential",
        "    token: 'preview-token-conflict',",
        lambda line: _secret_hit(line),
    ),
    (
        "SLSA buildType identifier URL is provenance vocabulary, not egress",
        '  "buildType": "https://slsa.dev/provenance/v1",',
        lambda line: _network_hit(line),
    ),
    (
        "JSON Schema namespace is an identifier, not egress",
        '  "$schema": "https://json-schema.org/draft/2020-12/schema",',
        lambda line: _network_hit(line),
    ),
    (
        "recorded clone source in the runtime lock is provenance, not egress",
        '        source            = "https://github.com/ggml-org/llama.cpp"',
        lambda line: _network_hit(line),
    ),
    (
        "project repository URL used for licence text is not runtime egress",
        'REPOSITORY = "https://github.com/Mountain-Nomad-BC/Pacify-X"',
        lambda line: _network_hit(line),
    ),
    (
        "technology detection table key is not a telemetry emitter call",
        '    "opentelemetry": "observability",',
        lambda line: _is_emitter(line),
    ),
    (
        "loopback literal is local, not remote egress",
        '        base_url: "http://127.0.0.1:11434",',
        lambda line: _network_hit(line),
    ),
    (
        "RFC-2606 reserved test domain is a fixture, not a real endpoint",
        '        "https://example.invalid/telemetry"',
        lambda line: _network_hit(line),
    ),
]


def _network_hit(line: str) -> bool:
    """Apply the network check's own suppression logic to one line."""

    allow = set(
        invariants._invariant(
            invariants._load_manifest(ROOT), "no-px-operated-remote-endpoints"
        ).get("false_positive_allowlist", [])
    )
    for host in invariants.URL_HOST.findall(line):
        if host in allow or host in invariants.LOOPBACK:
            continue
        if any(marker in line for marker in invariants.IDENTIFIER_CONTEXTS):
            continue
        if "clone" in line:
            continue
        return True
    return False


def _secret_hit(line: str) -> bool:
    allow = tuple(
        invariants._invariant(
            invariants._load_manifest(ROOT), "no-shipped-secrets"
        ).get("false_positive_allowlist_terms", ())
    )
    for pattern in invariants.SECRET_SHAPES:
        if pattern.search(line) and not any(
            token in line.casefold() for token in allow
        ):
            return True
    return False


def _pii_hit(line: str) -> bool:
    allow = tuple(
        invariants._invariant(
            invariants._load_manifest(ROOT), "no-machine-specific-paths-or-pii"
        ).get("false_positive_allowlist_terms", ())
    )
    for _name, pattern in invariants.PII_SHAPES:
        match = pattern.search(line)
        if not match:
            continue
        if any(token in match.group(0) or token in line.casefold() for token in allow):
            continue
        return True
    return False


def _is_emitter(line: str) -> bool:
    return invariants._is_emitter_call(line)


@pytest.mark.parametrize(
    "description,line,predicate",
    FALSE_POSITIVE_CASES,
    ids=[case[0] for case in FALSE_POSITIVE_CASES],
)
def test_documented_false_positives_are_not_reported(
    description, line, predicate
) -> None:
    assert predicate(line) is False, f"false positive reintroduced: {description}"


# ---------------------------------------------------------------------------
# True positives that MUST be reported (the scanner must still work)
# ---------------------------------------------------------------------------

TRUE_POSITIVE_CASES = [
    (
        "real provider key shape",
        'api_key = "sk-abcdefghijklmnopqrstuvwxyz012345"',
        lambda line: _secret_hit(line),
    ),
    (
        "embedded private key block",
        "-----BEGIN RSA PRIVATE KEY-----",
        lambda line: _secret_hit(line),
    ),
    (
        "machine-specific user path",
        r'root = Path(r"c:\Users\Somebody\Documents\project")',
        lambda line: _pii_hit(line),
    ),
    (
        "genuine remote endpoint",
        'url = "https://telemetry.pacify-x-cloud.example/api/ingest"',
        lambda line: _network_hit(line),
    ),
    (
        "genuine telemetry emitter call",
        "reporter.sendTelemetryEvent('px.activation');",
        lambda line: _is_emitter(line),
    ),
]


@pytest.mark.parametrize(
    "description,line,predicate",
    TRUE_POSITIVE_CASES,
    ids=[case[0] for case in TRUE_POSITIVE_CASES],
)
def test_real_findings_are_still_detected(description, line, predicate) -> None:
    assert predicate(line) is True, f"scanner missed a real finding: {description}"


# ---------------------------------------------------------------------------
# The manifest and the live tree
# ---------------------------------------------------------------------------


def test_release_invariants_manifest_is_well_formed() -> None:
    manifest = invariants._load_manifest(ROOT)
    assert manifest["schema_version"] == "px.release-invariants/1.0"
    assert manifest["release_line"] == "0.9.x"
    ids = [i["id"] for i in manifest["invariants"]]
    assert len(ids) == len(set(ids)), "invariant ids must be unique"
    for invariant in manifest["invariants"]:
        assert invariant["statement"].strip()
        assert invariant["reclassification_trigger"].strip()
        assert invariant["status"] in {"enforced", "policy"}
    # The owner explicitly prohibited these claims.
    forbidden = {
        "EU AI Act compliant",
        "CRA compliant",
        "GDPR compliant",
        "SOC 2 compliant",
    }
    assert forbidden.issubset(set(manifest["not_claimed"]))


def test_release_invariants_hold_on_the_current_tree() -> None:
    result = invariants.verify(ROOT)
    assert result["valid"], [r for r in result["results"] if not r["passed"]]


def test_every_enforced_invariant_declares_a_verifier() -> None:
    manifest = invariants._load_manifest(ROOT)
    for invariant in manifest["invariants"]:
        if invariant["status"] == "enforced":
            assert "verification" in invariant, invariant["id"]
            if invariant["id"] in invariants.CHECKS:
                assert invariant["id"] in invariants.CHECKS
