from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.memory_broker import (
    build_memory_query_plan,
    materialize_memory_context,
    validate_memory_query_plan,
)
from runtime.memory_fabric import MemoryRecord


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _record(memory_id: str, **changes: object) -> MemoryRecord:
    values = {
        "memory_id": memory_id, "workspace_id": "workspace", "project_id": "project",
        "owner_id": "actor", "session_id": "session", "lease_id": "lease",
        "title": "Decision", "memory_type": "decision", "summary": "Use bounded proof",
        "source_artifact": "evidence.json", "source_sha256": "a" * 64,
        "evidence_locator": "evidence:one", "epistemic_status": "observation",
        "confidence": 0.9, "confidence_method": "direct", "classification": "internal",
        "acl": ("project", "actor"), "observed_at": NOW, "effective_at": NOW,
        "certification_status": "certified", "retrieval_enabled": True, "layer": "L1",
        "visibility": "project", "priority": 80,
    }
    values.update(changes)
    return MemoryRecord(**values)


def _plan(**changes):
    values = {
        "project_id": "project", "subject_id": "task", "actor_id": "actor",
        "agent_id": "agent", "binding_ids": ("memory:one",),
        "memory_classes": ("decision",), "tiers": ("L1",), "max_items": 2,
        "max_bytes": 4096, "max_tokens": 1024, "trust_floor": 0.8,
        "max_age_seconds": 3600, "conflict_policy": "quarantine",
        "provenance_required": True, "writeback_policy": "deny",
        "source_revision": "source-1", "dependency_revisions": {"memory": "revision-1"},
    }
    values.update(changes)
    return build_memory_query_plan(**values)


def test_current_scoped_trusted_memory_materializes_with_provenance() -> None:
    plan = _plan()
    assert validate_memory_query_plan(plan)["valid"]
    result = materialize_memory_context(plan, [_record("memory:one")], now_utc=NOW)
    assert result["eligible"] is True
    assert result["items"][0]["source_sha256"] == "a" * 64
    assert result["byte_count"] <= plan.max_bytes
    assert result["token_count"] <= plan.max_tokens


def test_foreign_stale_and_below_trust_memory_fail_closed() -> None:
    cases = (
        _record("memory:one", project_id="foreign"),
        _record("memory:one", effective_at=NOW - timedelta(hours=2)),
        _record("memory:one", confidence=0.1),
    )
    for record in cases:
        result = materialize_memory_context(_plan(), [record], now_utc=NOW)
        assert result["eligible"] is False
        assert result["items"] == []


def test_budget_overflow_and_conflict_are_quarantined() -> None:
    huge = _record("memory:one", summary="x" * 500)
    result = materialize_memory_context(_plan(max_bytes=20), [huge], now_utc=NOW)
    assert "memory_byte_budget_exceeded" in result["quarantined"]
    left = _record("memory:one", conflicts_with=("memory:two",))
    right = _record("memory:two")
    result = materialize_memory_context(
        _plan(binding_ids=("memory:one", "memory:two")), [left, right], now_utc=NOW
    )
    assert result["eligible"] is False
    assert any(item.startswith("memory_conflict") for item in result["quarantined"])


def test_writeback_requires_narrow_policy_and_revision_freshness() -> None:
    try:
        _plan(writeback_policy="allow")
    except ValueError as error:
        assert "writeback policy" in str(error)
    else:
        raise AssertionError("broad writeback policy was accepted")
    report = validate_memory_query_plan(
        _plan(), current_source_revision="source-2"
    )
    assert not report["valid"]
