"""Independent, operation-scoped human recovery authorization.

This module owns challenge validation and policy decisions. FIDO2, Windows
Hello, Entra, or other authenticators implement ``RecoveryApprovalVerifier``;
this module does not pretend an absent authenticator is a valid approval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from ..archive_io import reject_path_links
from ..engineering_os_paths import control_root
from ..event_ledger import (
    _append_chained_event_locked,
    validate_event_ledger,
)
from ..file_lock import FileLock


CHALLENGE_SCHEMA_VERSION = "px.gremlin-recovery-challenge/1.0"
APPROVAL_SCHEMA_VERSION = "px.gremlin-recovery-approval/1.0"
DECISION_SCHEMA_VERSION = "px.gremlin-recovery-decision/1.0"
EVENT_SCHEMA_VERSION = "px.gremlin-recovery-event/1.0"
REPLAY_LEDGER_SCHEMA_VERSION = "px.gremlin-recovery-replay-ledger/1.0"

_AUTH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_APPROVAL_FACTORS = frozenset(
    {"passkey", "mfa", "hardware_key", "offline_recovery_token"}
)
_MIN_TTL_SECONDS = 5
_MAX_TTL_SECONDS = 900
_CLOCK_SKEW_SECONDS = 30
_MAX_REPLAY_EVENTS = 50_000
_REPLAY_EVENT_KINDS = frozenset({"approval_consumed", "approval_revoked"})


class RecoveryAuthorizationError(RuntimeError):
    """Recovery authorization failed and protected execution must remain stopped."""


def _identifier(value: str, label: str) -> str:
    if type(value) is not str or _AUTH_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded identifier")
    return value


def _timestamp(value: str, label: str) -> datetime:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _canonical_digest(value: Mapping[str, object]) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class RecoveryChallenge:
    challenge_id: str
    requesting_authority_id: str
    protected_execution_id: str
    operation: str
    reason_code: str
    nonce: str
    issued_at_utc: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "challenge_id",
            "requesting_authority_id",
            "protected_execution_id",
            "operation",
            "reason_code",
            "nonce",
        ):
            if name == "nonce":
                if type(self.nonce) is not str or _NONCE.fullmatch(self.nonce) is None:
                    raise ValueError("nonce must be bounded URL-safe random text")
            else:
                _identifier(getattr(self, name), name)
        issued = _timestamp(self.issued_at_utc, "issued_at_utc")
        expires = _timestamp(self.expires_at_utc, "expires_at_utc")
        if expires <= issued or expires - issued > timedelta(
            seconds=_MAX_TTL_SECONDS
        ):
            raise ValueError("recovery challenge expiry is invalid")

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": CHALLENGE_SCHEMA_VERSION, **asdict(self)}

    @property
    def challenge_sha256(self) -> str:
        return _canonical_digest(self.as_dict())


@dataclass(frozen=True, slots=True)
class RecoveryApproval:
    approval_id: str
    challenge_sha256: str
    principal_id: str
    auth_factor: str
    granted: bool
    issued_at_utc: str
    expires_at_utc: str
    signature: str

    def __post_init__(self) -> None:
        _identifier(self.approval_id, "approval_id")
        _identifier(self.principal_id, "principal_id")
        if _SHA256.fullmatch(self.challenge_sha256) is None:
            raise ValueError("approval challenge digest must be lowercase SHA-256")
        if (
            type(self.auth_factor) is not str
            or self.auth_factor not in _APPROVAL_FACTORS
        ):
            raise ValueError("recovery approval requires a supported strong factor")
        if type(self.granted) is not bool:
            raise ValueError("approval granted must be boolean")
        if (
            type(self.signature) is not str
            or not self.signature.strip()
            or len(self.signature) > 4096
        ):
            raise ValueError("recovery approval requires a bounded authenticator signature")
        issued = _timestamp(self.issued_at_utc, "issued_at_utc")
        expires = _timestamp(self.expires_at_utc, "expires_at_utc")
        if expires <= issued or expires - issued > timedelta(
            seconds=_MAX_TTL_SECONDS
        ):
            raise ValueError("recovery approval expiry is invalid")

    def signed_body(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("signature")
        return {"schema_version": APPROVAL_SCHEMA_VERSION, **value}

    def as_dict(self) -> dict[str, object]:
        return {**self.signed_body(), "signature": self.signature}


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    decision_id: str
    challenge_id: str
    approval_id: str | None
    protected_execution_id: str
    operation: str
    decision: str
    recovery_principal_id: str | None
    expires_at_utc: str
    reason_code: str

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": DECISION_SCHEMA_VERSION, **asdict(self)}


class RecoveryApprovalVerifier(Protocol):
    """Independent authenticator verifier; implementations own credential trust."""

    def verify(
        self, challenge: RecoveryChallenge, approval: RecoveryApproval
    ) -> bool: ...


class RecoveryReplayLedger(Protocol):
    """Durable, atomic single-use and revocation owner.

    Implementations must survive process restart; process-local sets are not
    sufficient to establish replay protection.
    """

    def is_revoked(self, approval_id: str) -> bool: ...

    def consume(self, challenge_id: str, approval_id: str) -> bool: ...

    def revoke(self, approval_id: str, revocation_id: str) -> None: ...


class FileRecoveryReplayLedger:
    """Cross-process durable replay and revocation ledger.

    Records are stored in the canonical engineering-OS control namespace and
    use the existing tamper-evident event-ledger owner. Each check-and-append
    is serialized by that ledger's process-bound file lock.
    """

    def __init__(self, root: Path) -> None:
        reject_path_links(Path(root))
        self.root = Path(root).resolve(strict=True)
        self.path = control_root(self.root) / "runtime-core" / "gremlin" / "recovery-replay"
        self.lock_path = self.path / ".event-ledger.lock"

    def _events_locked(self) -> list[tuple[str, dict[str, str]]]:
        reject_path_links(self.path)
        reject_path_links(self.path.parent / ".ledger-authority" / self.path.name)
        state = validate_event_ledger(self.path, require_head=True)
        if not state["valid"]:
            errors = state.get("errors")
            if not isinstance(errors, list) or not all(
                isinstance(error, str) for error in errors
            ):
                errors = ["ledger validation returned malformed errors"]
            raise RecoveryAuthorizationError(
                "recovery replay ledger integrity failure: "
                + "; ".join(errors)
            )
        event_count = state.get("event_count")
        if (
            type(event_count) is not int
            or event_count < 0
            or event_count > _MAX_REPLAY_EVENTS
        ):
            raise RecoveryAuthorizationError(
                "recovery replay ledger exceeds its event budget"
            )
        events = state["events"]
        if not isinstance(events, list):
            raise RecoveryAuthorizationError("recovery replay ledger is malformed")
        validated: list[tuple[str, dict[str, str]]] = []
        for event in events:
            if not isinstance(event, dict):
                raise RecoveryAuthorizationError(
                    "recovery replay ledger contains an invalid event"
                )
            kind = event.get("kind")
            if not isinstance(kind, str) or kind not in _REPLAY_EVENT_KINDS:
                raise RecoveryAuthorizationError(
                    "recovery replay ledger contains an unknown event"
                )
            payload = event.get("payload")
            expected = (
                {"schema_version", "challenge_id", "approval_id"}
                if event["kind"] == "approval_consumed"
                else {"schema_version", "approval_id", "revocation_id"}
            )
            if (
                not isinstance(payload, dict)
                or set(payload) != expected
                or payload.get("schema_version") != REPLAY_LEDGER_SCHEMA_VERSION
            ):
                raise RecoveryAuthorizationError(
                    "recovery replay ledger event fields are invalid"
                )
            values: dict[str, str] = {}
            for name in expected - {"schema_version"}:
                value = payload[name]
                if not isinstance(value, str):
                    raise RecoveryAuthorizationError(
                        "recovery replay ledger identifier is invalid"
                    )
                values[name] = _identifier(value, name)
            validated.append((kind, values))
        return validated

    def is_revoked(self, approval_id: str) -> bool:
        approval_id = _identifier(approval_id, "approval id")
        with FileLock(self.lock_path, timeout_seconds=10):
            return any(
                kind == "approval_revoked" and payload["approval_id"] == approval_id
                for kind, payload in self._events_locked()
            )

    def consume(self, challenge_id: str, approval_id: str) -> bool:
        challenge_id = _identifier(challenge_id, "challenge id")
        approval_id = _identifier(approval_id, "approval id")
        with FileLock(self.lock_path, timeout_seconds=10):
            events = self._events_locked()
            consumed_approvals = {
                payload["approval_id"]
                for kind, payload in events
                if kind == "approval_consumed"
            }
            revoked_approvals = {
                payload["approval_id"]
                for kind, payload in events
                if kind == "approval_revoked"
            }
            if approval_id in consumed_approvals or approval_id in revoked_approvals:
                return False
            _append_chained_event_locked(
                self.path,
                "approval_consumed",
                {
                    "schema_version": REPLAY_LEDGER_SCHEMA_VERSION,
                    "challenge_id": challenge_id,
                    "approval_id": approval_id,
                },
            )
            return True

    def revoke(self, approval_id: str, revocation_id: str) -> None:
        approval_id = _identifier(approval_id, "approval id")
        revocation_id = _identifier(revocation_id, "revocation id")
        with FileLock(self.lock_path, timeout_seconds=10):
            events = self._events_locked()
            existing = next(
                (
                    payload["revocation_id"]
                    for kind, payload in events
                    if kind == "approval_revoked"
                    and payload["approval_id"] == approval_id
                ),
                None,
            )
            if existing is not None:
                if existing != revocation_id:
                    raise RecoveryAuthorizationError(
                        "recovery approval has a conflicting revocation record"
                    )
                return
            _append_chained_event_locked(
                self.path,
                "approval_revoked",
                {
                    "schema_version": REPLAY_LEDGER_SCHEMA_VERSION,
                    "approval_id": approval_id,
                    "revocation_id": revocation_id,
                },
            )


class RecoveryAuthority:
    """Creates challenges and admits only independent, current human approvals."""

    def __init__(
        self,
        *,
        authority_id: str,
        verifier: RecoveryApprovalVerifier,
        replay_ledger: RecoveryReplayLedger,
        audit_sink: Callable[[Mapping[str, object]], object],
    ) -> None:
        self.authority_id = _identifier(authority_id, "recovery authority id")
        if not callable(getattr(verifier, "verify", None)):
            raise ValueError("independent approval verifier is required")
        if not all(
            callable(getattr(replay_ledger, name, None))
            for name in ("is_revoked", "consume", "revoke")
        ):
            raise ValueError("durable recovery replay/revocation ledger is required")
        if not callable(audit_sink):
            raise ValueError("canonical recovery audit sink is required")
        self._verifier = verifier
        self._replay_ledger = replay_ledger
        self._audit_sink = audit_sink

    def issue_challenge(
        self,
        *,
        requesting_authority_id: str,
        protected_execution_id: str,
        operation: str,
        reason_code: str,
        ttl_seconds: int = 120,
        now: datetime | None = None,
    ) -> RecoveryChallenge:
        if type(ttl_seconds) is not int or not (
            _MIN_TTL_SECONDS <= ttl_seconds <= _MAX_TTL_SECONDS
        ):
            raise ValueError("recovery challenge lifetime is outside its bound")
        issued = now or datetime.now(timezone.utc)
        if issued.tzinfo is None:
            raise ValueError("recovery challenge clock must be timezone-aware")
        issued = issued.astimezone(timezone.utc)
        challenge = RecoveryChallenge(
            challenge_id="px-recovery:" + str(uuid4()),
            requesting_authority_id=_identifier(
                requesting_authority_id, "requesting authority id"
            ),
            protected_execution_id=_identifier(
                protected_execution_id, "protected execution id"
            ),
            operation=_identifier(operation, "operation"),
            reason_code=_identifier(reason_code, "reason code"),
            nonce=secrets.token_urlsafe(32),
            issued_at_utc=issued.isoformat().replace("+00:00", "Z"),
            expires_at_utc=(issued + timedelta(seconds=ttl_seconds))
            .isoformat()
            .replace("+00:00", "Z"),
        )
        self._emit(
            "recovery_challenge_issued",
            challenge_id=challenge.challenge_id,
            execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            result="issued",
            principal_id=None,
        )
        return challenge

    def authorize(
        self,
        challenge: RecoveryChallenge,
        approval: RecoveryApproval,
        *,
        expected_nanny_authority_id: str,
        supervised_identity_id: str,
        now: datetime | None = None,
    ) -> RecoveryDecision:
        nanny_id = _identifier(expected_nanny_authority_id, "Nanny authority id")
        supervised_id = _identifier(supervised_identity_id, "supervised identity id")
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ValueError("recovery authorization clock must be timezone-aware")
        moment = moment.astimezone(timezone.utc)
        if challenge.requesting_authority_id != nanny_id:
            return self._refuse(challenge, approval, "wrong_requesting_authority", moment)
        if self.authority_id == nanny_id:
            return self._refuse(challenge, approval, "authority_not_independent", moment)
        if challenge.protected_execution_id != supervised_id:
            return self._refuse(challenge, approval, "wrong_protected_execution", moment)
        if approval.challenge_sha256 != challenge.challenge_sha256:
            return self._refuse(challenge, approval, "challenge_binding_mismatch", moment)
        if approval.principal_id in {
            supervised_id,
            nanny_id,
            self.authority_id,
        }:
            return self._refuse(challenge, approval, "principal_not_independent", moment)
        issued = _timestamp(approval.issued_at_utc, "approval issued_at_utc")
        expires = _timestamp(approval.expires_at_utc, "approval expires_at_utc")
        challenge_issued = _timestamp(challenge.issued_at_utc, "challenge issued_at_utc")
        challenge_expires = _timestamp(challenge.expires_at_utc, "challenge expires_at_utc")
        if (
            issued < challenge_issued - timedelta(seconds=_CLOCK_SKEW_SECONDS)
            or expires > challenge_expires
            or moment < issued - timedelta(seconds=_CLOCK_SKEW_SECONDS)
            or moment >= expires
            or moment >= challenge_expires
        ):
            return self._refuse(challenge, approval, "approval_expired_or_out_of_window", moment)
        if self._replay_ledger.is_revoked(approval.approval_id):
            return self._refuse(challenge, approval, "approval_revoked", moment)
        if not self._verifier.verify(challenge, approval):
            return self._refuse(challenge, approval, "authenticator_verification_failed", moment)
        if not self._replay_ledger.consume(challenge.challenge_id, approval.approval_id):
            return self._refuse(challenge, approval, "approval_replayed", moment)
        decision = "approved" if approval.granted else "denied"
        result = RecoveryDecision(
            decision_id="px-recovery-decision:" + str(uuid4()),
            challenge_id=challenge.challenge_id,
            approval_id=approval.approval_id,
            protected_execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            decision=decision,
            recovery_principal_id=approval.principal_id,
            expires_at_utc=approval.expires_at_utc,
            reason_code="human_approval_granted" if approval.granted else "human_approval_denied",
        )
        self._emit(
            "recovery_authorization_decided",
            challenge_id=challenge.challenge_id,
            execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            result=decision,
            principal_id=approval.principal_id,
        )
        return result

    def revoke(
        self,
        *,
        challenge: RecoveryChallenge,
        approval: RecoveryApproval,
        target_approval_id: str,
        expected_nanny_authority_id: str,
        supervised_identity_id: str,
        now: datetime | None = None,
    ) -> RecoveryDecision:
        if challenge.operation != "revoke_recovery_approval":
            raise RecoveryAuthorizationError(
                "revocation requires an operation-scoped revocation challenge"
            )
        target_approval_id = _identifier(target_approval_id, "target approval id")
        decision = self.authorize(
            challenge,
            approval,
            expected_nanny_authority_id=expected_nanny_authority_id,
            supervised_identity_id=supervised_identity_id,
            now=now,
        )
        if decision.decision != "approved":
            raise RecoveryAuthorizationError(
                "recovery approval revocation was not independently authorized"
            )
        self._replay_ledger.revoke(target_approval_id, decision.decision_id)
        self._emit(
            "recovery_approval_revoked",
            challenge_id=challenge.challenge_id,
            execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            result="revoked",
            principal_id=decision.recovery_principal_id,
            approval_id=target_approval_id,
            revocation_id=decision.decision_id,
        )
        return decision

    def _refuse(
        self,
        challenge: RecoveryChallenge,
        approval: RecoveryApproval,
        reason_code: str,
        now: datetime,
    ) -> RecoveryDecision:
        self._emit(
            "recovery_authorization_refused",
            challenge_id=challenge.challenge_id,
            execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            result=reason_code,
            principal_id=approval.principal_id,
            approval_id=approval.approval_id,
        )
        return RecoveryDecision(
            decision_id="px-recovery-decision:" + str(uuid4()),
            challenge_id=challenge.challenge_id,
            approval_id=approval.approval_id,
            protected_execution_id=challenge.protected_execution_id,
            operation=challenge.operation,
            decision="denied",
            recovery_principal_id=approval.principal_id,
            expires_at_utc=now.isoformat().replace("+00:00", "Z"),
            reason_code=reason_code,
        )

    def _emit(
        self,
        event_type: str,
        *,
        challenge_id: str | None,
        execution_id: str,
        operation: str,
        result: str,
        principal_id: str | None,
        approval_id: str | None = None,
        revocation_id: str | None = None,
    ) -> None:
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "recovery_authority_id": self.authority_id,
            "challenge_id": challenge_id,
            "approval_id": approval_id,
            "revocation_id": revocation_id,
            "protected_execution_id": execution_id,
            "operation": operation,
            "principal_id": principal_id,
            "result": result,
            "occurred_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        self._audit_sink(event)
