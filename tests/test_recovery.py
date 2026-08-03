from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from runtime.recovery import DurableState, load_state, persist_state, reconcile_resume


def _state(*, interrupted: tuple[str, ...] = ()) -> DurableState:
    return DurableState(
        package_id="pkg-1", completed_steps=("plan",),
        selected_skills=(("skill-a", "1.0"),), pending_approvals=("approval-1",),
        evidence_refs=("evidence-1",), idempotency_keys=("effect-1",),
        interrupted_steps=interrupted,
    )


def test_durable_state_round_trip_and_previous_version_is_preserved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state/state.json"
        persist_state(_state(), path)
        assert load_state(path) == _state()
        persist_state(_state(interrupted=("execute",)), path)
        history = list((path.parent / ".history/state.json").glob("*.json"))
        assert len(history) == 1
        assert load_state(history[0]) == _state()
        assert load_state(path) == _state(interrupted=("execute",))


def test_durable_state_refuses_non_file_replacement_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state"
        path.mkdir()
        with pytest.raises(ValueError, match="not a file"):
            persist_state(_state(), path)


def test_resume_fails_for_missing_evidence_interruption_and_replayed_effect() -> None:
    allowed, reasons = reconcile_resume(
        _state(interrupted=("execute",)), actual_evidence=(),
        requested_idempotency_key="effect-1",
    )
    assert not allowed
    assert reasons == (
        "effect idempotency key has already completed",
        "interrupted steps are non-certifying",
        "recorded evidence is missing from runtime",
    )


def test_resume_accepts_current_evidence_and_new_effect_key() -> None:
    assert reconcile_resume(
        _state(), actual_evidence=("evidence-1",),
        requested_idempotency_key="effect-2",
    ) == (True, ())
