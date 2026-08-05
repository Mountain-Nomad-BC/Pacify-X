"""Fail-closed project, session, lease, and transfer boundary controls.

These controls are deliberately side-effect free. They validate or produce plans;
callers must use separately authorized adapters to mutate repositories or state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Iterable, Mapping


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
PRIVATE_KINDS = frozenset(
    {"memory", "embedding", "prompt", "log", "source", "agent_state"}
)
GLOBAL_ALLOWED_KINDS = frozenset({"constitution", "policy", "sanitized_capability"})


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopeEnvelope:
    workspace_id: str
    project_id: str
    agent_id: str
    session_id: str
    workstream_id: str
    lease_id: str
    intent_id: str
    correlation_id: str

    def errors(self) -> tuple[str, ...]:
        missing = []
        for name, value in asdict(self).items():
            if not value or not ID_PATTERN.fullmatch(value):
                missing.append(f"invalid_{name}")
        return tuple(missing)


@dataclass(frozen=True, slots=True)
class ContextObject:
    source_id: str
    namespace_type: str
    project_id: str | None
    kind: str
    classification: str
    provenance: str
    transfer_id: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    decision: str
    reasons: tuple[str, ...]
    allowed_source_ids: tuple[str, ...]
    denied_source_ids: tuple[str, ...]
    receipt_hash: str


def authorize_context(
    scope: ScopeEnvelope,
    objects: Iterable[ContextObject],
    *,
    approved_transfer_ids: Iterable[str] = (),
) -> BoundaryDecision:
    """Authorize minimum context for exactly one project namespace."""
    scope_errors = scope.errors()
    if scope_errors:
        return BoundaryDecision("deny", scope_errors, (), (), _stable(scope_errors))
    approved = set(approved_transfer_ids)
    allowed: list[str] = []
    denied: list[str] = []
    reasons: set[str] = set()
    for item in objects:
        if not item.source_id or not item.provenance or not item.classification:
            denied.append(item.source_id or "untagged")
            reasons.add("untagged_or_unprovenanced_context")
        elif item.namespace_type == "project" and item.project_id == scope.project_id:
            allowed.append(item.source_id)
        elif item.namespace_type == "global" and item.kind in GLOBAL_ALLOWED_KINDS:
            allowed.append(item.source_id)
        elif (
            item.namespace_type == "transfer"
            and item.transfer_id
            and item.transfer_id in approved
            and item.project_id == scope.project_id
        ):
            allowed.append(item.source_id)
        else:
            denied.append(item.source_id)
            reasons.add("foreign_or_unapproved_context")
        if item.namespace_type == "global" and item.kind in PRIVATE_KINDS:
            if item.source_id in allowed:
                allowed.remove(item.source_id)
            if item.source_id not in denied:
                denied.append(item.source_id)
            reasons.add("private_payload_in_global_namespace")
    decision = "allow" if not denied else "deny"
    payload = {
        "scope": asdict(scope),
        "allowed": sorted(allowed),
        "denied": sorted(denied),
        "reasons": sorted(reasons),
    }
    return BoundaryDecision(
        decision,
        tuple(sorted(reasons)),
        tuple(sorted(allowed)),
        tuple(sorted(denied)),
        _stable(payload),
    )


@dataclass(frozen=True, slots=True)
class LeaseRequest:
    scope: ScopeEnvelope
    writable: bool
    expires_at: datetime
    tools: tuple[str, ...]
    roots: tuple[str, ...]
    side_effect_budget: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class LeaseDecision:
    decision: str
    reasons: tuple[str, ...]
    lease_fingerprint: str


def authorize_lease(
    request: LeaseRequest, existing: Iterable[LeaseRequest] = ()
) -> LeaseDecision:
    reasons = list(request.scope.errors())
    now = datetime.now(timezone.utc)
    expiry = request.expires_at
    if expiry.tzinfo is None or expiry <= now:
        reasons.append("lease_not_future_expiring")
    if not request.tools or not request.roots:
        reasons.append("lease_scope_incomplete")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in request.side_effect_budget.values()
    ):
        reasons.append("invalid_side_effect_budget")
    for lease in existing:
        if (
            request.writable
            and lease.writable
            and lease.scope.session_id == request.scope.session_id
            and lease.scope.project_id != request.scope.project_id
            and lease.expires_at > now
        ):
            reasons.append("session_has_foreign_writable_lease")
    fingerprint = _stable(
        {
            "scope": asdict(request.scope),
            "writable": request.writable,
            "expires_at": request.expires_at.isoformat(),
            "tools": sorted(request.tools),
            "roots": sorted(request.roots),
            "budget": dict(request.side_effect_budget),
        }
    )
    return LeaseDecision(
        "allow" if not reasons else "deny", tuple(sorted(set(reasons))), fingerprint
    )


@dataclass(frozen=True, slots=True)
class SwitchEvidence:
    checkpoint_created: bool
    locks_released: bool
    handles_closed: bool
    context_cache_flushed: bool
    embedding_cache_flushed: bool
    tool_roots_rebound: bool
    old_lease_revoked: bool
    old_project_access_denied: bool


def validate_project_switch(
    old: ScopeEnvelope, new: ScopeEnvelope, evidence: SwitchEvidence
) -> BoundaryDecision:
    reasons = list(old.errors()) + list(new.errors())
    if old.workspace_id != new.workspace_id:
        reasons.append("workspace_change_not_project_switch")
    if old.project_id == new.project_id:
        reasons.append("project_identity_unchanged")
    for name, passed in asdict(evidence).items():
        if not passed:
            reasons.append(f"switch_check_failed:{name}")
    decision = "allow" if not reasons else "deny"
    payload = {
        "old": asdict(old),
        "new": asdict(new),
        "evidence": asdict(evidence),
        "reasons": sorted(reasons),
    }
    return BoundaryDecision(
        decision, tuple(sorted(set(reasons))), (), (), _stable(payload)
    )


@dataclass(frozen=True, slots=True)
class TransferPackage:
    transfer_id: str
    source_project_id: str
    destination_project_id: str
    content_kind: str
    provenance: tuple[str, ...]
    license: str
    assumptions: tuple[str, ...]
    tests: tuple[str, ...]
    sanitization_passed: bool
    human_approved: bool
    destination_owned: bool
    includes_private_memory: bool = False


def authorize_transfer(package: TransferPackage) -> BoundaryDecision:
    reasons = []
    if not ID_PATTERN.fullmatch(package.transfer_id):
        reasons.append("invalid_transfer_id")
    if package.source_project_id == package.destination_project_id:
        reasons.append("source_equals_destination")
    if not package.provenance or not package.license or not package.tests:
        reasons.append("transfer_evidence_incomplete")
    if not package.sanitization_passed:
        reasons.append("sanitization_not_passed")
    if not package.human_approved:
        reasons.append("approval_missing")
    if not package.destination_owned:
        reasons.append("destination_ownership_missing")
    if package.includes_private_memory:
        reasons.append("private_memory_transfer_forbidden")
    payload = asdict(package)
    return BoundaryDecision(
        "allow" if not reasons else "deny",
        tuple(reasons),
        (package.transfer_id,) if not reasons else (),
        () if not reasons else (package.transfer_id,),
        _stable(payload),
    )
