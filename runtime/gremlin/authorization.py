"""Authority and justification resolution.

Before remediation, Gremlin resolves whether an observed effect is authorized. A
legitimate event survives because a valid capability lease/allowance exists, not
because the agent talked the nanny into it. The workload cannot supply its own
authorization: the resolver consumes external, policy-bound inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Iterable, Mapping

from ..json_io import bounded_canonical_json_bytes
from .events import DECISION_CATEGORIES, EffectEvent
from .policy import PolicyProfile

SCHEMA_VERSION = "px.gremlin-authorization/1.0"

#: Bounded clock skew allowed when comparing lease validity instants against a
#: trusted UTC clock (never applied to revocation, which is authoritative immediately).
LEASE_TIME_SKEW = timedelta(seconds=30)

#: Which lease budget dimensions apply to which capability: a zero budget in an
#: applicable dimension denies the effect (contract default: yes).
BUDGET_DIMENSION_FIELDS = (("max_connections", "connections"), ("max_requests", "requests"), ("max_bytes", "bytes"))
APPLICABLE_BUDGET_DIMENSIONS = {
    "outbound_network": ("connections", "requests"),
    "external_api": ("connections", "requests"),
    "raw_socket": ("connections", "requests"),
    "dns": ("requests",),
}


def trusted_utc(now: datetime | None = None) -> datetime:
    """The single trusted UTC clock used by lease/intervention/admin decisions."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("trusted time must be timezone-aware UTC")
    return moment.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def lease_denial_reason(
    lease: CapabilityLease | None,
    event: EffectEvent,
    *,
    capability: str,
    now: datetime,
    revoked_lease_ids: Iterable[str] = frozenset(),
    current_policy_revision: str | None = None,
    budget_ledger: Mapping[str, Mapping[str, int]] | None = None,
) -> str | None:
    """One trusted lease resolver shared by every effect/network entry point (G01).

    Returns ``None`` when the lease authorizes the observed effect, otherwise a
    bounded denial reason code. Validates, in order: existence, exact execution
    ownership (never the map key), capability, target scope, effective interval,
    revocation, policy revision and remaining applicable budgets. Deny by default.
    """
    if lease is None:
        return "lease_missing"
    if lease.agent_execution_id != event.execution_id:
        return "lease_foreign_owner"
    if lease.capability != capability:
        return "lease_capability_mismatch"
    if lease.destination_scope and event.target not in lease.destination_scope:
        return "lease_target_out_of_scope"
    valid_from = _parse_utc(lease.valid_from_utc)
    valid_until = _parse_utc(lease.valid_until_utc)
    if valid_from is None or valid_until is None or valid_until <= valid_from:
        return "lease_interval_invalid"
    if now + LEASE_TIME_SKEW < valid_from:
        return "lease_not_yet_valid"
    if now - LEASE_TIME_SKEW > valid_until:
        return "lease_expired"
    if lease.lease_id in set(revoked_lease_ids):
        return "lease_revoked"
    if current_policy_revision is not None and lease.policy_revision != current_policy_revision:
        return "lease_stale_policy_revision"
    ledger = (budget_ledger or {}).get(lease.lease_id, {})
    # Zero budget for an *applicable* dimension denies the effect; unrelated
    # zero dimensions never block an otherwise valid lease (contract decision).
    applicable_dimensions = APPLICABLE_BUDGET_DIMENSIONS.get(capability, ("requests",))
    for dimension in applicable_dimensions:
        attribute = next(
            (name for name, label in BUDGET_DIMENSION_FIELDS if label == dimension), None
        )
        if attribute is None:
            continue
        limit = int(getattr(lease, attribute))
        if limit == 0:
            return f"lease_zero_budget:{dimension}"
        remaining = limit - int(ledger.get(dimension, 0))
        if remaining <= 0:
            return f"lease_budget_exhausted:{dimension}"
    return None


@dataclass(frozen=True, slots=True)
class CapabilityLease:
    """A bounded capability lease (plan section 30)."""

    lease_id: str
    agent_execution_id: str
    capability: str
    destination_scope: tuple[str, ...]
    valid_from_utc: str
    valid_until_utc: str
    max_connections: int
    max_bytes: int
    max_requests: int
    allowed_protocols: tuple[str, ...]
    policy_revision: str
    revocable: bool = True

    def __post_init__(self) -> None:
        if not self.lease_id.strip():
            raise ValueError("capability lease requires an identity")
        if self.max_connections < 0 or self.max_bytes < 0 or self.max_requests < 0:
            raise ValueError("capability lease budgets must be non-negative")


@dataclass(frozen=True, slots=True)
class AuthorizationResolution:
    event_id: str
    capability: str
    requested_target: str
    policy_result: str
    existing_allowance: bool
    allowance_id: str | None
    justification_required: bool
    justification_received: bool
    justification_validated: bool
    final_decision: str
    decision_category: str

    def __post_init__(self) -> None:
        if self.final_decision not in {"allow", "deny", "remediate", "terminate"}:
            raise ValueError("invalid authorization decision")
        if self.decision_category not in DECISION_CATEGORIES:
            raise ValueError("invalid decision category")

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def resolve_authorization(
    event: EffectEvent,
    *,
    profile: PolicyProfile,
    leases: Mapping[str, CapabilityLease] | None = None,
    allowances: Mapping[str, str] | None = None,
    expected_effects: frozenset[str] = frozenset(),
    justification: str | None = None,
    now: datetime | None = None,
    revoked_lease_ids: Iterable[str] = frozenset(),
    current_policy_revision: str | None = None,
    budget_ledger: Mapping[str, Mapping[str, int]] | None = None,
) -> AuthorizationResolution:
    """Resolve the authorization for an observed effect.

    ``expected_effects`` is the set of effect types the policy profile declares as
    expected for this execution. ``allowances`` maps an effect/target key to an
    allowance id that was granted *externally* (never by the workload).
    """
    leases = leases or {}
    allowances = allowances or {}
    rule = profile.rule_for(event.effect_type)
    capability = event.effect_type
    expected = event.effect_type in expected_effects

    # Containment-control interference is never authorized and never remediated.
    if event.effect_type == "containment_control_interference":
        return AuthorizationResolution(
            event_id=event.event_id,
            capability=capability,
            requested_target=event.target,
            policy_result="denied",
            existing_allowance=False,
            allowance_id=None,
            justification_required=False,
            justification_received=False,
            justification_validated=False,
            final_decision="terminate",
            decision_category="containment_control_interference",
        )

    # Observe-only profiles never authorize containment decisions.
    if not profile.real_containment:
        return AuthorizationResolution(
            event_id=event.event_id,
            capability=capability,
            requested_target=event.target,
            policy_result="observed",
            existing_allowance=False,
            allowance_id=None,
            justification_required=False,
            justification_received=False,
            justification_validated=False,
            final_decision="allow",
            decision_category="unknown_unresolved",
        )

    allowance_id = allowances.get(f"{event.effect_type}:{event.target}")
    lease = leases.get(event.execution_id)
    moment = trusted_utc(now)
    denial_reason = (
        lease_denial_reason(
            lease,
            event,
            capability=capability,
            now=moment,
            revoked_lease_ids=revoked_lease_ids,
            current_policy_revision=current_policy_revision,
            budget_ledger=budget_ledger,
        )
        if lease is not None
        else None
    )
    lease_valid = lease is not None and denial_reason is None
    authorized = allowance_id is not None or (rule is not None and rule.allow_if_capability_lease_valid and lease_valid)
    if rule is not None and not rule.allow_if_capability_lease_valid:
        authorized = allowance_id is not None

    if authorized:
        category = "expected_authorized" if expected else "unexpected_authorized"
        decision = "allow"
    else:
        category = "expected_unauthorized" if expected else "unexpected_unauthorized"
        if rule is None:
            decision = "terminate"
        elif rule.remediation_attempts == 0:
            decision = "terminate"
        else:
            decision = "remediate"
    resolution = AuthorizationResolution(
        event_id=event.event_id,
        capability=capability,
        requested_target=event.target,
        policy_result="authorized" if authorized else "denied",
        existing_allowance=allowance_id is not None,
        allowance_id=allowance_id,
        justification_required=not authorized,
        justification_received=justification is not None,
        justification_validated=False,
        final_decision=decision,
        decision_category=category,
    )
    return resolution