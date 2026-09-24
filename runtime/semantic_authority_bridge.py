"""Read-only bridge to PX authority topology and operation-authority decisions."""
from __future__ import annotations
from pathlib import Path
from .authority_topology import resolve_effect_authority
from .operation_authority import AuthorityRequest, decide


def inspect_effect_authority(root: Path, effect_type: str) -> dict[str, object]:
    return resolve_effect_authority(root, effect_type)


def inspect_operation_authority(*, executor: str, effects: tuple[str, ...], scopes: tuple[str, ...] = (), observed_only: bool = True, active_executors: tuple[str, ...] = ()) -> dict[str, object]:
    decision = decide(AuthorityRequest(executor=executor, effects=effects, scopes=scopes, observed_only=observed_only, active_executors=active_executors))
    return {
        "allowed": decision.allowed,
        "executor_owner": decision.executor_owner,
        "reasons": list(decision.reasons),
        "requires_user_approval": decision.requires_user_approval,
        "requires_claim": decision.requires_claim,
    }
