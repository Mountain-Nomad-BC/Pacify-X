from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from runtime.agent_handoff import (
    acknowledge_handoff,
    consume_handoff,
    create_handoff_packet,
    persist_handoff_packet,
    validate_handoff_packet,
)


REV = "a" * 64
EVIDENCE = ({"ref": "evidence:one", "sha256": "b" * 64, "revision": "r1"},)


def packet(**overrides):
    values = {
        "project_id": "project",
        "task_plan_id": "plan",
        "task_plan_revision": REV,
        "run_id": "run",
        "sender_agent_id": "sender",
        "sender_revision": REV,
        "receiver_agent_id": "receiver",
        "receiver_revision": REV,
        "evidence": EVIDENCE,
        "hypotheses": ("h1",),
        "open_questions": ("q1",),
        "authority": ("read",),
        "sender_authority": ("read", "write"),
        "budgets": {"tool_calls": 2},
        "memory_query_plan_sha256": REV,
        "created_utc": "2026-09-04T12:00:00Z",
        "expires_utc": "2026-09-04T13:00:00Z",
    }
    values.update(overrides)
    return create_handoff_packet(**values)


def context(**overrides):
    values = {
        "expected_project_id": "project",
        "receiver_agent_id": "receiver",
        "receiver_revision": REV,
        "current_evidence_revisions": {"evidence:one": "r1"},
        "now_utc": "2026-09-04T12:30:00Z",
    }
    values.update(overrides)
    return values


def test_create_acknowledge_consume_and_immutable_persistence(tmp_path):
    value = packet()
    with pytest.raises(FrozenInstanceError):
        value.run_id = "changed"  # type: ignore[misc]
    path = persist_handoff_packet(value, tmp_path / "handoff.json")
    assert path.is_file()
    with pytest.raises(FileExistsError):
        persist_handoff_packet(value, path)
    with pytest.raises(PermissionError, match="before valid acknowledgment"):
        consume_handoff(value, None, **context())
    ack = acknowledge_handoff(
        value,
        decision="accept",
        reason="revision verified",
        receiver_agent_id="receiver",
        receiver_revision=REV,
        acknowledged_utc="2026-09-04T12:20:00Z",
    )
    assert consume_handoff(value, ack, **context())["consumable"]


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"receiver_revision": "b" * 64}, "receiver_revision_mismatch"),
        ({"now_utc": "2026-09-04T13:00:00Z"}, "packet_expired"),
        ({"current_evidence_revisions": {"evidence:one": "r2"}}, "stale_evidence"),
        ({"expected_project_id": "foreign"}, "project_mismatch"),
    ),
)
def test_validation_rejects_revision_expiration_evidence_and_scope(changes, error):
    result = validate_handoff_packet(packet(), **context(**changes))
    assert not result["valid"]
    assert any(error in item for item in result["errors"])


def test_authority_budget_receiver_and_recovery_boundaries():
    with pytest.raises(PermissionError, match="exceeds sender"):
        packet(authority=("write",), sender_authority=("read",))
    with pytest.raises(ValueError, match="positive explicit budgets"):
        packet(budgets={})
    value = packet(recovery_of="handoff-prior")
    assert value.recovery_of == "handoff-prior"
    with pytest.raises(PermissionError, match="receiver revision mismatch"):
        acknowledge_handoff(
            value,
            decision="accept",
            reason="wrong receiver",
            receiver_agent_id="receiver",
            receiver_revision="b" * 64,
            acknowledged_utc="2026-09-04T12:20:00Z",
        )
    tampered = replace(value, run_id="substituted")
    assert not validate_handoff_packet(tampered, **context())["valid"]
