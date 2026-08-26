from __future__ import annotations

from scripts.reconcile_unverified_operational_controls import (
    _simulate_observation_revisions,
    plan_expected_inventory_revision,
    plan_inventory_revisions,
    plan_operational_card_reconciliations,
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


def test_current_walker_completion_dispositions_are_operational() -> None:
    for terminal in (
        "installed_operational_interaction_complete",
        "reversible_ui_interaction_observed",
    ):
        receipt = _receipt()
        record = receipt["control_chains"]["controls"][0]
        record["terminal_disposition"] = terminal
        for stage in record["stages"]:
            stage.update(
                {"status": "observed", "evidence": "exact observation", "reason": None}
            )

        events, attempted = plan_observation_revisions(
            _snapshot(), receipt, "evidence/walk/receipt.json"
        )

        assert attempted == 1
        assert events[0]["payload"]["to_disposition"] == "operational"
        assert events[0]["payload"]["gap_ids"] == []
        assert events[0]["payload"]["observation"]["outcome"] == "operational"


def test_complete_read_only_observation_is_operational_without_attempt() -> None:
    receipt = _receipt()
    record = receipt["control_chains"]["controls"][0]
    record["attempted"] = False
    record["observed"] = True
    record["terminal_disposition"] = "observed_complete"
    for stage in record["stages"]:
        stage.update(
            {"status": "observed", "evidence": "exact observation", "reason": None}
        )

    events, examined = plan_observation_revisions(
        _snapshot(), receipt, "evidence/walk/receipt.json"
    )

    assert examined == 1
    assert events[0]["payload"]["to_disposition"] == "operational"
    observation = events[0]["payload"]["observation"]
    assert observation["attempted"] is False
    assert observation["observed"] is True


def test_partial_reobservation_does_not_downgrade_operational_proof() -> None:
    snapshot = _snapshot()
    current = snapshot["surfaces"]["surface-one"]["control_dispositions"][
        "control-one"
    ]
    current.update(
        {
            "disposition": "operational",
            "gap_ids": [],
            "observation": {
                "outcome": "operational",
                "interaction_chain": {
                    stage: {
                        "state": "present",
                        "detail": "direct",
                        "evidence": [f"receipt#{stage}"],
                    }
                    for stage in CHAIN_STAGES
                },
            },
        }
    )

    events, attempted = plan_observation_revisions(
        snapshot, _receipt(), "evidence/walk/receipt.json"
    )

    assert attempted == 1
    assert events == []


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


def test_inventory_revision_retires_removed_controls_and_adds_current_controls() -> None:
    snapshot = _snapshot()
    snapshot["surfaces"]["surface-one"]["control_records"] = {
        "control-one": {
            "control_id": "control-one", "kind": "field", "label": "one",
            "source_refs": ["old.js"],
        },
        "control-two": {
            "control_id": "control-two", "kind": "field", "label": "two",
            "source_refs": ["old.js"],
        },
    }
    controls = [
        {
            "control_id": "control-two", "kind": "field", "label": "two",
            "source_refs": ["current.js"],
        },
        {
            "control_id": "control-three", "kind": "action", "label": "three",
            "source_refs": ["current.js"],
        },
    ]
    import hashlib
    import json
    denominator = hashlib.sha256(
        json.dumps(["control-two", "control-three"], separators=(",", ":")).encode()
    ).hexdigest()
    inventory = {
        "surfaces": [{
            "surface_id": "surface-one",
            "expected_control_count": 2,
            "expected_controls_sha256": denominator,
            "source_files": ["current.js"],
            "controls": controls,
        }]
    }

    events = plan_inventory_revisions(snapshot, inventory, "registry/inventory.json")

    assert len(events) == 1
    payload = events[0]["payload"]
    assert events[0]["event_type"] == "surface_inventory_revised"
    assert payload["controls"] == controls
    assert payload["retired_controls"] == [{
        "control_id": "control-one",
        "reason": "The current canonical typed inventory no longer declares this control.",
        "replacement_control_ids": [],
    }]
    assert payload["previous_controls_sha256"] != denominator


def test_inventory_revision_is_empty_when_denominator_and_records_match() -> None:
    snapshot = _snapshot()
    controls = [
        {
            "control_id": control_id, "kind": "field", "label": control_id,
            "source_refs": ["current.js"],
        }
        for control_id in ("control-one", "control-two")
    ]
    snapshot["surfaces"]["surface-one"]["control_records"] = {
        item["control_id"]: item for item in controls
    }
    import hashlib
    import json
    denominator = hashlib.sha256(
        json.dumps(["control-one", "control-two"], separators=(",", ":")).encode()
    ).hexdigest()
    inventory = {"surfaces": [{
        "surface_id": "surface-one",
        "expected_control_count": 2,
        "expected_controls_sha256": denominator,
        "source_files": ["current.js"],
        "controls": controls,
    }]}

    assert plan_inventory_revisions(snapshot, inventory, "registry/inventory.json") == []


def test_expected_inventory_revision_predecessor_binds_current_authority() -> None:
    snapshot = {
        "expected_inventory": {
            "inventory_id": "inventory-r1",
            "source": "registry/inventory.json",
            "source_sha256": "a" * 64,
            "surfaces": [],
        }
    }
    inventory = {
        "inventory_id": "inventory-r2",
        "surfaces": [{
            "surface_id": "surface-one",
            "expected_control_count": 2,
            "expected_controls_sha256": "b" * 64,
        }],
    }

    events = plan_expected_inventory_revision(
        snapshot, inventory, "registry/inventory.json", "c" * 64
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "expected_inventory_revised"
    assert events[0]["payload"]["previous_source_sha256"] == "a" * 64
    assert events[0]["payload"]["source_sha256"] == "c" * 64
    assert events[0]["payload"]["surfaces"] == inventory["surfaces"]


def test_expected_inventory_revision_is_empty_for_exact_current_authority() -> None:
    rows = [{
        "surface_id": "surface-one",
        "expected_control_count": 2,
        "expected_controls_sha256": "b" * 64,
    }]
    snapshot = {"expected_inventory": {
        "inventory_id": "inventory-r2",
        "source": "registry/inventory.json",
        "source_sha256": "c" * 64,
        "surfaces": rows,
    }}
    inventory = {"inventory_id": "inventory-r2", "surfaces": rows}

    assert plan_expected_inventory_revision(
        snapshot, inventory, "registry/inventory.json", "c" * 64
    ) == []


def test_card_reconciliation_selects_only_fully_operational_historical_scope() -> None:
    chain = {
        stage: {"state": "present", "detail": "direct", "evidence": [f"receipt#{stage}"]}
        for stage in CHAIN_STAGES
    }
    operational = _disposition("PX-OS-001")
    operational.update({
        "disposition": "operational", "gap_ids": [],
        "observation": {"outcome": "operational", "interaction_chain": chain},
        "history": [{"gap_ids": ["PX-OS-001"]}],
    })
    incomplete = _disposition("PX-OS-002")
    snapshot = {
        "cards": {
            "PX-OS-001": {"severity": "medium", "classification": "UI", "current_state": "discovered"},
            "PX-OS-002": {"severity": "critical", "classification": "UI", "current_state": "scoped"},
            "PX-OS-003": {"severity": "high", "classification": "backend", "current_state": "discovered"},
        },
        "surfaces": {"surface-one": {"control_dispositions": {
            "complete": operational, "incomplete": incomplete,
        }}},
    }

    events, selected = plan_operational_card_reconciliations(snapshot, "evidence/exact.json")

    assert selected == ["PX-OS-001"]
    assert events[0]["event_type"] == "card_annotated"
    assert events[0]["payload"]["patch"]["completion_evidence"] == ["evidence/exact.json"]
    assert events[-1]["payload"]["to_state"] == "operationally_verified"
    assert all(event["payload"]["gap_id"] != "PX-OS-002" for event in events)
    assert all(event["payload"]["gap_id"] != "PX-OS-003" for event in events)


def test_dry_run_observation_simulation_preserves_gap_binding_for_reconciliation() -> None:
    snapshot = _snapshot()
    snapshot["cards"] = {
        "PX-OS-001": {"severity": "medium", "classification": "UI", "current_state": "discovered"},
        "PX-OS-002": {"severity": "medium", "classification": "UI", "current_state": "discovered"},
    }
    receipt = _receipt()
    first = receipt["control_chains"]["controls"][0]
    first["terminal_disposition"] = "interaction_complete"
    for item in first["stages"]:
        item.update({"status": "observed", "evidence": "exact observation", "reason": None})
    revisions, attempted = plan_observation_revisions(snapshot, receipt, "evidence/exact.json")

    active = _simulate_observation_revisions(snapshot, revisions)
    events, selected = plan_operational_card_reconciliations(active, "evidence/exact.json")

    assert attempted == 1
    assert selected == ["PX-OS-001"]
    assert events[-1]["payload"]["to_state"] == "operationally_verified"
    disposition = active["surfaces"]["surface-one"]["control_dispositions"]["control-one"]
    assert disposition["disposition"] == "operational"
    assert disposition["gap_ids"] == []
    assert disposition["history"][-1]["gap_ids"] == ["PX-OS-001"]
