"""Fail-closed authorization for Wave-3 read-only cross-project operations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .semantic_integration_types import QueryAuthorization

READ_ONLY_CROSS_PROJECT = frozenset({
    "semantic.project.summary", "semantic.symbol.find", "semantic.symbol.overview",
    "semantic.reference.find", "semantic.diagnostics.file", "semantic.cross_project.query",
    "semantic.project_map.query", "semantic.knowledge.fuse", "semantic.authority.inspect",
    "semantic.memory.integrity", "semantic.model.context",
})

@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reasons: tuple[str, ...]

def authorize(auth: QueryAuthorization, project_id: str, operation: str, *, now: datetime | None = None) -> AuthorizationDecision:
    reasons: list[str] = []
    if not auth.token_id.strip() or not auth.actor_id.strip():
        reasons.append("authorization_identity_missing")
    if auth.expired(now):
        reasons.append("authorization_expired")
    if project_id not in auth.project_ids:
        reasons.append("project_not_authorized")
    if operation not in auth.operations:
        reasons.append("operation_not_authorized")
    if operation not in READ_ONLY_CROSS_PROJECT:
        reasons.append("cross_project_operation_not_read_only")
    return AuthorizationDecision(not reasons, tuple(dict.fromkeys(reasons)))

def require_authorized(auth: QueryAuthorization, project_id: str, operation: str, *, now: datetime | None = None) -> None:
    decision = authorize(auth, project_id, operation, now=now)
    if not decision.allowed:
        raise PermissionError("; ".join(decision.reasons))
