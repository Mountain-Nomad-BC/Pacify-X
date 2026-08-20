from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from runtime.startup import bounded_startup
from runtime.state_invariants import (
    CoordinationPreCommitGuard,
    StateInvariantError,
    validate_coordination_startup,
    validate_coordination_state,
)
from runtime.wal_transaction import JsonArtifact, JsonWal


ROOT = Path(__file__).resolve().parents[1]


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seal_state(state: dict[str, object]) -> None:
    state["state_hash"] = None
    state["state_hash"] = _hash(state)


def _task(
    identifier: str,
    status: str,
    *,
    dependency: str | None = None,
    owner: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "status": status,
        "depends_on": [dependency] if dependency else [],
        "claim_targets": [f"runtime/{identifier}.py"],
        "owner": owner,
        "budget": {
            "max_minutes": 30,
            "max_tokens": 1_000,
            "max_cost_usd": 10,
            "hard_stop": True,
        },
        "usage": {
            "minutes": 0,
            "tokens": 0,
            "cost_usd": 0,
            "status": "healthy",
        },
    }


def _states(
    project: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    actor = {"actor_id": "agent-a", "session_id": "session-a"}
    previous = {
        "schema_version": "1.2",
        "project": {"id": "project-a", "root": str(project.resolve())},
        "revision": 1,
        "state_hash": None,
        "active_plan": "plan-a",
        "plans": [
            {
                "id": "plan-a",
                "status": "active",
                "task_ids": ["task-a", "task-b"],
            }
        ],
        "tasks": [
            _task("task-a", "reconciled"),
            _task("task-b", "planned", dependency="task-a"),
        ],
        "claims": [],
        "sessions": [],
        "memory": {
            "session_records": 0,
            "project_records": 0,
            "state_records": 0,
            "system_candidates": 0,
        },
        "team_fabric": {"fencing_by_target": {}, "budgets": {}},
    }
    _seal_state(previous)
    candidate = deepcopy(previous)
    candidate["revision"] = 2
    candidate["tasks"][1]["status"] = "claimed"
    candidate["tasks"][1]["owner"] = actor
    candidate["team_fabric"]["fencing_by_target"] = {"runtime/task-b.py": 1}
    candidate["claims"] = [
        {
            "id": "claim-a",
            "task_id": "task-b",
            "actor": actor,
            "targets": ["runtime/task-b.py"],
            "mode": "exclusive",
            "status": "active",
            "expires_utc": "2099-01-01T00:00:00Z",
            "fencing_tokens": {"runtime/task-b.py": 1},
        }
    ]
    _seal_state(candidate)
    event = {
        "schema_version": "1.2",
        "event_id": "event-2",
        "project_id": "project-a",
        "before_hash": previous["state_hash"],
        "after_hash": candidate["state_hash"],
        "previous_event_sha256": "c" * 64,
    }
    event["event_sha256"] = _hash(event)
    return previous, candidate, event


def _codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["violations"]}


def test_valid_transition_checks_every_invariant_family(tmp_path: Path) -> None:
    previous, candidate, event = _states(tmp_path)
    report = validate_coordination_state(
        candidate,
        previous_state=previous,
        event=event,
        observed_memory_counts={
            "session": 0,
            "project": 0,
            "state": 0,
            "system_candidate": 0,
        },
    )
    assert report["valid"] is True
    assert set(report["checks"]) == {
        "coordination",
        "claims",
        "fencing",
        "dag",
        "budget",
        "revision",
        "event_ancestry",
        "memory",
    }


@pytest.mark.parametrize(
    ("hostile", "expected"),
    [
        ("claim_missing_task", "claim_task_missing"),
        ("claim_owner", "claim_owner_mismatch"),
        ("duplicate_owner", "exclusive_owner"),
        ("stale_fence", "stale_fencing_token"),
        ("fence_decrease", "fencing_monotonic"),
        ("dag_cycle", "dag_cycle"),
        ("plan_missing_task", "plan_task_missing"),
        ("budget_negative", "budget_invalid"),
        ("budget_nan", "budget_invalid"),
        ("usage_decrease", "usage_monotonic"),
        ("revision_replay", "revision_monotonic"),
        ("illegal_terminal", "illegal_transition"),
        ("event_before", "event_before_hash"),
        ("event_after", "event_after_hash"),
        ("event_digest", "event_digest"),
        ("memory_decrease", "memory_counter_monotonic"),
        ("memory_drift", "memory_counter_drift"),
    ],
)
def test_hostile_transitions_fail_closed(
    tmp_path: Path, hostile: str, expected: str
) -> None:
    previous, candidate, event = _states(tmp_path)
    observed = {"session": 0, "project": 0, "state": 0, "system_candidate": 0}
    if hostile == "claim_missing_task":
        candidate["claims"][0]["task_id"] = "absent"
    elif hostile == "claim_owner":
        candidate["claims"][0]["actor"] = {
            "actor_id": "agent-b",
            "session_id": "session-b",
        }
    elif hostile == "duplicate_owner":
        duplicate = deepcopy(candidate["claims"][0])
        duplicate["id"] = "claim-b"
        candidate["claims"].append(duplicate)
    elif hostile == "stale_fence":
        candidate["claims"][0]["fencing_tokens"]["runtime/task-b.py"] = 9
    elif hostile == "fence_decrease":
        previous["team_fabric"]["fencing_by_target"] = {"runtime/task-b.py": 2}
    elif hostile == "dag_cycle":
        candidate["tasks"][0]["depends_on"] = ["task-b"]
    elif hostile == "plan_missing_task":
        candidate["plans"][0]["task_ids"].append("absent")
    elif hostile == "budget_negative":
        candidate["tasks"][1]["budget"]["max_tokens"] = -1
    elif hostile == "budget_nan":
        candidate["tasks"][1]["usage"]["cost_usd"] = float("nan")
    elif hostile == "usage_decrease":
        previous["tasks"][1]["usage"]["tokens"] = 5
    elif hostile == "revision_replay":
        candidate["revision"] = previous["revision"]
    elif hostile == "illegal_terminal":
        previous["tasks"][1]["status"] = "reconciled"
    elif hostile == "event_before":
        event["before_hash"] = "f" * 64
    elif hostile == "event_after":
        event["after_hash"] = "f" * 64
    elif hostile == "event_digest":
        event["event_sha256"] = "f" * 64
    elif hostile == "memory_decrease":
        previous["memory"]["project_records"] = 1
    elif hostile == "memory_drift":
        observed["project"] = 1
    report = validate_coordination_state(
        candidate,
        previous_state=previous,
        event=event,
        observed_memory_counts=observed,
    )
    assert report["valid"] is False
    assert expected in _codes(report)


def test_wal_guard_rejects_before_journal_or_target_publication(tmp_path: Path) -> None:
    coordination = tmp_path / "coordination"
    coordination.mkdir()
    previous, candidate, event = _states(tmp_path)
    state_path = coordination / "state.json"
    state_path.write_text(json.dumps(previous), encoding="utf-8")
    candidate["revision"] = 1  # hostile replay
    wal = JsonWal(
        tmp_path / "wal",
        tmp_path,
        precommit_validator=CoordinationPreCommitGuard(coordination),
    )
    artifacts = (
        JsonArtifact("state", state_path, candidate),
        JsonArtifact("event", coordination / "events" / "2.json", event),
        JsonArtifact("receipt", coordination / "receipts" / "2.json", event),
        JsonArtifact("handoff", coordination / "handoff.json", {"revision": 2}),
    )
    with pytest.raises(StateInvariantError) as captured:
        wal.commit(artifacts, transaction_id="hostile-replay")
    assert "revision_monotonic" in _codes(captured.value.report)
    assert json.loads(state_path.read_text(encoding="utf-8"))["revision"] == 1
    transactions = tmp_path / "wal" / "transactions"
    assert not transactions.exists() or not tuple(transactions.iterdir())


def _write_startup_store(project: Path) -> tuple[dict[str, object], dict[str, object]]:
    coordination = project / ".engineering-bootstrap" / "coordination"
    coordination.mkdir(parents=True)
    state = {
        "schema_version": "1.2",
        "project": {"id": "project-a", "root": str(project.resolve())},
        "revision": 1,
        "state_hash": None,
        "active_plan": None,
        "plans": [],
        "tasks": [],
        "claims": [],
        "sessions": [],
        "memory": {
            "session_records": 0,
            "project_records": 0,
            "state_records": 0,
            "system_candidates": 0,
        },
        "team_fabric": {"fencing_by_target": {}, "budgets": {}},
    }
    _seal_state(state)
    event = {
        "schema_version": "1.2",
        "event_id": "event-1",
        "project_id": "project-a",
        "before_hash": "c" * 64,
        "after_hash": state["state_hash"],
        "previous_event_sha256": None,
    }
    event["event_sha256"] = _hash(event)
    (coordination / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (coordination / "events.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8"
    )
    return state, event


def test_startup_checks_event_ancestry_and_strict_memory_counts(tmp_path: Path) -> None:
    state, event = _write_startup_store(tmp_path)
    memory = tmp_path / ".engineering-bootstrap" / "coordination" / "memory"
    memory.mkdir()
    record = {
        "memory_id": "memory-a",
        "revision": 1,
        "project_id": "project-a",
        "layer": "project",
    }
    record["record_sha256"] = _hash(record)
    (memory / "project.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = validate_coordination_startup(tmp_path)
    assert report["valid"] is False
    assert "memory_counter_drift" in _codes(report)

    state["memory"]["project_records"] = 1
    _seal_state(state)
    state_path = tmp_path / ".engineering-bootstrap" / "coordination" / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    event["after_hash"] = state["state_hash"]
    event.pop("event_sha256")
    event["event_sha256"] = _hash(event)
    events_path = tmp_path / ".engineering-bootstrap" / "coordination" / "events.jsonl"
    events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    assert validate_coordination_startup(tmp_path)["valid"] is True


def test_bounded_startup_fails_closed_on_hostile_coordination_state(
    tmp_path: Path,
) -> None:
    state, _event = _write_startup_store(tmp_path)
    state["active_plan"] = "missing-plan"
    state_path = tmp_path / ".engineering-bootstrap" / "coordination" / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(StateInvariantError) as captured:
        bounded_startup(ROOT, tmp_path, tool_names=())
    assert "active_plan_missing" in _codes(captured.value.report)
