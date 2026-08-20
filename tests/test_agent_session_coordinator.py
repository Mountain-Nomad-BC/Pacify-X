from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.agent_fleet_controls import (
    AgentSessionCoordinator,
    _stable,
    admit_inbox_message,
    evaluate_fleet_readiness,
)
from runtime.operational_event_bus import OperationalEventBus


ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-08-11T19:00:00Z"


def _participant(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "agent_id": "agent-a",
        "project_id": "pacify-x",
        "owner_id": "owner-a",
        "permissions": ["read", "write"],
        "heartbeat_age_seconds": 0,
        "reserved_cost": 4.5,
    }
    value.update(changes)
    return value


def _coordinator(tmp_path: Path) -> AgentSessionCoordinator:
    bus = OperationalEventBus(ROOT, tmp_path / "operation-bus", tmp_path)
    return AgentSessionCoordinator(
        ROOT,
        bus,
        tmp_path / "agent-sessions",
        tmp_path,
        heartbeat_max_age_seconds=120,
        total_cost_cap=10,
    )


def _register(coordinator: AgentSessionCoordinator, **participant: object) -> dict[str, object]:
    return coordinator.register_session(
        _participant(**participant),
        session_id="session-a",
        task_id="task-O07",
        claim_id="claim-visible-agent-state",
        orchestration_id="orch-universal-visibility",
        observed_at=T0,
        required_permissions=["read"],
    )


def test_readiness_fails_closed_for_duplicate_stale_cost_and_cross_project() -> None:
    duplicate = [_participant(), _participant(owner_id="owner-b")]
    result = evaluate_fleet_readiness("pacify-x", duplicate)
    assert result["valid"] is False
    assert all("identity missing or duplicated" in row["errors"] for row in result["agents"])
    assert result["authority_granted"] is False

    stale = evaluate_fleet_readiness(
        "pacify-x", [_participant(heartbeat_age_seconds=121)], heartbeat_max_age_seconds=120
    )
    assert stale["valid"] is False
    assert "heartbeat stale" in stale["agents"][0]["errors"]

    overflow = evaluate_fleet_readiness(
        "pacify-x", [_participant(reserved_cost=10.01)], total_cost_cap=10
    )
    assert overflow["valid"] is False
    assert "fleet cost cap exceeded" in overflow["agents"][0]["errors"]

    cross_project = evaluate_fleet_readiness(
        "pacify-x", [_participant(project_id="different-project")]
    )
    assert cross_project["valid"] is False
    assert "cross-project agent rejected" in cross_project["agents"][0]["errors"]


@pytest.mark.parametrize("reserved_cost", [float("nan"), float("inf"), "invalid", None])
def test_readiness_rejects_non_finite_or_missing_cost(reserved_cost: object) -> None:
    result = evaluate_fleet_readiness(
        "pacify-x", [_participant(reserved_cost=reserved_cost)]
    )
    assert result["valid"] is False
    assert "reserved cost is invalid" in result["agents"][0]["errors"]


def test_bounded_inbox_rejects_duplicate_identity_and_cross_project() -> None:
    existing = [
        {"message_id": "message-1", "project_id": "pacify-x", "sender_id": "agent-a"}
    ]
    duplicate = admit_inbox_message(
        "pacify-x",
        existing,
        existing[0],
        allowed_senders=["agent-a"],
    )
    assert duplicate["valid"] is False
    assert "duplicate message identity" in duplicate["errors"]
    cross = admit_inbox_message(
        "pacify-x",
        [],
        {"message_id": "message-2", "project_id": "elsewhere", "sender_id": "agent-a"},
        allowed_senders=["agent-a"],
    )
    assert cross["valid"] is False
    assert cross["mutated"] is False


def test_session_restart_reconstruction_and_event_correlations(tmp_path: Path) -> None:
    first = _coordinator(tmp_path)
    registered = _register(first)
    assert registered["lifecycle"] == "active"
    assert registered["authority_granted"] is False

    # A fresh coordinator instance represents a process restart.  It verifies
    # the hash-sealed projection against the canonical event ancestry.
    restarted = _coordinator(tmp_path)
    reconstructed = restarted.reconstruct_session(
        "pacify-x", "agent-a", "session-a"
    )
    assert reconstructed == registered

    replay = restarted.bus.replay()
    assert replay["valid"] is True
    event = replay["events"][0]["event"]
    assert event["actor"]["actor_id"] == "agent-a"
    assert event["actor"]["session_id"] == "session-a"
    assert event["work"] == {
        "project_id": "pacify-x",
        "task_id": "task-O07",
        "claim_id": "claim-visible-agent-state",
        "orchestration_id": "orch-universal-visibility",
    }
    assert event["correlation_id"] == "orch-universal-visibility"
    assert event["parent_correlation_id"] == "claim-visible-agent-state"
    assert event["capture"] == {
        "classification": "metadata_only",
        "payload_included": False,
    }


def test_all_session_states_legal_transitions_staleness_and_restart(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _register(coordinator)
    waiting = coordinator.transition_session(
        "pacify-x", "agent-a", "session-a", "waiting", observed_at="2026-08-11T19:00:10Z"
    )
    verifying = coordinator.transition_session(
        "pacify-x", "agent-a", "session-a", "verifying", observed_at="2026-08-11T19:00:20Z"
    )
    blocked = coordinator.transition_session(
        "pacify-x", "agent-a", "session-a", "blocked", observed_at="2026-08-11T19:00:30Z"
    )
    recovering = coordinator.restart_session(
        "pacify-x", "agent-a", "session-a", observed_at="2026-08-11T19:00:40Z"
    )
    active = coordinator.transition_session(
        "pacify-x", "agent-a", "session-a", "active", observed_at="2026-08-11T19:00:50Z"
    )
    heartbeat = coordinator.heartbeat_session(
        "pacify-x", "agent-a", "session-a", observed_at="2026-08-11T19:01:00Z"
    )
    assert [waiting["lifecycle"], verifying["lifecycle"], blocked["lifecycle"]] == [
        "waiting",
        "verifying",
        "blocked",
    ]
    assert recovering["lifecycle"] == "recovering"
    assert recovering["restart_count"] == 1
    assert active["lifecycle"] == "active"
    assert heartbeat["heartbeat_sequence"] == 7

    status = coordinator.session_status(
        "pacify-x", "agent-a", "session-a", observed_at="2026-08-11T19:03:01Z"
    )
    assert status["effective_lifecycle"] == "stale"
    assert status["heartbeat_fresh"] is False
    assert status["authority_granted"] is False
    with pytest.raises(ValueError, match="stale agent must enter recovering"):
        coordinator.heartbeat_session(
            "pacify-x", "agent-a", "session-a", observed_at="2026-08-11T19:03:01Z"
        )

    stale = coordinator.transition_session(
        "pacify-x", "agent-a", "session-a", "stale", observed_at="2026-08-11T19:03:01Z"
    )
    assert stale["lifecycle"] == "stale"
    recovered_after_stale = coordinator.restart_session(
        "pacify-x", "agent-a", "session-a", observed_at="2026-08-11T19:03:02Z"
    )
    assert recovered_after_stale["lifecycle"] == "recovering"
    assert recovered_after_stale["restart_count"] == 2

    events = coordinator.bus.replay()["events"]
    assert len(events) == 9
    assert all(item["event"]["work"]["task_id"] == "task-O07" for item in events)
    assert all(item["event"]["work"]["claim_id"] == "claim-visible-agent-state" for item in events)
    assert all(item["event"]["work"]["orchestration_id"] == "orch-universal-visibility" for item in events)


def test_illegal_transition_duplicate_identity_and_cross_project_fail_closed(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _register(coordinator)
    with pytest.raises(ValueError, match="duplicate stable agent identity"):
        coordinator.register_session(
            _participant(),
            session_id="different-session",
            task_id="task-O07",
            claim_id="claim-visible-agent-state",
            orchestration_id="orch-universal-visibility",
            observed_at="2026-08-11T19:00:01Z",
        )
    with pytest.raises(ValueError, match="illegal agent session transition"):
        coordinator.transition_session(
            "pacify-x", "agent-a", "session-a", "recovering", observed_at="2026-08-11T19:00:02Z"
        )
    with pytest.raises(ValueError, match="cross-project"):
        coordinator.reconstruct_session("another-project", "agent-a", "session-a")
    assert coordinator.bus.replay()["revision"] == 1


def test_registration_sums_existing_project_reservations_before_admission(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    _register(coordinator)
    with pytest.raises(ValueError, match="fleet cost cap exceeded"):
        coordinator.register_session(
            _participant(agent_id="agent-b", owner_id="owner-b", reserved_cost=6.0),
            session_id="session-b",
            task_id="task-O07-b",
            claim_id="claim-visible-agent-state-b",
            orchestration_id="orch-universal-visibility",
            observed_at="2026-08-11T19:00:01Z",
        )
    assert coordinator.bus.replay()["revision"] == 1


def test_restart_rolls_projection_forward_after_event_before_state_crash(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    registered = _register(coordinator)
    candidate = {
        **registered,
        "lifecycle": "waiting",
        "heartbeat_at": "2026-08-11T19:00:10+00:00",
        "heartbeat_sequence": 2,
        "state_revision": 2,
    }
    for field in ("last_event_id", "last_event_sha256", "last_bus_revision", "record_sha256"):
        candidate.pop(field)
    event = coordinator._event_for_state(
        candidate,
        operation_name="agent.session.transition.waiting",
        observed_at="2026-08-11T19:00:10+00:00",
        previous_event_sha256=str(registered["last_event_sha256"]),
        input_sha256=_stable(coordinator._projection_payload(registered)),
    )
    receipt = coordinator.bus.publish(event)

    # Simulate a process dying after the canonical event commit but before the
    # current-state projection commit.  A new coordinator validates the input
    # digest and legal transition, then rolls only the projection forward.
    restarted = _coordinator(tmp_path)
    recovered = restarted.reconstruct_session("pacify-x", "agent-a", "session-a")
    assert recovered["lifecycle"] == "waiting"
    assert recovered["last_event_sha256"] == receipt["event_sha256"]
    assert recovered["state_revision"] == 2


def test_state_tampering_is_not_reconstructed_over(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    registered = _register(coordinator)
    key = coordinator._session_key("pacify-x", "agent-a", "session-a")
    path = tmp_path / "agent-sessions" / "sessions" / key[:2] / f"{key}.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["owner_id"] = "attacker"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        coordinator.reconstruct_session("pacify-x", "agent-a", "session-a")
    assert registered["owner_id"] == "owner-a"
