"""Outcome verification with a strict boundary between claims and authority."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .trusted_evidence import EvidenceScope, TrustedEvidenceResolver


@dataclass(frozen=True)
class VerificationDecision:
    status: str
    failed_checks: tuple[str, ...]
    warnings: tuple[str, ...]
    approved_evidence_ids: tuple[str, ...]
    authoritative: bool = False
    decision_source: str = "caller_asserted_claims"


def evaluate_claims(
    postconditions: Mapping[str, bool],
    evidence: Sequence[Mapping[str, object]],
    *,
    policy_allowed: bool,
    executor_claimed_complete: bool,
) -> VerificationDecision:
    """Compatibility classifier. Its result is never authoritative verification."""
    failed = sorted(name for name, passed in postconditions.items() if not passed)
    current = sorted(
        str(item["id"])
        for item in evidence
        if item.get("status") == "current"
        and item.get("valid") is True
        and item.get("id")
    )
    warnings: list[str] = [
        "caller assertions were evaluated but not independently verified"
    ]
    if not policy_allowed:
        return VerificationDecision(
            "blocked",
            ("policy claim did not allow outcome",),
            tuple(warnings),
            tuple(current),
        )
    if not postconditions:
        return VerificationDecision(
            "failed", ("no postconditions declared",), tuple(warnings), tuple(current)
        )
    if failed:
        if executor_claimed_complete:
            warnings.append("executor completion claim contradicted by postconditions")
        return VerificationDecision(
            "failed", tuple(failed), tuple(warnings), tuple(current)
        )
    if not current:
        return VerificationDecision(
            "partial",
            (),
            tuple(warnings + ["postconditions lack current claimed evidence"]),
            (),
        )
    if not executor_claimed_complete:
        warnings.append(
            "postconditions passed although executor did not claim completion"
        )
    return VerificationDecision("verified", (), tuple(warnings), tuple(current))


# Compatibility import used by the in-process orchestration evaluator. The public
# CLI exposes this behavior only as evaluate-outcome-claims.
verify = evaluate_claims


def verify_authoritative(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    """Assess exact acquired artifact bytes using bound signed assessments."""
    from .numeric_inputs import bounded_mapping, bounded_json_value, bounded_integer
    from .trusted_evidence import (
        _evidence_text, evidence_store_path, acquire_evaluation_binding,
    )

    try:
        request = bounded_mapping(request, 'outcome request', maximum=16)
        bounded_json_value(request)
        request = json.loads(json.dumps(request, allow_nan=False))
        required = {'schema_version', 'outcome_id', 'project_id', 'task_id',
                    'execution_id', 'subject_source', 'postcondition_contract',
                    'policy_decision_ref', 'evidence_refs', 'evidence_store',
                    'accepted_producers'}
        if required - request.keys() or request.keys() - required - {'session_id', 'max_age_seconds'}:
            raise ValueError('outcome request fields mismatch')
        if request['schema_version'] != '2.0':
            raise ValueError('authoritative artifact assessment requires request version 2.0')
        scope = EvidenceScope(*[_evidence_text(request[field], field) for field in
            ('project_id', 'outcome_id', 'task_id', 'execution_id')],
            session_id=_evidence_text(request.get('session_id', ''), 'session_id', optional=True))
        accepted = request['accepted_producers']
        if type(accepted) is not list or not 1 <= len(accepted) <= 64:
            raise ValueError('accepted producers must be a nonempty bounded list')
        accepted = [_evidence_text(value, 'accepted producer') for value in accepted]
        if len(set(accepted)) != len(accepted):
            raise ValueError('accepted producers must be unique')
        max_age = bounded_integer(request.get('max_age_seconds', 86400),
                                  'evidence age', minimum=1, maximum=31536000)
        refs = request['evidence_refs']
        if type(refs) is not list or not 1 <= len(refs) <= 256:
            raise ValueError('evidence references must be a nonempty bounded list')
        seen = set()
        for item in refs:
            if type(item) is not dict or set(item) - {'ref', 'sha256'} or 'ref' not in item:
                raise ValueError('evidence reference fields mismatch')
            ref = _evidence_text(item['ref'], 'evidence reference', maximum=137)
            if ref in seen:
                raise ValueError('evidence references must be unique')
            seen.add(ref)
        policy_ref = _evidence_text(request['policy_decision_ref'], 'policy reference', maximum=137)
        evaluation, contract, _ = acquire_evaluation_binding(root,
            subject_source=request['subject_source'],
            assessment_contract=request['postcondition_contract'],
            interpretation='outcome-postconditions/1')
        if set(contract) - {'required_checks', 'id', 'version', 'risk', 'evidence'}:
            raise ValueError('unsupported postcondition contract field')
        checks = contract.get('required_checks')
        if type(checks) is not list or not 1 <= len(checks) <= 256:
            raise ValueError('required checks must be a nonempty bounded list')
        required_checks = tuple(_evidence_text(value, 'required check') for value in checks)
        if len(set(required_checks)) != len(required_checks):
            raise ValueError('required checks must be unique')
        store = evidence_store_path(root, request['evidence_store'])
        resolver = TrustedEvidenceResolver(store, root / 'policies/effect-grant-trust.json')
    except (OSError, KeyError, TypeError, ValueError, OverflowError):
        return _result('invalid_request', reasons=['outcome_request_or_subject_resolution_failed'])

    options = dict(scope=scope, accepted_producers=set(accepted),
                   max_age_seconds=max_age, expected_evaluation=evaluation)
    policy = resolver.resolve(policy_ref, required_type='policy_decision', **options)
    reasons = list(policy.reasons)
    if not policy.verified:
        reasons.append('policy_evidence_not_verified')
    elif policy.record['result'].get('allowed') is not True:
        reasons.append('policy_denied')
    resolved = []
    observations = {name: set() for name in required_checks}
    for item in refs:
        value = resolver.resolve(item['ref'], required_type='postcondition',
            expected_sha256=item.get('sha256'), **options)
        resolved.append(value)
        reasons.extend(value.reasons)
        if not value.verified:
            reasons.append('postcondition_evidence_not_verified')
            continue
        checks = value.record['result']['postconditions']
        for name, passed in checks.items():
            if name not in observations:
                reasons.append('unexpected_postcondition:' + name)
            else:
                observations[name].add(passed)
    observed = {name: values == {True} for name, values in observations.items() if values}
    failed = sorted(name for name in required_checks if observations[name] != {True})
    reasons.extend('postcondition_failed:' + name for name in failed)
    reasons.extend('postcondition_contradicted:' + name for name, values in observations.items() if len(values) > 1)
    reasons = sorted(set(reasons))
    decision = ('evidence_integrity_failure' if any('integrity' in reason or 'hash_mismatch' in reason for reason in reasons)
                else 'insufficient_trusted_evidence' if any(reason in {
                    'evidence_missing', 'evidence_stale', 'evidence_scope_mismatch',
                    'evidence_evaluation_mismatch', 'evidence_producer_unapproved',
                    'evidence_signature_missing', 'evidence_signer_untrusted'} for reason in reasons)
                else 'verification_failed' if reasons else 'verified')
    output = _result(decision, reasons=reasons,
        policy={'resolved': policy.resolved, 'authentic': policy.signature_valid,
                'applicable': policy.verified and policy.record['result'].get('allowed') is True},
        evidence={'requested':len(refs), 'resolved':sum(v.resolved for v in resolved),
            'integrity_valid':sum(v.integrity_valid for v in resolved),
            'fresh':sum(v.fresh for v in resolved), 'scope_valid':sum(v.scope_valid for v in resolved),
            'verified_ids':sorted({v.record['evidence_id'] for v in resolved if v.verified})},
        postconditions={'contract_resolved':True, 'required':list(required_checks),
                        'observed':observed, 'passed':not failed})
    output['evaluation_binding'] = evaluation
    output['evidence_level'] = 'signed-artifact-assessment'
    return output


def _result(
    decision: str,
    *,
    reasons: Sequence[str],
    policy: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    postconditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verified = decision == "verified"
    return {
        "evaluated": decision != "invalid_request",
        "verified": verified,
        "authoritative": verified,
        "decision": decision,
        "decision_source": "resolved_signed_evidence",
        "policy": dict(
            policy or {"resolved": False, "authentic": False, "applicable": False}
        ),
        "evidence": dict(
            evidence
            or {
                "requested": 0,
                "resolved": 0,
                "integrity_valid": 0,
                "fresh": 0,
                "scope_valid": 0,
                "verified_ids": [],
            }
        ),
        "postconditions": dict(
            postconditions or {"contract_resolved": False, "passed": False}
        ),
        "reasons": sorted(set(map(str, reasons))),
    }
