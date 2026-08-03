"""Fail-closed execution-contract validation.

This module authorizes an execution envelope. It does not execute the action.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .effect_grants import validate_effect_grant

NON_READ_EFFECTS = {
    "write_workspace", "install_tool", "network", "run_service",
    "secret_access", "migration", "destructive",
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
        if not all((effect_grant_path, effect_signature_path, effect_trust_policy_path, project_id, session_id, adapter, environment)):
            reasons.append("non-read effects require an enforced runtime effect grant")
        else:
            try:
                grant = json.loads(effect_grant_path.read_text(encoding="utf-8"))
                validation = validate_effect_grant(
                    grant, signature_path=effect_signature_path, trust_policy_path=effect_trust_policy_path,
                    capability_id=request.capability_id, requested_effects=request.effects,
                    adapter=adapter, environment=environment, project_id=project_id, session_id=session_id,
                    writable_targets=writable_targets, network_hosts=network_hosts, secret_refs=secret_refs,
                    destructive="destructive" in requested,
                )
                reasons.extend(validation["errors"])
            except (OSError, ValueError, json.JSONDecodeError) as error:
                reasons.append(f"effect grant validation failed: {type(error).__name__}: {error}")
    return ContractDecision(not reasons, tuple(reasons), bool(requested & NON_READ_EFFECTS))
