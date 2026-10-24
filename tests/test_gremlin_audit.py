from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.event_ledger import validate_event_ledger
from runtime.gremlin.audit import GremlinAuditLedger
from runtime.gremlin.runtime_identity import RuntimeIdentityEvent


def test_gremlin_audit_sink_persists_identity_and_recovery_metadata(tmp_path) -> None:
    sink = GremlinAuditLedger(tmp_path)
    identity_event = RuntimeIdentityEvent(
        event_type="runtime_identity_created",
        authority_id="gremlin-nanny",
        identity_id="a3db073e-1d45-458e-9bef-01f174732d74",
        generation=1,
        occurred_at_utc="2026-10-06T00:00:00Z",
        result="created",
        backend_id="windows-credential-manager",
    )
    recovery_event = {
        "schema_version": "px.gremlin-recovery-event/1.0",
        "event_type": "recovery_challenge_issued",
        "recovery_authority_id": "recovery-authority",
        "challenge_id": "challenge-1",
        "approval_id": None,
        "revocation_id": None,
        "protected_execution_id": "run-1",
        "operation": "restore_run",
        "principal_id": None,
        "result": "issued",
        "occurred_at_utc": datetime(2026, 10, 6, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    sink(identity_event.as_dict())
    sink(recovery_event)

    report = validate_event_ledger(sink.path)
    assert report["valid"]
    assert report["event_count"] == 2


def test_gremlin_audit_sink_rejects_secrets_and_unknown_event_fields(tmp_path) -> None:
    sink = GremlinAuditLedger(tmp_path)
    identity_event = RuntimeIdentityEvent(
        event_type="runtime_identity_created",
        authority_id="gremlin-nanny",
        identity_id="a3db073e-1d45-458e-9bef-01f174732d74",
        generation=1,
        occurred_at_utc="2026-10-06T00:00:00Z",
        result="created",
        backend_id="windows-credential-manager",
    ).as_dict()
    identity_event["signing_key"] = "must-not-be-recorded"

    with pytest.raises(ValueError, match="fields are not exact"):
        sink(identity_event)
