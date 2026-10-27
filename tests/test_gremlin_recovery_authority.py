from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.gremlin.recovery_authority import (
    FileRecoveryReplayLedger,
    RecoveryApproval,
    RecoveryAuthority,
    RecoveryAuthorizationError,
    RecoveryChallenge,
)


class AcceptingVerifier:
    def verify(
        self, _challenge: RecoveryChallenge, approval: RecoveryApproval
    ) -> bool:
        return approval.signature == "authenticator-proof"


class MemoryReplayLedger:
    def __init__(self) -> None:
        self.revoked: set[str] = set()
        self.consumed: set[tuple[str, str]] = set()

    def is_revoked(self, approval_id: str) -> bool:
        return approval_id in self.revoked

    def consume(self, challenge_id: str, approval_id: str) -> bool:
        key = (challenge_id, approval_id)
        if key in self.consumed:
            return False
        self.consumed.add(key)
        return True

    def revoke(self, approval_id: str, _revocation_id: str) -> None:
        self.revoked.add(approval_id)


NOW = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)


def _authority() -> tuple[RecoveryAuthority, MemoryReplayLedger, list[dict[str, object]]]:
    ledger = MemoryReplayLedger()
    events: list[dict[str, object]] = []
    authority = RecoveryAuthority(
        authority_id="human-recovery-authority",
        verifier=AcceptingVerifier(),
        replay_ledger=ledger,
        audit_sink=events.append,
    )
    return authority, ledger, events


def _approval(
    challenge: RecoveryChallenge, *, granted: bool = True
) -> RecoveryApproval:
    return RecoveryApproval(
        approval_id="approval-1",
        challenge_sha256=challenge.challenge_sha256,
        principal_id="independent-human",
        auth_factor="hardware_key",
        granted=granted,
        issued_at_utc="2026-10-06T00:00:30Z",
        expires_at_utc="2026-10-06T00:01:30Z",
        signature="authenticator-proof",
    )


def test_recovery_requires_independent_current_single_use_approval() -> None:
    authority, _ledger, events = _authority()
    challenge = authority.issue_challenge(
        requesting_authority_id="gremlin-nanny",
        protected_execution_id="run-1",
        operation="restore_run",
        reason_code="operator_recovery",
        now=NOW,
    )
    approval = _approval(challenge)

    decision = authority.authorize(
        challenge,
        approval,
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-1",
        now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
    )
    assert decision.decision == "approved"
    assert authority.authorize(
        challenge,
        approval,
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-1",
        now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
    ).reason_code == "approval_replayed"
    assert [event["event_type"] for event in events] == [
        "recovery_challenge_issued",
        "recovery_authorization_decided",
        "recovery_authorization_refused",
    ]


def test_recovery_denial_and_expiry_never_authorize() -> None:
    authority, _ledger, _events = _authority()
    challenge = authority.issue_challenge(
        requesting_authority_id="gremlin-nanny",
        protected_execution_id="run-2",
        operation="restore_run",
        reason_code="operator_recovery",
        now=NOW,
    )
    denied = authority.authorize(
        challenge,
        _approval(challenge, granted=False),
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-2",
        now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
    )
    assert denied.decision == "denied"
    expired = authority.authorize(
        challenge,
        RecoveryApproval(
            approval_id="approval-2",
            challenge_sha256=challenge.challenge_sha256,
            principal_id="independent-human",
            auth_factor="passkey",
            granted=True,
            issued_at_utc="2026-10-06T00:00:30Z",
            expires_at_utc="2026-10-06T00:01:30Z",
            signature="authenticator-proof",
        ),
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-2",
        now=datetime(2026, 10, 6, 0, 2, tzinfo=timezone.utc),
    )
    assert expired.decision == "denied"
    assert expired.reason_code == "approval_expired_or_out_of_window"


def test_recovery_authority_refuses_supervisor_and_wrong_execution() -> None:
    authority, _ledger, _events = _authority()
    challenge = authority.issue_challenge(
        requesting_authority_id="gremlin-nanny",
        protected_execution_id="run-3",
        operation="restore_run",
        reason_code="operator_recovery",
        now=NOW,
    )
    approval = RecoveryApproval(
        approval_id="approval-3",
        challenge_sha256=challenge.challenge_sha256,
        principal_id="gremlin-nanny",
        auth_factor="mfa",
        granted=True,
        issued_at_utc="2026-10-06T00:00:30Z",
        expires_at_utc="2026-10-06T00:01:30Z",
        signature="authenticator-proof",
    )
    decision = authority.authorize(
        challenge,
        approval,
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-3",
        now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
    )
    assert decision.decision == "denied"
    assert decision.reason_code == "principal_not_independent"


def test_recovery_revocation_requires_its_own_approved_challenge() -> None:
    authority, ledger, _events = _authority()
    challenge = authority.issue_challenge(
        requesting_authority_id="gremlin-nanny",
        protected_execution_id="run-4",
        operation="revoke_recovery_approval",
        reason_code="credential_compromised",
        now=NOW,
    )
    decision = authority.revoke(
        challenge=challenge,
        approval=_approval(challenge),
        target_approval_id="approval-to-revoke",
        expected_nanny_authority_id="gremlin-nanny",
        supervised_identity_id="run-4",
        now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
    )
    assert decision.decision == "approved"
    assert ledger.is_revoked("approval-to-revoke")

    with pytest.raises(RecoveryAuthorizationError, match="operation-scoped"):
        authority.revoke(
            challenge=authority.issue_challenge(
                requesting_authority_id="gremlin-nanny",
                protected_execution_id="run-4",
                operation="restore_run",
                reason_code="operator_recovery",
                now=NOW,
            ),
            approval=_approval(challenge),
            target_approval_id="approval-to-revoke",
            expected_nanny_authority_id="gremlin-nanny",
            supervised_identity_id="run-4",
            now=datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc),
        )


def test_file_replay_ledger_persists_and_serializes_recovery_state(tmp_path) -> None:
    ledger = FileRecoveryReplayLedger(tmp_path)
    assert ledger.consume("challenge-1", "approval-1")

    restarted = FileRecoveryReplayLedger(tmp_path)
    assert not restarted.consume("challenge-2", "approval-1")
    assert not restarted.is_revoked("approval-1")

    restarted.revoke("approval-2", "revocation-1")
    assert FileRecoveryReplayLedger(tmp_path).is_revoked("approval-2")
    assert not ledger.consume("challenge-3", "approval-2")


def test_file_replay_ledger_fails_closed_on_integrity_error(tmp_path) -> None:
    ledger = FileRecoveryReplayLedger(tmp_path)
    assert ledger.consume("challenge-1", "approval-1")
    event = next(ledger.path.glob("*.json"))
    event.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RecoveryAuthorizationError, match="integrity failure"):
        FileRecoveryReplayLedger(tmp_path).is_revoked("approval-1")
