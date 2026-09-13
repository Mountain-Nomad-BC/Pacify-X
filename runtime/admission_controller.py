"""Capability admission with verified evidence and explicit claim-only classification."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
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
    evaluation_binding: Mapping[str, object] | None = None


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
    """Assess the acquired candidate manifest; later use must rebind its bytes."""
    try:
        from .numeric_inputs import bounded_mapping, bounded_json_value, bounded_integer
        from .trusted_evidence import evidence_store_path, acquire_evaluation_binding, _evidence_text

        request = bounded_mapping(request, 'admission request', maximum=12)
        bounded_json_value(request)
        request = json.loads(json.dumps(request, allow_nan=False))
        required = {'schema_version', 'project_id', 'evidence_store', 'accepted_producers',
                    'evidence_refs', 'subject_source', 'assessment_contract'}
        if required - request.keys() or request.keys() - required - {'max_age_seconds'}:
            raise ValueError('admission request fields mismatch')
        if request['schema_version'] != '2.0':
            raise ValueError('bound admission requires request version 2.0')
        project_id = _evidence_text(request['project_id'], 'project_id')
        evaluation, contract, acquired_manifest = acquire_evaluation_binding(root,
            subject_source=request['subject_source'], assessment_contract=request['assessment_contract'],
            interpretation='candidate-assessments/1')
        supplied_manifest = _admission_manifest(manifest)
        manifest = _admission_manifest(acquired_manifest)
        if json.dumps(supplied_manifest, sort_keys=True, allow_nan=False) != json.dumps(manifest, sort_keys=True, allow_nan=False):
            raise ValueError('supplied candidate differs from acquired manifest')
        candidate_id = manifest['id']
        if set(contract) - {'required_evidence', 'id', 'version'}:
            raise ValueError('unsupported assessment contract field')
        declared = contract.get('required_evidence')
        if type(declared) is not list or len(declared) != len(REQUIRED_EVIDENCE) or any(type(v) is not str for v in declared) or set(declared) != set(REQUIRED_EVIDENCE):
            raise ValueError('assessment contract must require all four distinct evidence types')

        store = evidence_store_path(root, request["evidence_store"])
        resolver = TrustedEvidenceResolver(
            store, root / "policies/effect-grant-trust.json"
        )
        refs = request["evidence_refs"]
        producers = request['accepted_producers']
        if type(producers) is not list or not 1 <= len(producers) <= 64:
            raise ValueError('accepted producers must be a bounded nonempty list')
        producers = [_evidence_text(value, 'accepted producer') for value in producers]
        if len(set(producers)) != len(producers):
            raise ValueError('accepted producers must be unique')
        accepted = set(producers)
        max_age = bounded_integer(request.get('max_age_seconds', 86400), 'evidence age', minimum=1, maximum=31536000)
        if type(refs) is not dict or set(refs) != set(REQUIRED_EVIDENCE):
            raise ValueError('evidence references must cover all four evidence types')
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
            expected_evaluation=evaluation,
        )
        if not resolved.verified:
            failures.extend(resolved.reasons)
            continue
        from .trusted_evidence import _validate_evidence_result

        try:
            assessment = _validate_evidence_result(resolved.record.get("result"), evidence_type)
        except (AttributeError, TypeError, ValueError):
            failures.append("evidence_assessment_invalid")
            continue
        field, derive = mapping[evidence_type]
        facts[field] = derive(assessment)
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
    return replace(_classify(
        manifest, facts, authoritative=True, evidence_ids=tuple(sorted(verified_ids))
    ), evaluation_binding=evaluation)


def _admission_manifest(value):
    """Typed core of the candidate-manifest assessment interpretation."""
    from .numeric_inputs import bounded_mapping, bounded_json_value
    from .trusted_evidence import _evidence_text
    value = bounded_mapping(value, 'candidate manifest', maximum=128)
    bounded_json_value(value)
    value = json.loads(json.dumps(value, allow_nan=False))
    for field in ('id', 'version', 'owner'):
        _evidence_text(value.get(field), 'candidate ' + field)
    for field in ('provides', 'consumes', 'effects', 'dependencies'):
        items = value.get(field)
        if type(items) is not list or len(items) > 256:
            raise ValueError('candidate ' + field + ' must be a bounded list')
        for item in items:
            _evidence_text(item, 'candidate ' + field + ' item')
        if len(set(items)) != len(items):
            raise ValueError('candidate ' + field + ' must be unique')
    return value
