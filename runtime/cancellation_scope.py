"""Canonical cancellation-scope owner (punch card EXE-004).

One scope groups a root execution and every descendant that must be cancelled,
paused, interrupted or deadline-expired together. This owner is deliberately
small: it holds only the *propagation* decision for a scope, not the durable run
state (which belongs to ``runtime.studio_run_control``) and not the process
teardown (which belongs to the process supervisor).

A scope is never a second run-control authority. ``resolve_control`` maps the
requested control on any member onto the control that every other live member of
the same scope must adopt, so a caller cannot cancel a parent while leaving an
orphaned child running, nor resume a child while its root stays cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

SCHEMA_VERSION = "px.cancellation-scope/1.0"

#: Controls that propagate downward through a scope, and the terminal state each
#: member adopts. A ``pause_requested`` member pauses; ``cancel_requested`` and
#: ``interrupted`` members cancel; an expired deadline cancels.
CONTROL_STATES = ("running", "pause_requested", "paused", "cancel_requested", "cancelled", "interrupted")
_PROPAGATED_CONTROL = {
    "cancel_requested": "cancelled",
    "cancelled": "cancelled",
    "pause_requested": "paused",
    "paused": "paused",
    "interrupted": "cancelled",
}
#: A member that is already terminal in a stronger sense must not be resurrected.
_TERMINAL = frozenset({"cancelled", "failed", "succeeded"})


class CancellationScopeError(ValueError):
    """Raised when a scope or control request is invalid."""


@dataclass(frozen=True, slots=True)
class CancellationScope:
    """One cancellation scope and its membership.

    ``root_execution_id`` is the scope's anchor. Every member must declare the
    same ``scope_id``; membership is recorded so propagation can enumerate the
    exact set of live members without scanning unrelated runs.
    """

    scope_id: str
    project_id: str
    root_execution_id: str
    members: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("scope_id", "project_id", "root_execution_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise CancellationScopeError(f"{name} must be bounded nonempty text")
        if type(self.members) is not tuple or not self.members:
            raise CancellationScopeError("scope requires at least one member")
        if len(set(self.members)) != len(self.members):
            raise CancellationScopeError("scope members must be unique")
        if any(type(member) is not str or not member.strip() or len(member) > 512 for member in self.members):
            raise CancellationScopeError("scope member identities must be bounded nonempty text")
        if self.root_execution_id not in self.members:
            raise CancellationScopeError("scope root must be one of its members")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "scope_id": self.scope_id,
            "project_id": self.project_id,
            "root_execution_id": self.root_execution_id,
            "members": list(self.members),
            "member_count": len(self.members),
            "authority_granted": False,
        }


def build_scope(scope_id: str, project_id: str, root_execution_id: str, members) -> CancellationScope:
    """Build a scope from an exact member set, always including the root."""
    ids = list(dict.fromkeys([root_execution_id, *members]))
    return CancellationScope(scope_id, project_id, root_execution_id, tuple(ids))


def resolve_control(scope: CancellationScope, states: Mapping[str, str], *, now_utc: str | None = None,
                    deadline_utc: str | None = None) -> dict[str, object]:
    """Resolve the control every live member of a scope must adopt.

    ``states`` maps each member execution id to its current durable state. The
    result is the strongest requested control across the scope:

    * any member ``cancel_requested``/``interrupted`` -> whole scope cancels;
    * else any member ``pause_requested`` -> whole scope pauses;
    * else an expired ``deadline_utc`` -> whole scope cancels;
    * else no change.

    A member already ``cancelled``/``failed``/``succeeded`` is reported as
    terminal and is never asked to adopt a weaker control.
    """
    if type(scope) is not CancellationScope:
        raise CancellationScopeError("canonical cancellation scope required")
    if not isinstance(states, Mapping) or set(states) != set(scope.members):
        raise CancellationScopeError("control resolution requires the exact scope membership")
    for member, state in states.items():
        if state not in CONTROL_STATES:
            raise CancellationScopeError(f"unknown control state for {member}: {state}")

    requested: str | None = None
    for member in scope.members:
        state = states[member]
        if state in {"cancel_requested", "interrupted"}:
            requested = "cancelled"
            break
    if requested is None and any(states[member] == "pause_requested" for member in scope.members):
        requested = "paused"
    expired = False
    if requested is None and deadline_utc is not None:
        moment = now_utc or datetime.now(timezone.utc).isoformat()
        if _parse(moment) >= _parse(deadline_utc):
            requested = "cancelled"
            expired = True

    live = [member for member in scope.members if states[member] not in _TERMINAL]
    adopt = {}
    for member in live:
        if requested is None:
            continue
        # A member already at the requested terminal state needs no transition.
        if states[member] == requested:
            continue
        adopt[member] = requested
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": scope.scope_id,
        "requested_control": requested,
        "deadline_expired": expired,
        "terminal_members": sorted(member for member in scope.members if states[member] in _TERMINAL),
        "adopt": adopt,
        "authority_granted": False,
    }


def _parse(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise CancellationScopeError("scope timestamps must be ISO-8601") from error
    if moment.tzinfo is None:
        raise CancellationScopeError("scope timestamps require an offset")
    return moment.astimezone(timezone.utc)