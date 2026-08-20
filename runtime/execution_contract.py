"""Fail-closed execution-contract validation.

This module authorizes an execution envelope. It does not execute the action.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .effect_grants import validate_effect_grant
from .operation_authority import AuthorityRequest, decide as decide_authority
from .trusted_evidence import EvidenceScope, TrustedEvidenceResolver

NON_READ_EFFECTS = {
    "write_workspace",
    "install_tool",
    "network",
    "run_service",
    "secret_access",
    "migration",
    "destructive",
}


@dataclass(frozen=True)
class ExecutionRequest:
    capability_id: str
    effects: tuple[str, ...]
    timeout_seconds: int
    max_tool_calls: int
    idempotency_key: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    approved_effects: tuple[str, ...]
    approval_id: str | None = None


@dataclass(frozen=True)
class ContractDecision:
    approved: bool
    reasons: tuple[str, ...]
    requires_verification: bool


def enforce(
    request: ExecutionRequest,
    policy: PolicyDecision,
    manifest: Mapping[str, object],
    *,
    max_timeout_seconds: int = 120,
    max_tool_calls: int = 12,
    effect_grant_path: Path | None = None,
    effect_signature_path: Path | None = None,
    effect_trust_policy_path: Path | None = None,
    project_id: str = "",
    session_id: str = "",
    adapter: str = "",
    environment: str = "",
    writable_targets: tuple[Path, ...] = (),
    network_hosts: tuple[str, ...] = (),
    secret_refs: tuple[str, ...] = (),
) -> ContractDecision:
    reasons: list[str] = []
    if manifest.get("id") != request.capability_id:
        reasons.append("manifest capability mismatch")
    if manifest.get("status") not in {"admitted", "active"}:
        reasons.append("capability is not admitted or active")
    declared = set(manifest.get("effects", ()))
    requested = set(request.effects)
    if not requested <= declared:
        reasons.append("request contains undeclared effects")
    if not policy.allowed:
        reasons.append("policy denied execution")
    if not requested <= set(policy.approved_effects):
        reasons.append("effects exceed policy approval")
    if request.timeout_seconds < 1 or request.timeout_seconds > max_timeout_seconds:
        reasons.append("timeout outside budget")
    if request.max_tool_calls < 0 or request.max_tool_calls > max_tool_calls:
        reasons.append("tool-call budget outside limit")
    if requested & NON_READ_EFFECTS:
        if not policy.approval_id:
            reasons.append("non-read effects require approval id")
        if not request.idempotency_key:
            reasons.append("non-read effects require idempotency key")
        if not all(
            (
                effect_grant_path,
                effect_signature_path,
                effect_trust_policy_path,
                project_id,
                session_id,
                adapter,
                environment,
            )
        ):
            reasons.append("non-read effects require an enforced runtime effect grant")
        else:
            try:
                grant = json.loads(effect_grant_path.read_text(encoding="utf-8"))
                validation = validate_effect_grant(
                    grant,
                    signature_path=effect_signature_path,
                    trust_policy_path=effect_trust_policy_path,
                    capability_id=request.capability_id,
                    requested_effects=request.effects,
                    adapter=adapter,
                    environment=environment,
                    project_id=project_id,
                    session_id=session_id,
                    writable_targets=writable_targets,
                    network_hosts=network_hosts,
                    secret_refs=secret_refs,
                    destructive="destructive" in requested,
                    idempotency_key=request.idempotency_key,
                )
                reasons.extend(validation["errors"])
            except (OSError, ValueError, json.JSONDecodeError) as error:
                reasons.append(
                    f"effect grant validation failed: {type(error).__name__}: {error}"
                )
    return ContractDecision(
        not reasons, tuple(reasons), bool(requested & NON_READ_EFFECTS)
    )


def simulate_authorization(
    request: ExecutionRequest,
    policy: PolicyDecision,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate a caller-asserted envelope without creating operational authority."""
    decision = enforce(request, policy, manifest)
    return {
        "evaluated": True,
        "approved": decision.approved,
        "authoritative": False,
        "decision_source": "caller_asserted",
        "effect_grant_verified": False,
        "reasons": list(decision.reasons),
        "requires_verification": decision.requires_verification,
    }


def authorize_with_policy_evidence(
    root: Path,
    manifest: Mapping[str, object],
    request_data: Mapping[str, object],
) -> dict[str, object]:
    """Resolve a signed policy decision before validating the execution envelope."""
    try:
        capability_id = str(request_data["capability_id"])
        effects = tuple(map(str, request_data.get("effects", ("read_local",))))
        project_id = str(request_data["project_id"])
        actor_id = str(request_data["actor_id"])
        session_id = str(request_data["session_id"])
        execution_id = str(request_data["execution_id"])
        store_relative = Path(str(request_data["evidence_store"]))
        store = (root.resolve() / store_relative).resolve()
        if store_relative.is_absolute() or root.resolve() not in store.parents:
            raise ValueError("evidence_store must be product-relative")
        resolver = TrustedEvidenceResolver(
            store, root / "policies/effect-grant-trust.json"
        )
        resolved = resolver.resolve(
            str(request_data["policy_decision_ref"]),
            scope=EvidenceScope(
                project_id,
                capability_id,
                execution_id=execution_id,
                actor_id=actor_id,
                session_id=session_id,
            ),
            accepted_producers=set(map(str, request_data["accepted_policy_producers"])),
            max_age_seconds=int(request_data.get("max_age_seconds", 900)),
            expected_sha256=str(request_data["policy_decision_sha256"])
            if request_data.get("policy_decision_sha256")
            else None,
            required_type="policy_decision",
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        return {
            "evaluated": False,
            "approved": False,
            "authoritative": False,
            "decision_source": "request_validation",
            "effect_grant_verified": False,
            "reasons": [f"invalid authorization request: {error}"],
            "requires_verification": False,
        }
    if not resolved.verified:
        return {
            "evaluated": True,
            "approved": False,
            "authoritative": False,
            "decision_source": "resolved_signed_policy",
            "effect_grant_verified": False,
            "reasons": list(resolved.reasons),
            "requires_verification": bool(set(effects) & NON_READ_EFFECTS),
        }
    policy_result = resolved.record.get("result", {})
    if not isinstance(policy_result, dict):
        policy_result = {}
    approval_id = str(policy_result.get("approval_id", "")) or None
    authority = decide_authority(
        AuthorityRequest(
            executor=str(request_data.get("executor", "codex-host")),
            effects=effects,
            scopes=tuple(map(str, request_data.get("scopes", ()))),
            observed_only=bool(request_data.get("observed_only", False)),
            user_approval_id=approval_id,
            px_policy_decision_id=str(resolved.record.get("evidence_id", "")) or None,
            claim_id=str(request_data.get("claim_id", "")) or None,
            claim_status=str(request_data.get("claim_status", "")) or None,
            idempotency_key=str(request_data.get("idempotency_key", "")) or None,
            explicit_delegation=bool(request_data.get("explicit_delegation", False)),
            active_executors=tuple(
                map(str, request_data.get("active_executors", ()))
            ),
        )
    )
    if not authority.allowed:
        return {
            "evaluated": True,
            "approved": False,
            "authoritative": False,
            "decision_source": "resolved_signed_policy+operation_authority",
            "policy_evidence_id": resolved.record.get("evidence_id"),
            "effect_grant_verified": False,
            "executor_owner": authority.executor_owner,
            "reasons": list(authority.reasons),
            "requires_verification": bool(set(effects) & NON_READ_EFFECTS),
        }
    decision = enforce(
        ExecutionRequest(
            capability_id,
            effects,
            int(request_data.get("timeout_seconds", 30)),
            int(request_data.get("max_tool_calls", 0)),
            str(request_data.get("idempotency_key", "")) or None,
        ),
        PolicyDecision(
            policy_result.get("allowed") is True,
            tuple(map(str, policy_result.get("approved_effects", ()))),
            approval_id,
        ),
        manifest,
        effect_grant_path=Path(str(request_data["effect_grant_path"]))
        if request_data.get("effect_grant_path")
        else None,
        effect_signature_path=Path(str(request_data["effect_signature_path"]))
        if request_data.get("effect_signature_path")
        else None,
        effect_trust_policy_path=root / "policies/effect-grant-trust.json",
        project_id=project_id,
        session_id=session_id,
        adapter=str(request_data.get("adapter", "")),
        environment=str(request_data.get("environment", "")),
        writable_targets=tuple(
            Path(str(value)) for value in request_data.get("writable_targets", ())
        ),
        network_hosts=tuple(map(str, request_data.get("network_hosts", ()))),
        secret_refs=tuple(map(str, request_data.get("secret_refs", ()))),
    )
    return {
        "evaluated": True,
        "approved": decision.approved,
        "authoritative": decision.approved,
        "decision_source": "resolved_signed_policy",
        "policy_evidence_id": resolved.record.get("evidence_id"),
        "executor_owner": authority.executor_owner,
        "effect_grant_verified": decision.approved
        if set(effects) & NON_READ_EFFECTS
        else False,
        "reasons": list(decision.reasons),
        "requires_verification": decision.requires_verification,
    }
