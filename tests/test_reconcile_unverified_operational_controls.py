from __future__ import annotations

import json

from scripts.reconcile_unverified_operational_controls import (
    _accepted_recovered_authority_observation,
    _simulate_card_discoveries,
    _simulate_initial_dispositions,
    _simulate_observation_revisions,
    _typed_observation,
    operational_reconciliation_status,
    plan_expected_inventory_revision,
    plan_inventory_revisions,
    plan_operational_card_reconciliations,
    plan_observation_revisions,
)
from runtime.operational_gap_ledger import CHAIN_STAGES, control_disposition_sha256


def _feature_requirements() -> dict[str, object]:
    return {
        "schema_version": "px.feature-acceptance-requirements/1.0",
        "source_revision": "a" * 64,
        "dependency_revisions": {},
        "criteria": [
            {
                "criterion_id": "feature-runtime",
                "required_evidence_classes": ["runtime_effect"],
                "required_authority_class": "installed_host",
                "required_tests": ["exact current installed-host control probe"],
                "allow_not_applicable": False,
            }
        ],
    }


def _feature_acceptance() -> dict[str, object]:
    return {
        "schema_version": "px.feature-acceptance/1.0",
        "source_revision": "a" * 64,
        "dependency_revisions": {},
        "criteria": [
            {
                "criterion_id": "feature-runtime",
                "status": "verified",
                "evidence_classes": ["runtime_effect"],
                "authority_class": "installed_host",
                "tests_run": ["exact current installed-host control probe"],
                "evidence": [
                    {
                        "reference": "sha256:" + "b" * 64,
                        "claim": "The exact feature runtime behavior passed.",
                    }
                ],
            }
        ],
    }


def _accepted_card(severity: str = "medium", state: str = "discovered") -> dict[str, object]:
    return {
        "severity": severity,
        "classification": "UI",
        "current_state": state,
        "feature_acceptance_requirements": _feature_requirements(),
        "feature_acceptance": _feature_acceptance(),
    }


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
        "kind": "action",
        "rendered": attempted,
        "attempted": attempted,
        "errors": [],
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
        "status_truth": {"source_identity": {"state": "mismatch" if mismatch else "verified"}},
        "control_chains": {
            "schema_version": "px.operational-ui-control-chain/1.0",
            "inventory": {"control_count": 2, "sha256": "a" * 64},
            "controls": [
                _record("control-one", attempted=True),
                _record("control-two", attempted=False),
            ],
        },
    }


def _authority_boundary_record() -> dict[str, object]:
    control_id = "pxui.runtime-core.action.cleanupPermanent"
    return {
        "control_id": control_id,
        "surface_id": "surface-one",
        "kind": "action",
        "rendered": True,
        "visible": True,
        "attempted": True,
        "terminal_disposition": "skipped_requires_authority",
        "errors": [],
        "authority": "owned isolated host; exact effect withheld",
        "reason": "the exact effect exceeds this walk authority",
        "expected_effect": "exercise the exact permanent cleanup effect",
        "return_condition": "grant destructive authority and rerun with rollback proof",
        "stages": [
            {
                "stage": stage,
                "status": (
                    "observed"
                    if stage in {"failure_handling", "recovery_rollback"}
                    else "not_observed"
                ),
                "evidence": "exact refusal boundary",
            }
            for stage in CHAIN_STAGES
        ],
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


def test_rendered_complete_terminal_record_is_typed_when_observed_flag_was_omitted() -> None:
    receipt = _receipt()
    record = receipt["control_chains"]["controls"][1]
    record["rendered"] = True
    record["visible"] = True
    record["kind"] = "indicator"
    record["errors"] = []
    record.pop("observed", None)
    record["terminal_disposition"] = "observed_complete"
    for stage in record["stages"]:
        stage.update({"status": "observed", "evidence": "exact", "reason": None})

    events, examined = plan_observation_revisions(
        _snapshot(), receipt, "evidence/walk/receipt.json"
    )

    assert examined == 2
    second = next(event for event in events if event["payload"]["control_id"] == "control-two")
    assert second["payload"]["to_disposition"] == "operational"
    assert second["payload"]["observation"]["observed"] is False


def test_omitted_observed_fallback_rejects_unsafe_records() -> None:
    receipt = _receipt()
    base = receipt["control_chains"]["controls"][1]
    base.update({
        "rendered": True,
        "visible": True,
        "kind": "indicator",
        "errors": [],
        "terminal_disposition": "observed_complete",
    })
    base.pop("observed", None)
    for stage in base["stages"]:
        stage.update({"status": "observed", "evidence": "exact", "reason": None})
    unsafe = [
        {**base, "kind": "action"},
        {**base, "visible": False},
        {**base, "errors": ["synthetic-control-error"]},
        {**base, "errors": "synthetic-control-error"},
    ]

    for record in unsafe:
        assert _typed_observation(
            receipt, record, "evidence/walk/receipt.json", "a" * 64
        ) is None


def test_rendered_partial_record_without_observed_or_attempted_is_not_examined() -> None:
    receipt = _receipt()
    record = receipt["control_chains"]["controls"][1]
    record["rendered"] = True
    record.pop("observed", None)

    events, examined = plan_observation_revisions(
        _snapshot(), receipt, "evidence/walk/receipt.json"
    )

    assert examined == 1
    assert all(event["payload"]["control_id"] != "control-two" for event in events)


def test_exact_recovered_authority_boundary_remains_a_nonoperational_gap() -> None:
    receipt = _receipt()
    record = _authority_boundary_record()
    observation = _typed_observation(
        receipt, record, "evidence/walk/receipt.json", "a" * 64
    )

    assert observation is not None
    assert observation["schema_version"] == "px.control-observation/2.0"
    assert observation["outcome"] == "observed_only"
    assert observation["control_kind"] == "action"
    assert observation["evidence_mode"] == "contained_fault_injection"
    assert observation["observed"] is True
    assert observation["recovered_authority_boundary"] is True
    assert _accepted_recovered_authority_observation(record["control_id"], observation)

    snapshot = {
        "surfaces": {
            "surface-one": {
                "known_controls": [record["control_id"]],
                "control_dispositions": {
                    record["control_id"]: _disposition("PX-OS-001")
                },
            }
        }
    }
    receipt["control_chains"]["inventory"]["control_count"] = 1
    receipt["control_chains"]["controls"] = [record]
    events, examined = plan_observation_revisions(
        snapshot, receipt, "evidence/walk/receipt.json"
    )
    assert examined == 1
    assert events[0]["payload"]["to_disposition"] == "gap"
    assert events[0]["payload"]["gap_ids"] == ["PX-OS-001"]


def test_recovered_authority_boundary_contract_fails_closed() -> None:
    receipt = _receipt()
    base = _authority_boundary_record()
    invalid_records = [
        {**base, "control_id": "pxui.unknown.action"},
        {**base, "kind": "command"},
        {**base, "rendered": False},
        {**base, "visible": False},
        {**base, "attempted": False},
        {**base, "errors": ["fault"]},
        {**base, "errors": "fault"},
        {**base, "reason": ""},
        {
            **base,
            "stages": [
                {**stage, "status": "observed"} for stage in base["stages"]
            ],
        },
        {
            **base,
            "stages": [
                stage for stage in base["stages"]
                if stage["stage"] != "recovery_rollback"
            ],
        },
    ]
    for record in invalid_records:
        try:
            observation = _typed_observation(
                receipt, record, "evidence/walk/receipt.json", "a" * 64
            )
        except ValueError:
            # Missing a mandatory stage is invalid before it can be accepted.
            continue
        if observation is None:
            continue
        assert observation["recovered_authority_boundary"] is False
        assert not _accepted_recovered_authority_observation(
            str(record["control_id"]), observation
        )


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

    reported = _receipt()
    reported["status_truth"]["source_identity"]["state"] = "reported_match"
    try:
        plan_observation_revisions(
            _snapshot(), reported, "evidence/walk/receipt.json"
        )
    except ValueError as error:
        assert "positive current-source" in str(error)
    else:
        raise AssertionError("reported-only source identity was admitted")


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
            "PX-OS-001": _accepted_card(),
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
    assert events[-1]["payload"]["feature_acceptance"] == _feature_acceptance()
    assert all(event["payload"]["gap_id"] != "PX-OS-002" for event in events)
    assert all(event["payload"]["gap_id"] != "PX-OS-003" for event in events)


def test_dry_run_observation_simulation_preserves_gap_binding_for_reconciliation() -> None:
    snapshot = _snapshot()
    snapshot["cards"] = {
        "PX-OS-001": _accepted_card(),
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


def test_check_projection_preserves_discovered_cards_while_adding_dispositions() -> None:
    snapshot = {
        "cards": {},
        "surfaces": {
            "surface-one": {"control_dispositions": {}}
        },
    }
    discovery = [{
        "payload": {"gap_id": "PX-OS-003", "control_action": "control-three"}
    }]
    active = _simulate_card_discoveries(snapshot, discovery)
    disposition = [{
        "payload": {
            "surface_id": "surface-one",
            "control_id": "control-three",
            "disposition": "gap",
            "gap_ids": ["PX-OS-003"],
            "evidence": [{"reference": "inventory", "claim": "current gap"}],
        }
    }]

    projected = _simulate_initial_dispositions(
        active, disposition, "2026-09-06T00:00:00Z"
    )

    assert projected["cards"]["PX-OS-003"]["current_state"] == "discovered"
    assert projected["surfaces"]["surface-one"]["control_dispositions"]["control-three"]["gap_ids"] == ["PX-OS-003"]


def test_green_control_does_not_select_feature_with_missing_runtime_acceptance() -> None:
    chain = {
        stage: {
            "state": "not_applicable",
            "detail": "The control itself has no direct runtime stage.",
            "evidence": [f"receipt#{stage}"],
        }
        for stage in CHAIN_STAGES
    }
    operational = _disposition("PX-OS-001")
    operational.update(
        {
            "disposition": "operational",
            "gap_ids": [],
            "observation": {"outcome": "operational", "interaction_chain": chain},
            "history": [{"gap_ids": ["PX-OS-001"]}],
        }
    )
    snapshot = {
        "cards": {
            "PX-OS-001": {
                "severity": "critical",
                "classification": "runtime",
                "current_state": "scoped",
                "required_runtime_features": ["memory-broker"],
            }
        },
        "surfaces": {
            "surface-one": {"control_dispositions": {"green-textbox": operational}}
        },
    }

    events, selected = plan_operational_card_reconciliations(
        snapshot, "evidence/exact.json"
    )

    assert events == []
    assert selected == []


def test_operational_status_rejects_complete_count_with_unexamined_control(
    tmp_path, monkeypatch,
) -> None:
    inventory_path = tmp_path / "registry/operational_surface_inventory.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(
        json.dumps({
            "schema_version": "px.operational-surface-inventory/2.0",
            "inventory_id": "inventory-r1",
            "surfaces": [{"surface_id": "surface-one", "controls": [{}, {}]}],
        }),
        encoding="utf-8",
    )
    receipt = _receipt()
    receipt["control_chains"]["inventory"].update({
        "path": str(inventory_path.resolve()),
        "schema_version": "px.current-source-control-manifest/1.0",
        "inventory_id": "pacify-x-current-source-controls/inventory-r1",
        "surface_count": 1,
        "control_count": 2,
        "sha256": "a" * 64,
    })
    for record in receipt["control_chains"]["controls"]:
        for stage in record["stages"]:
            stage.update(
                {"status": "observed", "evidence": "exact", "reason": None}
            )
        record["terminal_disposition"] = "interaction_complete"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    snapshot = _snapshot()
    snapshot["cards"] = {}
    for disposition in snapshot["surfaces"]["surface-one"]["control_dispositions"].values():
        disposition.update({
            "disposition": "operational",
            "gap_ids": [],
            "proof_status": "current_typed",
            "observation": {
                "outcome": "operational",
                "source_identity": {"source_sha256": "a" * 64},
            },
        })
    monkeypatch.setattr(
        "scripts.reconcile_unverified_operational_controls.read_snapshot",
        lambda root: snapshot,
    )

    invalid = operational_reconciliation_status(tmp_path, receipt_path)
    assert invalid["valid"] is False
    assert invalid["examined_control_count"] == 1

    second = receipt["control_chains"]["controls"][1]
    second["observed"] = True
    second["terminal_disposition"] = "observed_complete"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    valid = operational_reconciliation_status(tmp_path, receipt_path)
    assert valid["valid"] is True
    assert valid["operational_receipt_count"] == 2


def test_operational_status_accepts_only_exact_current_authority_boundary(
    tmp_path, monkeypatch,
) -> None:
    inventory_path = tmp_path / "registry/operational_surface_inventory.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(
        json.dumps({
            "schema_version": "px.operational-surface-inventory/2.0",
            "inventory_id": "inventory-r1",
            "surfaces": [{"surface_id": "surface-one", "controls": [{}]}],
        }),
        encoding="utf-8",
    )
    receipt = _receipt()
    record = _authority_boundary_record()
    receipt["control_chains"]["controls"] = [record]
    receipt["control_chains"]["inventory"].update({
        "path": str(inventory_path.resolve()),
        "schema_version": "px.current-source-control-manifest/1.0",
        "inventory_id": "pacify-x-current-source-controls/inventory-r1",
        "surface_count": 1,
        "control_count": 1,
        "sha256": "a" * 64,
    })
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    observation = _typed_observation(
        receipt, record, str(receipt_path), "a" * 64
    )
    durable_observation = {
        field: observation[field]
        for field in (
            "schema_version", "outcome", "authority", "observed_at",
            "source_identity", "rendered", "attempted", "interaction_chain",
            "control_kind", "evidence_mode", "observed",
        )
    }
    disposition = _disposition("PX-OS-001")
    disposition.update({
        "proof_status": "current_typed",
        "observation": durable_observation,
    })
    snapshot = {
        "cards": {"PX-OS-001": {"current_state": "discovered"}},
        "surfaces": {
            "surface-one": {
                "known_controls": [record["control_id"]],
                "control_dispositions": {record["control_id"]: disposition},
            }
        },
    }
    monkeypatch.setattr(
        "scripts.reconcile_unverified_operational_controls.read_snapshot",
        lambda root: snapshot,
    )

    status = operational_reconciliation_status(tmp_path, receipt_path)
    assert status["valid"] is True
    assert status["operational_receipt_count"] == 0
    assert status["recovered_authority_boundary_count"] == 1
    assert status["accepted_receipt_count"] == 1
    assert status["unresolved_control_ids"] == []
    assert status["nonterminal_bound_card_ids"] == []

    durable_observation["evidence_mode"] = "contained_ui_interaction"
    invalid_durable_mode = operational_reconciliation_status(tmp_path, receipt_path)
    assert invalid_durable_mode["valid"] is False
    assert invalid_durable_mode["unresolved_control_ids"] == [
        f"surface-one/{record['control_id']}"
    ]
    durable_observation["evidence_mode"] = "contained_fault_injection"

    durable_observation["control_kind"] = "command"
    invalid_durable_kind = operational_reconciliation_status(tmp_path, receipt_path)
    assert invalid_durable_kind["valid"] is False
    assert invalid_durable_kind["unresolved_control_ids"] == [
        f"surface-one/{record['control_id']}"
    ]
    durable_observation["control_kind"] = "action"

    record["reason"] = ""
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    invalid = operational_reconciliation_status(tmp_path, receipt_path)
    assert invalid["valid"] is False
    assert invalid["recovered_authority_boundary_count"] == 0
    assert invalid["accepted_receipt_count"] == 0
