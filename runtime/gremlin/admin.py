"""Protected administrative controls and GN admin audit events.

Sensitive containment controls require strong human authentication and are
operation-scoped and short-lived. There is no single ``enabled=false`` switch
(GN-INV-009): each operation has its own required auth strength and emits its own
audit event. The workload can never hold an admin authorization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from ..json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.gremlin-admin/1.0"

#: Maximum lifetime of one admin authorization and tolerated issuance skew.
ADMIN_MAX_LIFETIME = timedelta(minutes=15)
ADMIN_ISSUANCE_SKEW = timedelta(seconds=60)

# Separate operations (plan section 16). No single Boolean control surface.
ADMIN_OPERATIONS = frozenset(
    {
        "pause_new_protected_runs",
        "disable_specific_rule",
        "modify_policy_bundle",
        "disable_specific_observer",
        "suspend_intervention",
        "remove_kill_authority",
        "disable_network_enforcement",
        "disable_all_gn",
    }
)

AUTH_FACTORS = frozenset({"passkey", "mfa", "hardware_key", "offline_recovery_token"})

#: The action an authorization permits is bound to its operation (G07): a
#: signature over a mismatched operation/action pair is refused.
OPERATION_ACTIONS = {
    "pause_new_protected_runs": frozenset({"pause"}),
    "disable_specific_rule": frozenset({"disable"}),
    "modify_policy_bundle": frozenset({"modify"}),
    "disable_specific_observer": frozenset({"disable"}),
    "suspend_intervention": frozenset({"suspend"}),
    "remove_kill_authority": frozenset({"remove"}),
    "disable_network_enforcement": frozenset({"disable"}),
    "disable_all_gn": frozenset({"disable"}),
}

# Operations that reduce containment require stronger authentication.
HIGH_IMPACT_OPERATIONS = frozenset(
    {
        "remove_kill_authority",
        "disable_network_enforcement",
        "disable_all_gn",
        "modify_policy_bundle",
    }
)


def admin_signature_body(authorization: "AdminAuthorization") -> dict[str, object]:
    """The canonical body the trusted host signs and later verifies."""
    return {
        "schema_version": SCHEMA_VERSION,
        "principal_id": authorization.principal_id,
        "auth_strength": authorization.auth_strength,
        "operation": authorization.operation,
        "target": authorization.target,
        "permitted_action": authorization.permitted_action,
        "issued_at_utc": authorization.issued_at_utc,
        "expires_at_utc": authorization.expires_at_utc,
        "nonce": authorization.nonce,
        "approval_id": authorization.approval_id,
    }


def sign_admin_authorization(authorization: AdminAuthorization, signing_key: bytes) -> AdminAuthorization:
    """Return the authorization with a trusted-host HMAC signature over its body."""
    digest = hmac.new(signing_key, bounded_canonical_json_bytes(admin_signature_body(authorization), max_bytes=65536), hashlib.sha256).hexdigest()
    return replace(authorization, signature=digest)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("admin authorization times must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class AdminAuthorizationError(ValueError):
    """Raised when a GN admin change lacks adequate authentication (fail closed)."""


@dataclass(frozen=True, slots=True)
class AdminAuthorization:
    principal_id: str
    auth_strength: str
    operation: str
    target: str
    permitted_action: str
    issued_at_utc: str
    expires_at_utc: str
    nonce: str
    approval_id: str
    signature: str

    def __post_init__(self) -> None:
        if self.auth_strength not in AUTH_FACTORS:
            raise ValueError("unknown admin auth factor")
        if self.operation not in ADMIN_OPERATIONS:
            raise ValueError(f"unknown admin operation {self.operation!r}")
        for name in ("principal_id", "target", "permitted_action", "nonce", "approval_id", "signature"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"admin authorization requires a bounded {name}")

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment >= datetime.fromisoformat(self.expires_at_utc.replace("Z", "+00:00"))

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True, slots=True)
class AdminAuditEvent:
    actor: str
    auth_factor: str
    operation: str
    target: str
    prior_state: str
    new_state: str
    reason: str
    timestamp_utc: str
    authorization_id: str
    session_id: str
    result: str

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


class ProtectedAdminControl:
    """Applies an operation-scoped, authenticated containment control change.

    A change that reduces containment is especially visible: it requires a
    high-impact auth factor (passkey/mfa/hardware_key) and produces an audit event
    whether it is authorized or refused.
    """

    def __init__(self, *, signing_key: bytes | None = None) -> None:
        self.audit_log: list[AdminAuditEvent] = []
        #: Durable nonce replay store (G07): one application per nonce, ever.
        self._used_nonces: set[str] = set()
        if signing_key is None or not signing_key:
            raise AdminAuthorizationError(
                "protected admin controls require a trusted-host signing key (fail closed)"
            )
        self._signing_key = bytes(signing_key)

    def apply(
        self,
        authorization: AdminAuthorization,
        *,
        target_state: str,
        reason: str,
        now: datetime | None = None,
    ) -> AdminAuditEvent:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise AdminAuthorizationError("trusted time must be timezone-aware UTC")
        moment = moment.astimezone(timezone.utc)
        prior_state = "enabled"
        result = "applied"
        try:
            if authorization.operation not in ADMIN_OPERATIONS:
                raise AdminAuthorizationError("unknown admin operation")
            if authorization.permitted_action not in OPERATION_ACTIONS.get(authorization.operation, frozenset()):
                raise AdminAuthorizationError(
                    "permitted action does not bind the operation (fail closed)"
                )
            issued = parse_utc(authorization.issued_at_utc)
            expires = parse_utc(authorization.expires_at_utc)
            if expires <= issued:
                raise AdminAuthorizationError("admin authorization expires before issuance")
            if expires - issued > ADMIN_MAX_LIFETIME:
                raise AdminAuthorizationError("admin authorization exceeds its bounded lifetime")
            if issued > moment + ADMIN_ISSUANCE_SKEW:
                raise AdminAuthorizationError("admin authorization issued in the future (fail closed)")
            if moment >= expires:
                raise AdminAuthorizationError("admin authorization has expired")
            if (
                authorization.operation in HIGH_IMPACT_OPERATIONS
                and authorization.auth_strength not in {"passkey", "mfa", "hardware_key"}
            ):
                raise AdminAuthorizationError("high-impact operation requires strong authentication")
            if authorization.nonce in self._used_nonces:
                raise AdminAuthorizationError("admin authorization nonce was already used (replay refused)")
            expected = hmac.new(
                self._signing_key,
                bounded_canonical_json_bytes(admin_signature_body(authorization), max_bytes=65536),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(str(authorization.signature), expected):
                raise AdminAuthorizationError("admin authorization signature is not authentic (fail closed)")
        except AdminAuthorizationError:
            result = "refused"
            event = AdminAuditEvent(
                actor=authorization.principal_id,
                auth_factor=authorization.auth_strength,
                operation=authorization.operation,
                target=authorization.target,
                prior_state=prior_state,
                new_state=prior_state,
                reason=reason,
                timestamp_utc=moment.isoformat(),
                authorization_id=authorization.approval_id,
                session_id=authorization.nonce,
                result=result,
            )
            self.audit_log.append(event)
            raise
        event = AdminAuditEvent(
            actor=authorization.principal_id,
            auth_factor=authorization.auth_strength,
            operation=authorization.operation,
            target=authorization.target,
            prior_state=prior_state,
            new_state=target_state,
            reason=reason,
            timestamp_utc=moment.isoformat(),
            authorization_id=authorization.approval_id,
            session_id=authorization.nonce,
            result=result,
        )
        self.audit_log.append(event)
        # The nonce is consumed only on a successful, authenticated application:
        # refused claims are refused again, and a replay after success is denied.
        self._used_nonces.add(authorization.nonce)
        return event

    def audit_digest(self) -> str:
        body = {"events": [event.as_dict() for event in self.audit_log]}
        return hashlib.sha256(bounded_canonical_json_bytes(body, max_bytes=1_048_576)).hexdigest()