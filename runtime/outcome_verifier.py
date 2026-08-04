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
    """Derive an outcome verdict exclusively from signed records in an approved store."""
    reasons: list[str] = []
    required = {
        "outcome_id",
        "project_id",
        "task_id",
        "execution_id",
        "postcondition_contract",
        "policy_decision_ref",
        "evidence_refs",
        "evidence_store",
        "accepted_producers",
    }
    missing = sorted(required - set(request))
    if missing:
        return _result(
            "invalid_request", reasons=["missing request fields: " + ", ".join(missing)]
        )
    contract_relative = Path(str(request["postcondition_contract"]))
    contract_path = (root.resolve() / contract_relative).resolve()
    if (
        contract_relative.is_absolute()
        or root.resolve() not in contract_path.parents
        or not contract_path.is_file()
    ):
        return _result(
            "invalid_request", reasons=["postcondition_contract_not_resolved"]
        )
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        required_checks = tuple(map(str, contract["required_checks"]))
        if not required_checks:
            raise ValueError
        store_relative = Path(str(request["evidence_store"]))
        store = (root.resolve() / store_relative).resolve()
        if store_relative.is_absolute() or root.resolve() not in store.parents:
            raise ValueError("evidence_store must be product-relative")
        resolver = TrustedEvidenceResolver(
            store, root / "policies/effect-grant-trust.json"
        )
        scope = EvidenceScope(
            str(request["project_id"]),
            str(request["outcome_id"]),
            str(request["task_id"]),
            str(request["execution_id"]),
            session_id=str(request.get("session_id", "")),
        )
        accepted = set(map(str, request["accepted_producers"]))
        max_age = int(request.get("max_age_seconds", 86400))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _result(
            "invalid_request",
            reasons=[f"request_resolution_failed:{type(error).__name__}"],
        )

    policy = resolver.resolve(
        str(request["policy_decision_ref"]),
        scope=scope,
        accepted_producers=accepted,
        max_age_seconds=max_age,
        required_type="policy_decision",
    )
    if not policy.verified:
        reasons.extend(policy.reasons)
    elif policy.record.get("result", {}).get("allowed") is not True:
        reasons.append("policy_denied")

    refs = request.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        reasons.append("evidence_missing")
        refs = []
    resolved = []
    observed_checks: dict[str, bool] = {}
    for item in refs:
        if not isinstance(item, dict) or "ref" not in item:
            reasons.append("invalid_evidence_reference")
            continue
        value = resolver.resolve(
            str(item["ref"]),
            scope=scope,
            accepted_producers=accepted,
            max_age_seconds=max_age,
            expected_sha256=item.get("sha256"),
            required_type="postcondition",
        )
        resolved.append(value)
        reasons.extend(value.reasons)
        if value.verified:
            checks = value.record.get("result", {}).get("postconditions", {})
            if isinstance(checks, dict):
                for name, passed in checks.items():
                    observed_checks[str(name)] = passed is True
    failed = sorted(
        name for name in required_checks if observed_checks.get(name) is not True
    )
    if failed:
        reasons.extend(f"postcondition_failed:{name}" for name in failed)
    integrity_failure = any(
        "integrity" in reason or "hash_mismatch" in reason for reason in reasons
    )
    decision = (
        "evidence_integrity_failure"
        if integrity_failure
        else "insufficient_trusted_evidence"
        if reasons
        and any(
            reason
            in {
                "evidence_missing",
                "evidence_stale",
                "evidence_scope_mismatch",
                "evidence_producer_unapproved",
                "evidence_signature_missing",
                "evidence_signer_untrusted",
            }
            for reason in reasons
        )
        else "verification_failed"
        if reasons
        else "verified"
    )
    return _result(
        decision,
        reasons=reasons,
        policy={
            "resolved": policy.resolved,
            "authentic": policy.signature_valid,
            "applicable": policy.scope_valid
            and policy.record is not None
            and policy.record.get("result", {}).get("allowed") is True,
        },
        evidence={
            "requested": len(refs),
            "resolved": sum(item.resolved for item in resolved),
            "integrity_valid": sum(item.integrity_valid for item in resolved),
            "fresh": sum(item.fresh for item in resolved),
            "scope_valid": sum(item.scope_valid for item in resolved),
            "verified_ids": [
                str(item.record.get("evidence_id"))
                for item in resolved
                if item.verified
            ],
        },
        postconditions={
            "contract_resolved": True,
            "required": list(required_checks),
            "observed": observed_checks,
            "passed": not failed,
        },
    )


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
