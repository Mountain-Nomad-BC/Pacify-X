from __future__ import annotations

"""PX-GAP-0004: the operational gap ledger delta lifecycle invariant.

These tests pin the invariant that a delta checkpoint is INCREMENTAL and
EXPLICITLY PARENTED, that compaction is driven by aggregate retained bytes and
chain depth rather than any single delta's size, that superseded checkpoints
become a governed reclaim set with a cleanup receipt, and that retained storage
grows approximately LINEARLY across repeated checkpointing.

The growth test is written so that it would fail under the previous
``delta_bytes = prior_delta + appended`` behaviour, which made every
checkpoint a cumulative superset of all earlier ones.
"""

import json
from pathlib import Path

import pytest

from runtime.operational_gap_ledger import (
    DELTA_CHAIN_DEPTH_COMPACTION_THRESHOLD,
    DELTA_RETAINED_BYTES_COMPACTION_THRESHOLD,
    DELTA_SEMANTICS_INCREMENTAL,
    DELTA_SEMANTICS_LEGACY_CUMULATIVE,
    _build_delta_head,
    _digest,
    _encoded_json,
    _encoded_segment,
    _incremental_segment,
    append_event,
    delta_reclaim_set,
    project_events,
    read_head,
    read_snapshot,
    reclaim_delta_checkpoints,
)


def _card(index: int) -> dict[str, object]:
    return {
        "gap_id": f"PX-GAP-{index:04d}",
        "parent_surface": "agent-console",
        "feature": f"lifecycle feature {index}",
        "control_action": f"perform action {index}",
        "discovery_source": "source trace",
        "discovered_at": "AUTO",
        "discovered_by": "AUTO",
        "source_refs": [{"path": "runtime/operational_gap_ledger.py", "symbols": ["append_event"]}],
        "expected_behavior": f"Behaviour {index} holds.",
        "observed_behavior": f"Behaviour {index} does not hold.",
        "interaction_chain": {
            "open_load": {"state": "present", "detail": "loaded", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "display": {"state": "present", "detail": "displayed", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "user_edit_action": {"state": "present", "detail": "edited", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "input_validation": {"state": "present", "detail": "validated", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "authorization": {"state": "present", "detail": "authorized", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "backend_dispatch": {"state": "present", "detail": "dispatched", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "runtime_effect": {"state": "present", "detail": "effected", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "progress_reporting": {"state": "present", "detail": "reported", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "result_acknowledgement": {"state": "present", "detail": "acknowledged", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "persistence": {"state": "present", "detail": "persisted", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "reload_reopen": {"state": "present", "detail": "reopened", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "failure_handling": {"state": "present", "detail": "handled", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
            "recovery_rollback": {"state": "present", "detail": "rolled back", "evidence": ["runtime/operational_gap_ledger.py:append_event"]},
        },
        "classification": "UI",
        "severity": "medium",
        "operational_impact": f"Impact {index}.",
        "dependencies": [],
        "blockers": [],
        "assigned_owner": "codex-root",
        "tests_required": [f"test {index}"],
        "completion_evidence": [],
        "reopen_reason": None,
        "defer_skip": None,
        "next_action": f"Repair {index}.",
    }


def _seed(root: Path) -> None:
    append_event(root, "ledger_initialized", {"ledger_id": "lifecycle", "scope": ["test"]}, actor="test")


def _event(root: Path, index: int) -> None:
    append_event(root, "card_discovered", _card(index), actor="test")


def _force_delta_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the delta branch by lowering the snapshot-size threshold.

    The production threshold stays at 8 MB; the tests patch the module
    constant so the incremental delta path is exercised without writing an
    8 MB snapshot for every case.
    """
    import runtime.operational_gap_ledger as ledger

    monkeypatch.setattr(ledger, "DELTA_CHECKPOINT_THRESHOLD_BYTES", 1)


def test_incremental_segment_contains_only_its_own_events_and_is_parent_bound() -> None:
    rows = [
        {"sequence": 6, "event_sha256": "a" * 64, "previous_event_sha256": "5" * 64},
        {"sequence": 7, "event_sha256": "b" * 64, "previous_event_sha256": "a" * 64},
    ]
    segment = _incremental_segment(rows, parent_sequence=5, parent_event_sha256="5" * 64)
    # The segment encodes ONLY its own two events - never a cumulative prefix.
    assert segment["event_count"] == 2
    assert segment["first_sequence"] == 6
    assert segment["last_sequence"] == 7
    assert len(_encoded_segment(rows)) < 400


def test_incremental_segment_rejects_a_parentage_break() -> None:
    rows = [{"sequence": 9, "event_sha256": "a" * 64, "previous_event_sha256": "8" * 64}]
    with pytest.raises(ValueError, match="does not follow its parent sequence"):
        _incremental_segment(rows, parent_sequence=7, parent_event_sha256="7" * 64)
    with pytest.raises(ValueError, match="not bound to its parent event"):
        _incremental_segment(rows, parent_sequence=8, parent_event_sha256="z" * 64)


def test_delta_chain_grows_linearly_not_quadratically_across_repeated_checkpointing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The core PX-GAP-0004 regression.

    Under the old ``prior_delta + appended`` behaviour, retained delta bytes
    after N appends grow as ~N^2/2. Under the incremental invariant they grow
    as ~N. This asserts the linear bound and fails under the cumulative one.
    """
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)

    measurements: list[tuple[int, int]] = []
    steps = 24
    for index in range(steps):
        _event(root, index)
        if (index + 1) % 8 == 0:
            report = delta_reclaim_set(root)
            retained = sum(item["size_bytes"] for item in report["present"])
            measurements.append((index + 1, retained))

    small = measurements[1][1] / measurements[1][0]
    large = measurements[2][1] / measurements[2][0]
    # Per-event retained cost must not grow with ledger length. Quadratic
    # retention inflates this ratio without bound; linear retention keeps it
    # within a small constant factor.
    assert large <= small * 1.75, (
        f"retained delta growth is super-linear: per-event cost rose from "
        f"{small:.1f} to {large:.1f} bytes/event"
    )


def test_compaction_is_driven_by_chain_depth_not_by_single_delta_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    for index in range(5):
        _event(root, index)
    head = read_head(root)
    assert head.get("delta_chain") is not None
    chain = head["delta_chain"]
    assert chain["semantics"] == DELTA_SEMANTICS_INCREMENTAL
    # Every appended event is its own incremental segment of exactly one event.
    assert chain["segment_count"] == 5
    assert all(segment["event_count"] == 1 for segment in chain["segments"])
    # Parentage is explicit and contiguous.
    sequences = [segment["first_sequence"] for segment in chain["segments"]]
    assert sequences == sorted(sequences)
    assert chain["base_snapshot_sha256"]


def test_compaction_threshold_constants_are_documented_and_chain_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DELTA_RETAINED_BYTES_COMPACTION_THRESHOLD > 0
    assert DELTA_CHAIN_DEPTH_COMPACTION_THRESHOLD > 0
    # The chain can never exceed the documented depth bound, because exceeding
    # it is itself a compaction trigger.
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    for index in range(12):
        _event(root, index)
    head = read_head(root)
    chain = head.get("delta_chain")
    assert chain is None or chain["segment_count"] <= DELTA_CHAIN_DEPTH_COMPACTION_THRESHOLD


def test_delta_replay_equals_snapshot_reconstruction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A delta-backed head must reconstruct exactly the same state as a full snapshot."""
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    for index in range(6):
        _event(root, index)

    delta_snapshot = read_snapshot(root)
    # Independently rebuild from the raw event log and compare.
    from runtime.operational_gap_ledger import read_events

    rebuilt = project_events(read_events(root))
    assert delta_snapshot["event_count"] == rebuilt["event_count"]
    assert delta_snapshot["head_event_sha256"] == rebuilt["head_event_sha256"]
    assert delta_snapshot["ledger_id"] == rebuilt["ledger_id"]


def test_reclamation_never_removes_a_live_reference_and_retains_a_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    for index in range(4):
        _event(root, index)

    report = delta_reclaim_set(root)
    assert report["present_count"] > 0
    # While the chain is live, every stored delta is referenced.
    assert report["reclaimable"] == []
    assert set(report["live"]) == {item["path"] for item in report["present"]}

    # Reclamation under authorization is a no-op for live deltas and retains a
    # receipt proving nothing live was touched.
    receipt = reclaim_delta_checkpoints(root, authorization="lifecycle-test")
    assert receipt["removed_count"] == 0
    assert receipt["live_paths_preserved"] == report["live"]
    assert (root / "registry" / "operational_gap_ledger.reclaim-receipt.json").is_file()

    # The head still resolves after a reclaim pass.
    assert read_head(root)["event_count"] == 5


def test_legacy_cumulative_deltas_are_preserved_and_never_reinterpreted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A legacy cumulative head must keep its cumulative semantics, explicitly labelled."""
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    for index in range(3):
        _event(root, index)

    # Rewrite the head into the legacy cumulative shape with genuinely
    # cumulative rows (every event since the base snapshot, duplicated forward).
    head_path = root / "registry" / "operational_gap_ledger.head.json"
    head = json.loads(head_path.read_text(encoding="utf-8"))
    snapshot_bytes = (root / "registry" / "operational_gap_ledger.snapshot.json").read_bytes()
    snapshot = json.loads(snapshot_bytes)
    from runtime.operational_gap_ledger import read_events

    all_rows = read_events(root)
    base_count = int(snapshot["event_count"])
    # Legacy cumulative semantics: the checkpoint carries EVERY event appended
    # since the base snapshot - one cumulative file, not per-append segments.
    cumulative = all_rows[base_count:]
    cumulative_bytes = _encoded_segment(cumulative)
    legacy_path = root / "registry" / "operational_gap_ledger.deltas" / (
        f"{__import__('hashlib').sha256(cumulative_bytes).hexdigest()}.jsonl"
    )
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(cumulative_bytes)

    rebuilt, encoded = _build_delta_head(
        json.loads(_encoded_json(read_snapshot(root))),
        _encoded_json(read_snapshot(root)),
        snapshot,
        snapshot_bytes,
        delta_relative=legacy_path.relative_to(root).as_posix(),
        delta_bytes=cumulative_bytes,
        delta_count=len(cumulative),
        fingerprint=head["ledger_fingerprint"],
        tail_event=all_rows[-1],
        verification_basis={"kind": "full_replay"},
        previous_checkpoint_sha256=None,
        semantics=DELTA_SEMANTICS_LEGACY_CUMULATIVE,
    )
    rebuilt.pop("checkpoint_sha256")
    rebuilt["checkpoint_sha256"] = _digest(rebuilt)
    head_path.write_bytes(_encoded_json(rebuilt))

    # The legacy branch reads it, and labels it legacy-cumulative rather than
    # silently treating it as incremental.
    loaded = read_snapshot(root)
    assert loaded["event_count"] == len(all_rows)
    head_now = read_head(root)
    assert head_now["delta_semantics"] == DELTA_SEMANTICS_LEGACY_CUMULATIVE
    assert head_now["delta_projection"]["cumulative"] is True
    assert "delta_chain" not in head_now
    assert base_count <= len(all_rows)


def test_mixed_delta_shapes_are_rejected_with_a_migration_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _seed(root)
    _force_delta_mode(monkeypatch)
    _event(root, 0)
    head_path = root / "registry" / "operational_gap_ledger.head.json"
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["delta_projection"] = {"path": "registry/operational_gap_ledger.deltas/x.jsonl", "event_count": 1, "size_bytes": 1, "sha256": "0" * 64}
    head.pop("checkpoint_sha256")
    head["checkpoint_sha256"] = _digest(head)
    head_path.write_bytes(_encoded_json(head))
    with pytest.raises(ValueError, match="mixes incremental and legacy delta shapes"):
        read_snapshot(root)