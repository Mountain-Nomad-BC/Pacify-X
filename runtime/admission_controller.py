"""Capability admission with verified evidence and explicit claim-only classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .trusted_evidence import EvidenceScope, TrustedEvidenceResolver

KNOWN_EFFECTS = {
    "read_local",
    "trace_write",
    "write_workspace",
    "install_tool",
    "network",
    "run_service",
    "secret_access",
    "migration",
    "destructive",
}
HIGH_RISK_EFFECTS = {
    "install_tool",
    "network",
    "run_service",
    "secret_access",
    "migration",
    "destructive",
}
REQUIRED_EVIDENCE = ("provenance", "license", "tests", "security")


@dataclass(frozen=True)
class AdmissionDecision:
    evaluated: bool
    request_valid: bool
    accepted: bool
    authoritative: bool
    decision_source: str
    disposition: str
    reasons: tuple[str, ...]
    allowed_environment: str
    promotion_state: str
    verified_evidence_ids: tuple[str, ...] = ()


def _classify(
    manifest: Mapping[str, object],
    facts: Mapping[str, object],
    *,
    authoritative: bool,
    evidence_ids: tuple[str, ...] = (),
) -> AdmissionDecision:
    fatal: list[str] = []
    restrictions: list[str] = []
    required = {
        "id",
        "version",
        "owner",
        "provides",
        "consumes",
        "effects",
        "dependencies",
    }
    missing = sorted(required - set(manifest))
    if missing:
        fatal.append("missing manifest fields: " + ", ".join(missing))
    effects = set(manifest.get("effects", ()))
    unknown = sorted(effects - KNOWN_EFFECTS)
    if unknown:
        fatal.append("unknown effects: " + ", ".join(unknown))
    if not facts.get("provenance_verified"):
        fatal.append("provenance is not verified")
    if not facts.get("license_reviewed"):
        fatal.append("license is not reviewed")
    if facts.get("malicious_or_unsafe"):
        disposition, reasons, environment, promotion = (
            "reject",
            ("unsafe behavior evidence",),
            "none",
            "rejected",
        )
    elif fatal:
        disposition, reasons, environment, promotion = (
            "quarantine",
            tuple(fatal),
            "metadata-review-only",
            "candidate",
        )
    else:
        if not facts.get("tests_passed"):
            restrictions.append("validation tests have not passed")
        if effects & HIGH_RISK_EFFECTS:
            restrictions.append(
                "high-risk effects require an approved adapter and runtime approval"
            )
        if restrictions:
            disposition, reasons, environment, promotion = (
                "restrict",
                tuple(restrictions),
                "sandbox-or-read-only",
                "admitted_restricted",
            )
        else:
            disposition, reasons, environment, promotion = (
                "admit",
                (),
                "governed-runtime",
                "admitted",
            )
    if not authoritative:
        return AdmissionDecision(
            True,
            not missing and not unknown,
            False,
            False,
            "caller_asserted_claims",
            disposition,
            tuple(reasons) + ("claim-only result cannot promote a candidate",),
            "metadata-review-only",
            "candidate",
            (),
        )
    return AdmissionDecision(
        True,
        not missing and not unknown,
        disposition in {"admit", "restrict"},
        True,
        "resolved_signed_evidence",
        disposition,
        tuple(reasons),
        environment,
        promotion,
        evidence_ids,
    )


def evaluate_claims(
    manifest: Mapping[str, object], evidence: Mapping[str, object]
) -> AdmissionDecision:
    """Classify caller claims without treating them as verified admission evidence."""
    return _classify(manifest, evidence, authoritative=False)


# Compatibility alias. Public authoritative admission uses review_authoritative.
review = evaluate_claims


def review_authoritative(
    root: Path, manifest: Mapping[str, object], request: Mapping[str, Any]
) -> AdmissionDecision:
    """Resolve signed admission receipts and derive the admission facts."""
    try:
        candidate_id = str(manifest["id"])
        project_id = str(request["project_id"])
        store_relative = Path(str(request["evidence_store"]))
        store = (root.resolve() / store_relative).resolve()
        if store_relative.is_absolute() or root.resolve() not in store.parents:
            raise ValueError("evidence_store must be product-relative")
        resolver = TrustedEvidenceResolver(
            store, root / "policies/effect-grant-trust.json"
        )
        refs = request["evidence_refs"]
        accepted = set(map(str, request["accepted_producers"]))
        max_age = int(request.get("max_age_seconds", 86400))
        if not isinstance(refs, dict):
            raise ValueError("evidence_refs must be an object")
    except (KeyError, OSError, TypeError, ValueError) as error:
        return AdmissionDecision(
            False,
            False,
            False,
            False,
            "request_validation",
            "reject",
            (f"invalid admission request: {error}",),
            "none",
            "rejected",
        )
    facts: dict[str, object] = {}
    verified_ids: list[str] = []
    failures: list[str] = []
    scope = EvidenceScope(project_id, candidate_id)
    mapping = {
        "provenance": (
            "provenance_verified",
            lambda value: value.get("verified") is True,
        ),
        "license": (
            "license_reviewed",
            lambda value: value.get("reviewed") is True
            and value.get("allowed") is True,
        ),
        "tests": ("tests_passed", lambda value: value.get("passed") is True),
        "security": (
            "malicious_or_unsafe",
            lambda value: value.get("malicious_or_unsafe") is True,
        ),
    }
    for evidence_type in REQUIRED_EVIDENCE:
        reference = refs.get(evidence_type)
        if not isinstance(reference, str):
            failures.append(f"missing_{evidence_type}_evidence")
            continue
        resolved = resolver.resolve(
            reference,
            scope=scope,
            accepted_producers=accepted,
            max_age_seconds=max_age,
            required_type=evidence_type,
        )
        if not resolved.verified:
            failures.extend(resolved.reasons)
            continue
        field, derive = mapping[evidence_type]
        facts[field] = derive(resolved.record.get("result", {}))
        verified_ids.append(str(resolved.record.get("evidence_id")))
    if failures:
        return AdmissionDecision(
            True,
            True,
            False,
            False,
            "resolved_signed_evidence",
            "quarantine",
            tuple(sorted(set(failures))),
            "metadata-review-only",
            "candidate",
            tuple(sorted(verified_ids)),
        )
    return _classify(
        manifest, facts, authoritative=True, evidence_ids=tuple(sorted(verified_ids))
    )
