from __future__ import annotations

from scripts.reconcile_unverified_operational_controls import (
    plan_observation_revisions,
)
from runtime.operational_gap_ledger import CHAIN_STAGES, control_disposition_sha256


def _disposition(gap_id: str) -> dict[str, object]:
    return {
        "disposition": "gap",
        "gap_ids": [gap_id],
        "evidence": [{"reference": "inventory", "claim": "unverified"}],
        "observation": None,
        "proof_status": "legacy_unbound",
        "timestamp": "2026-08-16T00:00:00Z",
        "actor": "test",
        "history": [],
    }


def _snapshot() -> dict[str, object]:
    return {
        "surfaces": {
            "surface-one": {
                "known_controls": ["control-one", "control-two"],
                "control_dispositions": {
                    "control-one": _disposition("PX-OS-001"),
                    "control-two": _disposition("PX-OS-002"),
                },
            }
        }
    }


def _record(control_id: str, *, attempted: bool) -> dict[str, object]:
    return {
        "control_id": control_id,
        "surface_id": "surface-one",
        "rendered": attempted,
        "attempted": attempted,
        "observed_at": "2026-08-16T00:00:00Z",
        "authority": "isolated current-source host",
        "terminal_disposition": "observed_only" if attempted else "not_rendered",
        "stages": [
            {
                "stage": stage,
                "status": "observed" if attempted and index < 3 else "not_attempted",
                "evidence": "exact observation" if attempted and index < 3 else None,
                "reason": "not exercised" if not attempted or index >= 3 else None,
            }
            for index, stage in enumerate(CHAIN_STAGES)
        ],
    }


def _receipt(*, mismatch: bool = False) -> dict[str, object]:
    return {
        "schema_version": "px.operational-ui-walk/1.2",
        "observed_at": "2026-08-16T00:00:00Z",
        "authority": "isolated current-source host",
        "host_source_mismatch": mismatch,
        "status_truth": {"source_identity": {"state": "mismatch" if mismatch else "reported_match"}},
        "control_chains": {
            "schema_version": "px.operational-ui-control-chain/1.0",
            "inventory": {"control_count": 2, "sha256": "a" * 64},
            "controls": [
                _record("control-one", attempted=True),
                _record("control-two", attempted=False),
            ],
        },
    }


def test_only_attempted_controls_receive_predecessor_bound_observations() -> None:
    snapshot = _snapshot()
    events, attempted = plan_observation_revisions(snapshot, _receipt(), "evidence/walk/receipt.json")

    assert attempted == 1
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "control_disposition_revised"
    assert event["payload"]["control_id"] == "control-one"
    assert event["payload"]["to_disposition"] == "gap"
    assert event["payload"]["gap_ids"] == ["PX-OS-001"]
    assert event["payload"]["previous_disposition_sha256"] == control_disposition_sha256(
        snapshot["surfaces"]["surface-one"]["control_dispositions"]["control-one"]
    )
    observation = event["payload"]["observation"]
    assert observation["schema_version"] == "px.control-observation/1.0"
    assert observation["outcome"] == "observed_only"
    assert observation["attempted"] is True
    assert set(observation["interaction_chain"]) == set(CHAIN_STAGES)
    assert all(stage["evidence"] for stage in observation["interaction_chain"].values())
    assert all(event["event_type"] != "surface_examined" for event in events)


def test_receipt_without_positive_current_source_identity_is_rejected() -> None:
    try:
        plan_observation_revisions(_snapshot(), _receipt(mismatch=True), "evidence/walk/receipt.json")
    except ValueError as error:
        assert "positive current-source" in str(error)
    else:
        raise AssertionError("identity-invalid receipt was admitted")


def test_complete_denominator_is_required_even_when_only_one_control_was_attempted() -> None:
    receipt = _receipt()
    receipt["control_chains"]["controls"].pop()
    try:
        plan_observation_revisions(_snapshot(), receipt, "evidence/walk/receipt.json")
    except ValueError as error:
        assert "complete ledger control denominator" in str(error)
    else:
        raise AssertionError("partial control denominator was admitted")
