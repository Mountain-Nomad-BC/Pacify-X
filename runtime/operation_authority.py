"""Compose operation authority without allowing one control plane to impersonate another.

This module decides *who may own* an operation.  Capability admission, signed effect
grants, policy evidence, and executor-specific validation remain separate gates.
"""

from __future__ import annotations

from dataclasses import dataclass


READ_EFFECTS = frozenset({"read", "read_local", "workspace-read", "observe", "host-ui"})
WRITE_EFFECTS = frozenset(
    {
        "write_workspace",
        "workspace-write",
        "filesystem-write",
        "configuration-write",
        "clipboard-write",
        "install_tool",
        "network",
        "run_service",
        "process",
        "secret_access",
        "migration",
        "destructive",
        "destructive-filesystem",
    }
)
EXECUTORS = frozenset({"codex-host", "px-owned-executor"})


@dataclass(frozen=True)
class AuthorityRequest:
    executor: str
    effects: tuple[str, ...]
    scopes: tuple[str, ...] = ()
    observed_only: bool = False
    user_approval_id: str | None = None
    px_policy_decision_id: str | None = None
    claim_id: str | None = None
    claim_status: str | None = None
    idempotency_key: str | None = None
    explicit_delegation: bool = False
    active_executors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    executor_owner: str | None
    reasons: tuple[str, ...]
    requires_user_approval: bool
    requires_claim: bool


def decide(request: AuthorityRequest) -> AuthorityDecision:
    """Fail closed unless every independent authority supplies its own evidence."""
    reasons: list[str] = []
    effects = set(request.effects)
    non_read = bool(effects - READ_EFFECTS)
    workspace_write = bool(
        effects
        & {
            "write_workspace",
            "workspace-write",
            "filesystem-write",
            "configuration-write",
            "destructive",
            "destructive-filesystem",
        }
    )

    if request.executor not in EXECUTORS:
        reasons.append("executor is not an admitted operation owner")
    unknown_effects = effects - READ_EFFECTS - WRITE_EFFECTS
    if unknown_effects:
        reasons.append("request contains unknown effects")
    if request.observed_only and non_read:
        reasons.append("observation cannot authorize or claim a non-read effect")
    if non_read and not request.user_approval_id:
        reasons.append("non-read effects require current user approval")
    if non_read and not request.px_policy_decision_id:
        reasons.append("non-read effects require a PX policy decision")
    if non_read and not request.idempotency_key:
        reasons.append("non-read effects require an idempotency key")
    if workspace_write and not (
        request.claim_id and request.claim_status == "active"
    ):
        reasons.append("workspace mutation requires an active repository claim")
    if request.executor == "px-owned-executor" and not request.explicit_delegation:
        reasons.append("PX-owned execution requires explicit delegation")

    active = tuple(dict.fromkeys(request.active_executors))
    if any(owner not in EXECUTORS for owner in active):
        reasons.append("active executor set contains an unadmitted owner")
    other_owners = {owner for owner in active if owner != request.executor}
    if other_owners:
        reasons.append("overlapping active executor authority is forbidden")
    if request.executor == "px-owned-executor" and "codex-host" in active:
        reasons.append("PX must not start a nested executor inside the Codex host")

    return AuthorityDecision(
        allowed=not reasons,
        executor_owner=request.executor if not reasons else None,
        reasons=tuple(dict.fromkeys(reasons)),
        requires_user_approval=non_read,
        requires_claim=workspace_write,
    )


def authority_roles() -> dict[str, dict[str, object]]:
    """Return the stable role boundary used by diagnostics and user interfaces."""
    return {
        "codex-host": {
            "may_execute": True,
            "owns_user_approval_surface": True,
            "may_issue_px_policy": False,
            "may_issue_repository_claim": False,
        },
        "px-control-plane": {
            "may_execute": False,
            "owns_user_approval_surface": False,
            "may_issue_px_policy": True,
            "may_issue_repository_claim": False,
        },
        "repository-claim": {
            "may_execute": False,
            "owns_user_approval_surface": False,
            "may_issue_px_policy": False,
            "may_issue_repository_claim": True,
        },
        "extension": {
            "may_execute": False,
            "owns_user_approval_surface": False,
            "presentation_and_observation_only": True,
        },
    }
