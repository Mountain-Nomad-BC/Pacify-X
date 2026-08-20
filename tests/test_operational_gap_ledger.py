from __future__ import annotations

import base64
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import json

import pytest

from runtime.operational_gap_ledger import (
    PRIMARY_STATES,
    append_event,
    append_events,
    append_transition_admission_backfill,
    blank_interaction_chain,
    card_control_scope_sha256,
    control_disposition_sha256,
    evidence_reference_sha256,
    guard_work_admission,
    project_events,
    read_head,
    read_snapshot,
    read_events,
    write_snapshot,
)
from runtime.dashboard_api import (
    _operational_punch_cards,
    query_operational_inventory,
    query_operational_punch_card,
)


def evidence(claim: str = "observed") -> list[dict[str, str]]:
    return [{"reference": "source:file.py:symbol", "claim": claim}]


def control_observation(
    outcome: str = "operational",
    *,
    rendered: bool = True,
    attempted: bool = True,
) -> dict[str, object]:
    state = "present" if outcome == "operational" else "missing"
    chain = {
        stage: {
            "state": state,
            "detail": f"Exact fixture observation for {stage}.",
            "evidence": ["sha256:" + "a" * 64],
        }
        for stage in blank_interaction_chain()
    }
    return {
        "schema_version": "px.control-observation/1.0",
        "outcome": outcome,
        "authority": "isolated disposable test host",
        "observed_at": "2026-08-16T00:00:00Z",
        "source_identity": {
            "kind": "test-fixture",
            "source_sha256": "a" * 64,
            "current_source": True,
            "host_source_mismatch": False,
        },
        "rendered": rendered,
        "attempted": attempted,
        "interaction_chain": chain,
    }


def card(identifier: str = "PX-GAP-0001") -> dict[str, object]:
    return {
        "gap_id": identifier,
        "parent_surface": "workflow-studio",
        "feature": "revision reopen",
        "control_action": "save and reopen",
        "discovery_source": "source trace",
        "discovered_at": "AUTO",
        "discovered_by": "AUTO",
        "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
        "expected_behavior": "The revision reopens exactly.",
        "observed_behavior": "The revision loses editor state.",
        "interaction_chain": blank_interaction_chain(),
        "classification": "revisioning",
        "severity": "high",
        "operational_impact": "Edits cannot be trusted after reload.",
        "dependencies": [],
        "blockers": [],
        "assigned_owner": "codex-primary",
        "tests_required": ["save-reopen equality"],
        "completion_evidence": [],
        "reopen_reason": None,
        "defer_skip": None,
        "next_action": "Implement a hash-bound editor sidecar.",
    }


def initialize(root: Path) -> None:
    append_event(root, "ledger_initialized", {"ledger_id": "test-ledger", "scope": ["test"]}, actor="test")


def process_discover(args: tuple[str, int]) -> None:
    root, index = args
    append_event(
        Path(root),
        "card_discovered",
        card(f"PX-GAP-{index:04d}"),
        actor=f"process-{index}",
    )


def test_discovery_provenance_binds_event_time_actor_and_source_symbols(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    event = append_event(tmp_path, "card_discovered", card(), actor="test-agent")
    assert event["payload"]["discovered_at"] == event["timestamp"]
    assert event["payload"]["discovered_by"] == "test-agent"

    bad_time = card("PX-GAP-0002")
    bad_time["discovered_at"] = "not-a-time"
    with pytest.raises(ValueError, match="ISO-8601"):
        append_event(tmp_path, "card_discovered", bad_time, actor="test-agent")

    bad_actor = card("PX-GAP-0002")
    bad_actor["discovered_by"] = "different-agent"
    with pytest.raises(ValueError, match="authoritative event actor"):
        append_event(tmp_path, "card_discovered", bad_actor, actor="test-agent")

    no_symbols = card("PX-GAP-0002")
    no_symbols["source_refs"] = [{"path": "runtime/owner.py", "symbols": []}]
    with pytest.raises(ValueError, match="source_refs"):
        append_event(tmp_path, "card_discovered", no_symbols, actor="test-agent")


def controls_sha256(values: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest()


def write_report(root: Path, name: str, finding_ids: list[str]) -> dict[str, object]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": "px.operational-gap-audit-manifest/1.0",
        "finding_ids": finding_ids,
        "findings": [
            {"finding_id": finding_id, "summary": f"Finding {finding_id}."}
            for finding_id in finding_ids
        ],
    }
    data = json.dumps(value, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    return {
        "source": name,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "finding_ids": finding_ids,
    }


def transition_payload(identifier: str, before: str, after: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "gap_id": identifier,
        "from_state": before,
        "to_state": after,
        "reason": f"advance to {after}",
        "evidence": evidence(after),
    }
    if after == "implemented":
        payload["implementation_evidence"] = evidence("implementation")
    elif after == "narrowly_verified":
        payload["verification"] = {"tests_run": ["targeted test"], "results": evidence("passed")}
    elif after == "integrated":
        payload["integration_evidence"] = evidence("integrated")
    elif after == "operationally_verified":
        payload["operational_evidence"] = evidence("operational")
    return payload


def legacy_implemented_transition(root: Path) -> dict[str, object]:
    initialize(root)
    append_event(root, "card_discovered", card(), actor="test")
    current = "discovered"
    for state in ("reproduced", "scoped", "approved", "implementing", "implemented"):
        append_event(root, "card_transition", transition_payload("PX-GAP-0001", current, state), actor="test")
        current = state
    events = read_events(root)
    target = events[-1]
    target["payload"].pop("implementation_evidence")
    target["event_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in target.items() if key != "event_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    encoded = b"".join(
        json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        for event in events
    )
    (root / "registry" / "operational_gap_ledger.jsonl").write_bytes(encoded)
    return target


def admission_backfill_payload(target: dict[str, object]) -> dict[str, object]:
    return {
        "finding_id": "PX-LEDGER-TRANSITION-ADMISSION-LEGACY-TEST",
        "reason": "Bind the historical transition to its formerly untyped admission evidence.",
        "evidence": evidence("immutable backfill review"),
        "attestations": [
            {
                "target_sequence": target["sequence"],
                "target_event_id": target["event_id"],
                "target_event_sha256": target["event_sha256"],
                "gap_id": target["payload"]["gap_id"],
                "to_state": target["payload"]["to_state"],
                "admission": {"implementation_evidence": evidence("historical implementation")},
            }
        ],
    }


def test_state_machine_refuses_jump_to_closed(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    with pytest.raises(ValueError, match="invalid card transition"):
        append_event(
            tmp_path,
            "card_transition",
            {"gap_id": "PX-GAP-0001", "from_state": "discovered", "to_state": "closed", "reason": "invalid jump", "evidence": evidence()},
            actor="test",
        )
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["cards"]["PX-GAP-0001"]["current_state"] == "discovered"
    assert snapshot["event_count"] == 2


def test_deferred_transition_requires_dependency_and_return_condition(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    payload = {
        "gap_id": "PX-GAP-0001", "from_state": "discovered", "to_state": "deferred",
        "reason": "External dependency is not available.", "evidence": evidence("defer review"),
        "defer_skip": {"reason": "Wait for the dependency.", "authority": "user", "return_condition": "Dependency becomes available."},
    }
    with pytest.raises(ValueError, match="dependency"):
        append_event(tmp_path, "card_transition", payload, actor="test")
    payload["defer_skip"]["dependency"] = "external-service-contract"
    append_event(tmp_path, "card_transition", payload, actor="test")
    result = read_snapshot(tmp_path)["cards"]["PX-GAP-0001"]
    assert result["current_state"] == "deferred"
    assert result["defer_skip"]["dependency"] == "external-service-contract"


def test_duplicate_card_relationship_is_rejected(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    payload = {"parent_gap_id": "PX-GAP-0001", "child_gap_id": "PX-GAP-0002", "relationship": "child", "evidence": evidence("decomposition")}
    append_event(tmp_path, "card_relationship", payload, actor="test")
    with pytest.raises(ValueError, match="already recorded"):
        append_event(tmp_path, "card_relationship", payload, actor="test")


def test_new_cards_cannot_pollute_missing_source_symbols_progress(tmp_path: Path) -> None:
    initialize(tmp_path)
    value = card()
    value["source_refs"] = [{"path": "runtime/owner.py", "symbols": []}]
    with pytest.raises(ValueError, match="source_refs"):
        append_event(tmp_path, "card_discovered", value, actor="test")
    assert read_snapshot(tmp_path)["progress"]["cards_missing_source_symbols"] == []


def test_non_visible_path_resolves_without_fabricating_a_ui_control(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(
        tmp_path,
        "card_control_scope_set",
        {
            "gap_id": "PX-GAP-0001",
            "kind": "non_visible_path",
            "path_id": "pxpath.ledger.append.serialization",
            "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
            "reason": "The defect is owned by an exact backend path, not a visible control.",
            "authority": "Reviewed source ownership and card evidence.",
            "return_condition": "Reclassify if a visible control is introduced.",
            "evidence": evidence("source ownership"),
        },
        actor="test",
    )
    snapshot = read_snapshot(tmp_path)
    resolution = snapshot["cards"]["PX-GAP-0001"]["control_resolution"]
    assert resolution["kind"] == "non_visible_path"
    assert resolution["resolved"] is True
    assert snapshot["progress"]["cards_without_control_links"] == ["PX-GAP-0001"]
    assert snapshot["progress"]["cards_without_control_resolution"] == []


def test_aggregate_scope_requires_relationships_and_resolved_children(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    aggregate = {
        "gap_id": "PX-GAP-0001",
        "kind": "aggregate_parent",
        "child_gap_ids": ["PX-GAP-0002"],
        "reason": "The parent tracks completion of its exact child set.",
        "authority": "Reviewed decomposition.",
        "return_condition": "Revise when the child set changes.",
        "evidence": evidence("decomposition"),
    }
    with pytest.raises(ValueError, match="explicit child relationships"):
        append_event(tmp_path, "card_control_scope_set", aggregate, actor="test")
    append_event(
        tmp_path,
        "card_relationship",
        {"parent_gap_id": "PX-GAP-0001", "child_gap_id": "PX-GAP-0002", "relationship": "child", "evidence": evidence("branch")},
        actor="test",
    )
    append_event(tmp_path, "card_control_scope_set", aggregate, actor="test")
    assert read_snapshot(tmp_path)["progress"]["cards_without_control_resolution"] == ["PX-GAP-0001", "PX-GAP-0002"]
    append_event(
        tmp_path,
        "card_control_scope_set",
        {
            "gap_id": "PX-GAP-0002",
            "kind": "non_visible_path",
            "path_id": "pxpath.child.runtime-effect",
            "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
            "reason": "The child owns the exact non-visible effect.",
            "authority": "Reviewed source ownership.",
            "return_condition": "Reclassify if ownership moves.",
            "evidence": evidence("child ownership"),
        },
        actor="test",
    )
    snapshot = read_snapshot(tmp_path)
    assert snapshot["cards"]["PX-GAP-0001"]["control_resolution"]["resolved"] is True
    assert snapshot["progress"]["cards_without_control_resolution"] == []


def test_control_scope_revision_is_predecessor_bound_and_retains_history(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    initial = {
        "gap_id": "PX-GAP-0001",
        "kind": "non_visible_path",
        "path_id": "pxpath.owner.old",
        "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
        "reason": "Initial reviewed ownership.",
        "authority": "Source review.",
        "return_condition": "Revise if the path moves.",
        "evidence": evidence("initial"),
    }
    append_event(tmp_path, "card_control_scope_set", initial, actor="test")
    current = read_snapshot(tmp_path)["cards"]["PX-GAP-0001"]["control_scope_disposition"]
    revision = {
        **initial,
        "path_id": "pxpath.owner.current",
        "previous_scope_sha256": card_control_scope_sha256(current),
        "reason": "The implementation path moved.",
        "evidence": evidence("revision"),
    }
    stale = {**revision, "previous_scope_sha256": "0" * 64}
    with pytest.raises(ValueError, match="predecessor is stale"):
        append_event(tmp_path, "card_control_scope_revised", stale, actor="test")
    append_event(tmp_path, "card_control_scope_revised", revision, actor="test")
    result = read_snapshot(tmp_path)["cards"]["PX-GAP-0001"]
    assert result["control_scope_disposition"]["path_id"] == "pxpath.owner.current"
    assert result["control_scope_history"][0]["path_id"] == "pxpath.owner.old"


def test_non_visible_control_scope_can_return_to_typed_control_ownership(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(
        tmp_path,
        "surface_registered",
        {
            "surface_id": "workflow-studio",
            "name": "Workflow Studio",
            "source_files": ["ui.js"],
            "known_controls": ["graph-node"],
            "owner": "ui",
            "inventory_evidence": ["ui.js"],
        },
        actor="test",
    )
    initial = {
        "gap_id": "PX-GAP-0001",
        "kind": "non_visible_path",
        "path_id": "pxpath.workflow.graph-node-missing",
        "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
        "reason": "The visible graph control has not been implemented.",
        "authority": "Reviewed source ownership.",
        "return_condition": "Return to typed ownership after the control is inventoried.",
        "evidence": evidence("initial source ownership"),
    }
    append_event(tmp_path, "card_control_scope_set", initial, actor="test")
    current = read_snapshot(tmp_path)["cards"]["PX-GAP-0001"]["control_scope_disposition"]
    append_event(
        tmp_path,
        "card_control_scope_revised",
        {
            "gap_id": "PX-GAP-0001",
            "kind": "typed_controls",
            "reason": "The graph node is now a reviewed typed control.",
            "authority": "Current typed surface inventory.",
            "return_condition": "Revise if the visible control is retired or ownership moves.",
            "previous_scope_sha256": card_control_scope_sha256(current),
            "evidence": evidence("typed control return"),
        },
        actor="test",
    )
    append_event(
        tmp_path,
        "control_disposition",
        {
            "surface_id": "workflow-studio",
            "control_id": "graph-node",
            "disposition": "gap",
            "gap_ids": ["PX-GAP-0001"],
            "evidence": evidence("typed graph ownership"),
        },
        actor="test",
    )
    result = read_snapshot(tmp_path)
    resolution = result["cards"]["PX-GAP-0001"]["control_resolution"]
    assert resolution["kind"] == "typed_controls"
    assert resolution["resolved"] is True
    assert resolution["bindings"] == [
        {"surface_id": "workflow-studio", "control_id": "graph-node"}
    ]
    assert result["progress"]["card_control_scope_conflicts"] == []
    assert result["cards"]["PX-GAP-0001"]["control_scope_history"][0]["kind"] == "non_visible_path"


def test_historical_evidence_attestation_is_exact_and_single_use(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    snapshot = read_snapshot(tmp_path)
    historical = snapshot["cards"]["PX-GAP-0001"]["history"][0]["evidence"][0]
    target = evidence_reference_sha256(historical)
    payload = {
        "gap_id": "PX-GAP-0001",
        "target_evidence_sha256": target,
        "artifact_sha256": "a" * 64,
        "artifact_size": 17,
        "verification_method": "fixture-content-sha256",
        "evidence": evidence("attestation review"),
    }
    assert read_snapshot(tmp_path)["progress"]["cards_with_unbound_evidence"] == ["PX-GAP-0001"]
    assert read_snapshot(tmp_path)["progress"]["evidence_deficient_cards"] == ["PX-GAP-0001"]
    append_event(tmp_path, "card_evidence_attested", payload, actor="test")
    assert read_snapshot(tmp_path)["progress"]["cards_with_unbound_evidence"] == []
    assert read_snapshot(tmp_path)["progress"]["evidence_deficient_cards"] == []
    with pytest.raises(ValueError, match="already recorded"):
        append_event(tmp_path, "card_evidence_attested", {**payload, "artifact_sha256": "b" * 64}, actor="test")


def test_explicit_scope_and_typed_control_binding_is_reported_as_conflict(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]},
        actor="test",
    )
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(
        tmp_path,
        "card_control_scope_set",
        {
            "gap_id": "PX-GAP-0001", "kind": "non_visible_path",
            "path_id": "pxpath.owner.save", "source_refs": [{"path": "runtime/owner.py", "symbols": ["Owner.save"]}],
            "reason": "Initial ownership.", "authority": "Source review.",
            "return_condition": "Revise on a typed binding.", "evidence": evidence("ownership"),
        },
        actor="test",
    )
    append_event(
        tmp_path,
        "control_disposition",
        {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("typed binding")},
        actor="test",
    )
    snapshot = read_snapshot(tmp_path)
    assert snapshot["progress"]["card_control_scope_conflicts"] == ["PX-GAP-0001"]
    assert snapshot["cards"]["PX-GAP-0001"]["control_resolution"]["explicit_scope_conflict"] is True


def test_control_disposition_revision_can_change_exact_gap_bindings_without_rewriting_history(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]},
        actor="test",
    )
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    append_event(
        tmp_path,
        "control_disposition",
        {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("initial binding")},
        actor="test",
    )
    current = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    revision = {
        "surface_id": "workflow-studio", "control_id": "save",
        "previous_disposition_sha256": control_disposition_sha256(current),
        "from_disposition": "gap", "to_disposition": "gap",
        "gap_ids": ["PX-GAP-0001", "PX-GAP-0002"],
        "reason": "A reviewed second card owns part of the same exact control path.",
        "evidence": evidence("reviewed binding"),
    }
    append_event(tmp_path, "control_disposition_revised", revision, actor="test")
    revised = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    assert revised["gap_ids"] == ["PX-GAP-0001", "PX-GAP-0002"]
    assert revised["history"][0]["gap_ids"] == ["PX-GAP-0001"]
    with pytest.raises(ValueError, match="semantic no-op"):
        append_event(
            tmp_path,
            "control_disposition_revised",
            {**revision, "previous_disposition_sha256": control_disposition_sha256(revised)},
            actor="test",
        )


def test_surface_inventory_revision_replaces_polluted_controls_and_preserves_history(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "diagnostics", "name": "Diagnostics", "source_files": ["shared.js"], "known_controls": ["settingsOnly", "validate"], "owner": "ui", "inventory_evidence": ["shared.js"]}, actor="test")
    append_event(
        tmp_path,
        "surface_inventory_revised",
        {
            "surface_id": "diagnostics",
            "previous_controls_sha256": controls_sha256(["settingsOnly", "validate"]),
            "controls": [
                {"control_id": "pxui.diagnostics.action.validate", "kind": "action", "label": "Validate", "source_refs": ["diagnostics.js:10"]},
                {"control_id": "pxui.diagnostics.indicator.ledgerState", "kind": "indicator", "label": "Ledger state", "source_refs": ["diagnostics.js:20"]},
            ],
            "retired_controls": [
                {"control_id": "settingsOnly", "reason": "Replace broad legacy ownership.", "replacement_control_ids": ["pxui.diagnostics.indicator.ledgerState"]},
                {"control_id": "validate", "reason": "Replace legacy action identity.", "replacement_control_ids": ["pxui.diagnostics.action.validate"]},
            ],
            "source_files": ["diagnostics.js"],
            "reason": "Replace whole-file union with typed ownership.",
            "evidence": evidence("typed source trace"),
        },
        actor="test",
    )
    snapshot = project_events(read_events(tmp_path))
    surface = snapshot["surfaces"]["diagnostics"]
    assert surface["known_controls"] == ["pxui.diagnostics.action.validate", "pxui.diagnostics.indicator.ledgerState"]
    assert surface["control_records"]["pxui.diagnostics.action.validate"]["kind"] == "action"
    assert surface["inventory_revisions"][0]["previous_known_controls"] == ["settingsOnly", "validate"]

    legacy_events = json.loads(json.dumps(read_events(tmp_path)))
    legacy_revision = legacy_events[-1]
    legacy_revision["payload"].pop("retired_controls")
    legacy_revision["event_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in legacy_revision.items() if key != "event_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    legacy_surface = project_events(legacy_events)["surfaces"]["diagnostics"]
    assert legacy_surface["inventory_revisions"][0]["retirement_schema"] == "legacy_inferred"
    assert sorted(legacy_surface["retired_controls"]) == ["settingsOnly", "validate"]


def test_surface_inventory_revision_retires_dispositioned_controls_without_destroying_history(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {
            "surface_id": "agent-studio",
            "name": "Agent Studio",
            "source_files": ["old-ui.js"],
            "known_controls": ["legacy-node"],
            "owner": "ui",
            "inventory_evidence": ["old-ui.js"],
        },
        actor="test",
    )
    append_event(
        tmp_path,
        "control_disposition",
        {
            "surface_id": "agent-studio",
            "control_id": "legacy-node",
            "disposition": "operational",
            "gap_ids": [],
            "evidence": evidence("legacy control was examined"),
            "observation": control_observation(),
        },
        actor="test",
    )
    replacement = {
        "control_id": "graph-node",
        "kind": "action",
        "label": "Graph node",
        "source_refs": ["new-ui.js:10"],
    }
    append_event(
        tmp_path,
        "surface_inventory_revised",
        {
            "surface_id": "agent-studio",
            "previous_controls_sha256": controls_sha256(["legacy-node"]),
            "controls": [replacement],
            "retired_controls": [
                {
                    "control_id": "legacy-node",
                    "reason": "Replaced by the graph-backed editor.",
                    "replacement_control_ids": ["graph-node"],
                }
            ],
            "source_files": ["new-ui.js"],
            "reason": "Replace the lifecycle strip with a real graph.",
            "evidence": evidence("graph editor source trace"),
        },
        actor="test",
    )
    snapshot = project_events(read_events(tmp_path))
    surface = snapshot["surfaces"]["agent-studio"]
    retired = surface["retired_controls"]["legacy-node"]
    assert surface["known_controls"] == ["graph-node"]
    assert surface["control_dispositions"] == {}
    assert surface["examined"] is False
    assert retired["disposition"]["disposition"] == "operational"
    assert retired["replacement_control_ids"] == ["graph-node"]
    assert surface["inventory_revisions"][0]["retired_control_ids"] == ["legacy-node"]

    before = (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes()
    with pytest.raises(ValueError, match="exact removed control set"):
        append_event(
            tmp_path,
            "surface_inventory_revised",
            {
                "surface_id": "agent-studio",
                "previous_controls_sha256": controls_sha256(["graph-node"]),
                "controls": [
                    {
                        "control_id": "replacement-two",
                        "kind": "action",
                        "label": "Replacement two",
                        "source_refs": ["new-ui.js:20"],
                    }
                ],
                "retired_controls": [],
                "source_files": ["new-ui.js"],
                "reason": "Invalid missing retirement declaration.",
                "evidence": evidence("must fail"),
            },
            actor="test",
        )
    assert (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes() == before


def test_contradictory_evidence_reopens_a_narrow_verification_without_replacement_card(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    state = "discovered"
    verified = None
    for next_state in PRIMARY_STATES[1:7]:
        verified = append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", state, next_state), actor="test")
        state = next_state
    append_event(
        tmp_path,
        "card_transition",
        {
            "gap_id": "PX-GAP-0001",
            "from_state": "narrowly_verified",
            "to_state": "reopened",
            "reason": "Independent evidence disproved the narrow verification basis.",
            "reopen_reason": "Same-size earlier-event corruption bypassed the cached integrity check.",
            "regression_strengthening": ["add earlier-event same-size corruption test"],
            "contradicted_transition_event_sha256": verified["event_sha256"],
            "evidence": evidence("contradiction"),
        },
        actor="test",
    )
    retained = project_events(read_events(tmp_path))["cards"]["PX-GAP-0001"]
    assert retained["current_state"] == "reopened"
    assert retained["history"][-1]["from"] == "narrowly_verified"


def test_closed_card_reopens_under_same_stable_id_with_history(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    resolved = {
        stage: {"state": "not_applicable", "detail": "This test card does not exercise the application stage.", "evidence": ["test"]}
        for stage in card()["interaction_chain"]
    }
    append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "Resolve interaction applicability.", "evidence": evidence(), "patch": {"interaction_chain": resolved}}, actor="test")
    current = "discovered"
    for state in PRIMARY_STATES[1:-1]:
        append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", current, state), actor="test")
        current = state
    append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "Attach completion evidence before closure.", "evidence": evidence("completion artifact"), "patch": {"completion_evidence": ["evidence/live-reopen.json"]}}, actor="test")
    closing = {"gap_id": "PX-GAP-0001", "from_state": "operationally_verified", "to_state": "closed", "reason": "all interaction stages passed", "evidence": evidence("installed-host result")}
    with pytest.raises(ValueError, match="closure_evidence"):
        append_event(tmp_path, "card_transition", closing, actor="test")
    closed = append_event(tmp_path, "card_transition", {**closing, "closure_evidence": [{"reference": "sha256:" + "a" * 64, "claim": "Exact installed-host completion receipt."}]}, actor="test")
    append_event(tmp_path, "card_transition", {"gap_id": "PX-GAP-0001", "from_state": "closed", "to_state": "reopened", "reason": "later evidence contradicted closure", "reopen_reason": "Reload lost the saved layout.", "regression_strengthening": ["add exact reload regression"], "contradicted_transition_event_sha256": closed["event_sha256"], "evidence": evidence("contradictory reload")}, actor="test")
    snapshot = project_events(read_events(tmp_path))
    retained = snapshot["cards"]["PX-GAP-0001"]
    assert retained["current_state"] == "reopened"
    assert retained["reopen_reason"] == "Reload lost the saved layout."
    assert any(row.get("to") == "closed" for row in retained["history"])
    reopened = next(row for row in retained["history"] if row.get("to") == "reopened")
    assert reopened["regression_strengthening"] == ["add exact reload regression"]


def test_operational_verification_rejects_partial_and_unproved_host_boundary(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    value = card()
    value["classification"] = "host-owned"
    append_event(tmp_path, "card_discovered", value, actor="test")
    current = "discovered"
    for state in PRIMARY_STATES[1:8]:
        append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", current, state), actor="test")
        current = state
    partial = {
        stage: {"state": "not_applicable", "detail": "Host boundary.", "evidence": ["host-contract"]}
        for stage in blank_interaction_chain()
    }
    partial["result_acknowledgement"] = {"state": "partial", "detail": "Host acknowledgement is incomplete.", "evidence": ["host-contract"]}
    append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "Retain boundary chain.", "patch": {"interaction_chain": partial}, "evidence": evidence()}, actor="test")
    base = {
        "gap_id": "PX-GAP-0001", "from_state": "integrated", "to_state": "operationally_verified",
        "reason": "claim boundary", "evidence": evidence(), "operational_evidence": evidence("host result"),
    }
    with pytest.raises(ValueError, match="complete evidence-bound"):
        append_event(tmp_path, "card_transition", base, actor="test")
    partial["result_acknowledgement"] = {"state": "not_applicable", "detail": "Host owns acknowledgement.", "evidence": ["host-contract"]}
    append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "Resolve stage applicability.", "patch": {"interaction_chain": partial}, "evidence": evidence()}, actor="test")
    with pytest.raises(ValueError, match="ownership and user-visible"):
        append_event(tmp_path, "card_transition", base, actor="test")
    append_event(
        tmp_path,
        "card_transition",
        {**base, "boundary_evidence": {"owner": "VS Code host", "authority": "Host security model", "user_visible_behavior": "PX shows the host handoff and exact limitation.", "return_condition": "Reopen if the host contract changes.", "evidence": evidence("host boundary")}},
        actor="test",
    )
    assert read_snapshot(tmp_path)["cards"]["PX-GAP-0001"]["current_state"] == "operationally_verified"


def test_surface_examination_requires_evidence_and_gap_reference(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(tmp_path, "surface_examined", {"surface_id": "workflow-studio", "outcome": "gap", "gap_ids": ["PX-GAP-0001"], "examined_controls": ["save"], "evidence": evidence("save loses layout")}, actor="test")
    append_event(
        tmp_path,
        "control_disposition",
        {
            "surface_id": "workflow-studio",
            "control_id": "save",
            "disposition": "gap",
            "gap_ids": ["PX-GAP-0001"],
            "evidence": evidence("save loses layout"),
            "observation": control_observation("observed_gap"),
        },
        actor="test",
    )
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["progress"]["surfaces_examined"] == 1
    assert snapshot["progress"]["examined_controls"] == 1
    assert snapshot["surfaces"]["workflow-studio"]["examinations"][0]["gap_ids"] == ["PX-GAP-0001"]


def test_partial_surface_walk_does_not_mark_surface_examined(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save", "reload"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(tmp_path, "control_disposition", {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence()}, actor="test")
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["progress"]["surfaces_examined"] == 0
    assert snapshot["progress"]["controls_not_yet_disposed"] == 1


def test_control_disposition_revision_is_predecessor_bound_and_retains_history(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(tmp_path, "control_disposition", {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("identity mismatch blocks proof")}, actor="test")
    current = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    with pytest.raises(ValueError, match="bind its predecessor"):
        append_event(tmp_path, "control_disposition_revised", {"surface_id": "workflow-studio", "control_id": "save", "from_disposition": "gap", "to_disposition": "operational", "previous_disposition_sha256": "0" * 64, "gap_ids": [], "reason": "invalid predecessor", "evidence": evidence("live walk"), "observation": control_observation()}, actor="test")
    append_event(tmp_path, "control_disposition_revised", {"surface_id": "workflow-studio", "control_id": "save", "from_disposition": "gap", "to_disposition": "operational", "previous_disposition_sha256": control_disposition_sha256(current), "gap_ids": [], "reason": "exact current-source host completed the chain", "evidence": evidence("live walk"), "observation": control_observation()}, actor="test")
    snapshot = read_snapshot(tmp_path)
    revised = snapshot["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    assert revised["disposition"] == "operational"
    assert revised["gap_ids"] == []
    assert revised["history"][0]["disposition"] == "gap"
    assert revised["history"][0]["gap_ids"] == ["PX-GAP-0001"]
    assert snapshot["progress"]["operational_controls"] == 1
    assert snapshot["progress"]["gap_controls"] == 0
    assert snapshot["progress"]["controls_with_current_observation"] == 1
    assert snapshot["progress"]["surfaces_operationally_proven"] == 1


def test_legacy_control_disposition_predecessor_hash_survives_observation_projection(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(tmp_path, "control_disposition", {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("legacy gap")}, actor="test")
    current = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    legacy_identity = hashlib.sha256(
        json.dumps(
            {key: value for key, value in current.items() if key not in {"observation", "proof_status"}},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert control_disposition_sha256(current) == legacy_identity
    append_event(
        tmp_path,
        "control_disposition_revised",
        {"surface_id": "workflow-studio", "control_id": "save", "from_disposition": "gap", "to_disposition": "gap", "previous_disposition_sha256": legacy_identity, "gap_ids": ["PX-GAP-0001"], "reason": "Attach current observation.", "evidence": evidence("current walk"), "observation": control_observation("observed_gap")},
        actor="test",
    )
    revised = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]["control_dispositions"]["save"]
    assert revised["proof_status"] == "current_typed"
    assert control_disposition_sha256(revised) != legacy_identity


def test_operational_disposition_rejects_missing_or_incomplete_current_host_proof(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]},
        actor="test",
    )
    base = {
        "surface_id": "workflow-studio",
        "control_id": "save",
        "disposition": "operational",
        "gap_ids": [],
        "evidence": evidence("generic claim is insufficient"),
    }
    with pytest.raises(ValueError, match="typed current-host observation"):
        append_event(tmp_path, "control_disposition", base, actor="test")
    incomplete = control_observation()
    incomplete["interaction_chain"]["reload_reopen"]["state"] = "unknown"
    with pytest.raises(ValueError, match="complete interaction chain"):
        append_event(
            tmp_path,
            "control_disposition",
            {**base, "observation": incomplete},
            actor="test",
        )
    assert read_snapshot(tmp_path)["progress"]["controls_with_disposition"] == 0


def test_legacy_gap_disposition_reconciles_inventory_but_not_examination(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]},
        actor="test",
    )
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(
        tmp_path,
        "control_disposition",
        {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("legacy gap")},
        actor="test",
    )
    progress = read_snapshot(tmp_path)["progress"]
    assert progress["surfaces_inventory_reconciled"] == 1
    assert progress["surfaces_examined"] == 0
    assert progress["controls_with_disposition"] == 1
    assert progress["controls_with_current_observation"] == 0


def test_work_admission_binds_active_checkpoint_and_exact_effect_scope(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    checkpoint = append_event(tmp_path, "work_checkpoint", {"active_gap_id": "PX-GAP-0001", "learned": "The exact repair is bounded.", "next_action": "Implement a hash-bound editor sidecar.", "unresolved_branch_gap_ids": [], "newly_discovered_gap_ids": [], "evidence": evidence("checkpoint")}, actor="test")
    payload = {
        "gap_id": "PX-GAP-0001", "checkpoint_event_id": checkpoint["event_id"],
        "effect": "write", "scope": ["runtime/operational_gap_ledger.py"],
        "authority": "Codex host authority applying PX governance inside the repository scope.",
        "expected_effect": "Add bounded ledger behavior.",
        "rollback": "Retain the append-only card and revert only the scoped source edit if its targeted gate fails.",
        "evidence": evidence("admission"),
    }
    with pytest.raises(ValueError, match="active checkpoint"):
        append_event(tmp_path, "work_admitted", {**payload, "checkpoint_event_id": "wrong"}, actor="test")
    append_event(tmp_path, "work_admitted", payload, actor="test")
    snapshot = read_snapshot(tmp_path)
    assert snapshot["work_admissions"][-1]["gap_id"] == "PX-GAP-0001"
    assert snapshot["work_admissions"][-1]["checkpoint_event_id"] == checkpoint["event_id"]
    assert snapshot["work_admissions"][-1]["scope"] == ["runtime/operational_gap_ledger.py"]


def test_work_guard_requires_exact_active_admission_event_effect_and_scope(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    checkpoint = append_event(
        tmp_path,
        "work_checkpoint",
        {
            "active_gap_id": "PX-GAP-0001",
            "learned": "The repair is bounded.",
            "next_action": "Implement a hash-bound editor sidecar.",
            "unresolved_branch_gap_ids": [],
            "newly_discovered_gap_ids": [],
            "evidence": evidence("checkpoint"),
        },
        actor="test",
    )
    admission = append_event(
        tmp_path,
        "work_admitted",
        {
            "gap_id": "PX-GAP-0001",
            "checkpoint_event_id": checkpoint["event_id"],
            "effect": "write",
            "scope": ["runtime/owner.py", "tests/test_owner.py"],
            "authority": "Codex host authority applying PX governance.",
            "expected_effect": "Implement the bounded owner contract.",
            "rollback": "Revert only the two admitted files.",
            "evidence": evidence("admission"),
        },
        actor="test",
    )
    snapshot = read_snapshot(tmp_path)
    result = guard_work_admission(
        snapshot,
        gap_id="PX-GAP-0001",
        effect="write",
        scope=["tests/test_owner.py", "runtime\\owner.py"],
        admission_event_id=admission["event_id"],
    )
    assert result["valid"] is True
    assert result["admission_event_id"] == admission["event_id"]
    with pytest.raises(ValueError, match="absent"):
        guard_work_admission(
            snapshot,
            gap_id="PX-GAP-0001",
            effect="write",
            scope=["runtime/owner.py", "tests/test_owner.py"],
            admission_event_id="gap-event:missing",
        )
    with pytest.raises(ValueError, match="effect"):
        guard_work_admission(
            snapshot,
            gap_id="PX-GAP-0001",
            effect="execute",
            scope=["runtime/owner.py", "tests/test_owner.py"],
            admission_event_id=admission["event_id"],
        )
    with pytest.raises(ValueError, match="scope"):
        guard_work_admission(
            snapshot,
            gap_id="PX-GAP-0001",
            effect="write",
            scope=["runtime/owner.py"],
            admission_event_id=admission["event_id"],
        )


def test_concurrent_append_serializes_sequence_and_refreshes_snapshot(tmp_path: Path) -> None:
    initialize(tmp_path)

    def discover(index: int) -> None:
        append_event(tmp_path, "card_discovered", card(f"PX-GAP-{index:04d}"), actor=f"worker-{index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(discover, range(1, 13)))
    events = read_events(tmp_path)
    snapshot = project_events(events)
    persisted = __import__("json").loads((tmp_path / "registry/operational_gap_ledger.snapshot.json").read_text(encoding="utf-8"))
    assert [event["sequence"] for event in events] == list(range(1, 14))
    assert snapshot["event_count"] == persisted["event_count"] == 13
    assert snapshot["head_event_sha256"] == persisted["head_event_sha256"]


def test_annotation_revalidates_completion_evidence(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    with pytest.raises(ValueError, match="completion_evidence"):
        append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "invalid", "evidence": evidence(), "patch": {"completion_evidence": [None]}}, actor="test")


def test_local_evidence_is_hash_bound_at_append(tmp_path: Path) -> None:
    initialize(tmp_path)
    source = tmp_path / "evidence.txt"
    source.write_text("exact bytes", encoding="utf-8")
    append_event(tmp_path, "card_discovered", {**card(), "discovery_source": "evidence.txt", "source_refs": [{"path": "evidence.txt", "symbols": []}]}, actor="test")
    snapshot = project_events(read_events(tmp_path))
    discovery = snapshot["cards"]["PX-GAP-0001"]["history"][0]["evidence"][0]
    assert len(discovery["artifact_sha256"]) == 64
    assert discovery["artifact_size"] == 11


def test_dashboard_queries_keep_full_counts_and_load_exact_detail(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", {**card("PX-GAP-0002"), "severity": "low", "feature": "second"}, actor="test")
    page = _operational_punch_cards(tmp_path, limit=1)
    assert page["count"] == 2
    assert page["filtered_count"] == 2
    assert page["has_more"] is True
    assert len(page["cards"]) == 1
    detail = query_operational_punch_card(tmp_path, "PX-GAP-0002")
    assert detail["card"]["feature"] == "second"
    assert detail["card"]["history"][0]["event"] == "discovered"
    inventory = query_operational_inventory(tmp_path, surface_id="workflow-studio")
    assert inventory["surfaces"][0]["known_controls"] == ["save"]


def test_semantic_transition_gates_refuse_unevidenced_implementation(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    current = "discovered"
    for state in ("reproduced", "scoped", "approved", "implementing"):
        append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", current, state), actor="test")
        current = state
    with pytest.raises(ValueError, match="implementation_evidence"):
        append_event(tmp_path, "card_transition", {"gap_id": "PX-GAP-0001", "from_state": "implementing", "to_state": "implemented", "reason": "unsupported", "evidence": evidence()}, actor="test")


def test_hash_bound_backfill_restores_replay_without_rewriting_history(tmp_path: Path) -> None:
    target = legacy_implemented_transition(tmp_path)
    original = (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes()
    with pytest.raises(ValueError, match="implementation_evidence"):
        project_events(read_events(tmp_path))
    backfill = append_transition_admission_backfill(
        tmp_path, admission_backfill_payload(target), actor="test-repair"
    )
    after = (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes()
    assert after.startswith(original)
    snapshot = project_events(read_events(tmp_path))
    history = snapshot["cards"]["PX-GAP-0001"]["history"][-1]
    assert history["implementation_evidence"][0]["claim"] == "historical implementation"
    assert history["admission_backfill"]["backfill_event_id"] == backfill["event_id"]
    assert snapshot["transition_admission_backfills"][0]["target_event_sha256s"] == [target["event_sha256"]]


def test_backfill_rejects_wrong_target_binding_without_append(tmp_path: Path) -> None:
    target = legacy_implemented_transition(tmp_path)
    payload = admission_backfill_payload(target)
    payload["attestations"][0]["gap_id"] = "PX-GAP-9999"
    before = (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes()
    with pytest.raises(ValueError, match="exact target"):
        append_transition_admission_backfill(tmp_path, payload, actor="test-repair")
    assert (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes() == before


def test_backfill_rejects_duplicate_target_attestation(tmp_path: Path) -> None:
    target = legacy_implemented_transition(tmp_path)
    payload = admission_backfill_payload(target)
    append_transition_admission_backfill(tmp_path, payload, actor="test-repair")
    before = (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes()
    with pytest.raises(ValueError, match="more than once"):
        append_transition_admission_backfill(tmp_path, payload, actor="test-repair")
    assert (tmp_path / "registry" / "operational_gap_ledger.jsonl").read_bytes() == before


def test_expected_inventory_and_report_reconciliation_are_explicit(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "expected_inventory_registered", {"inventory_id": "expected", "source": "inventory.json", "source_sha256": "a" * 64, "surfaces": [{"surface_id": "workflow-studio", "expected_control_count": 1, "expected_controls_sha256": "0" * 64}]}, actor="test")
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(tmp_path, "report_registered", {"report_id": "review-1", **write_report(tmp_path, "review.json", ["finding-1"])}, actor="reviewer")
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["progress"]["inventory_drift_surfaces"] == ["workflow-studio"]
    assert snapshot["progress"]["unreconciled_report_findings"] == ["review-1/finding-1"]
    append_event(tmp_path, "report_finding_reconciled", {"report_id": "review-1", "finding_id": "finding-1", "disposition": "card", "gap_ids": ["PX-GAP-0001"], "evidence": evidence()}, actor="test")
    assert project_events(read_events(tmp_path))["progress"]["unreconciled_report_findings"] == []


def test_report_registration_binds_physical_hash_and_exact_finding_denominator(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    valid = write_report(tmp_path, "review.json", ["finding-1", "finding-2"])
    with pytest.raises(ValueError, match="physical report bytes"):
        append_event(
            tmp_path,
            "report_registered",
            {"report_id": "bad-hash", **valid, "source_sha256": "0" * 64},
            actor="reviewer",
        )
    with pytest.raises(ValueError, match="exactly match"):
        append_event(
            tmp_path,
            "report_registered",
            {"report_id": "omitted", **valid, "finding_ids": ["finding-1"]},
            actor="reviewer",
        )
    append_event(
        tmp_path,
        "report_registered",
        {"report_id": "valid", **valid},
        actor="reviewer",
    )
    report = read_snapshot(tmp_path)["reports"]["valid"]
    assert report["finding_ids"] == ["finding-1", "finding-2"]
    assert report["source_size_bytes"] > 0


def test_auto_gap_id_and_snapshot_are_stable(tmp_path: Path) -> None:
    initialize(tmp_path)
    event = append_event(tmp_path, "card_discovered", {**card(), "gap_id": "AUTO"}, actor="test")
    assert event["payload"]["gap_id"] == "PX-OS-001"
    write_snapshot(tmp_path)
    first = (tmp_path / "registry/operational_gap_ledger.snapshot.json").read_bytes()
    write_snapshot(tmp_path)
    assert (tmp_path / "registry/operational_gap_ledger.snapshot.json").read_bytes() == first


def test_preappend_event_bound_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    monkeypatch.setattr(ledger, "MAX_EVENTS", 1)
    with pytest.raises(ValueError, match="event bound would be exceeded"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert len(read_events(tmp_path)) == 1


def test_preappend_byte_bound_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    ledger_path = tmp_path / "registry/operational_gap_ledger.jsonl"
    monkeypatch.setattr(ledger, "MAX_LEDGER_BYTES", ledger_path.stat().st_size + 1)
    with pytest.raises(ValueError, match="byte bound would be exceeded"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert len(read_events(tmp_path)) == 1


def test_new_present_chain_claim_requires_evidence(tmp_path: Path) -> None:
    initialize(tmp_path)
    candidate = card()
    candidate["interaction_chain"]["display"] = {"state": "present", "detail": "Rendered.", "evidence": []}
    with pytest.raises(ValueError, match="requires evidence for present"):
        append_event(tmp_path, "card_discovered", candidate, actor="test")


def test_atomic_event_publication_retains_valid_stream_if_snapshot_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    original = ledger._write_snapshot_unlocked
    monkeypatch.setattr(ledger, "_write_snapshot_unlocked", lambda *_args: (_ for _ in ()).throw(OSError("snapshot blocked")))
    with pytest.raises(OSError, match="snapshot blocked"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert project_events(read_events(tmp_path))["cards"]["PX-GAP-0001"]["current_state"] == "discovered"
    monkeypatch.setattr(ledger, "_write_snapshot_unlocked", original)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    assert set(read_snapshot(tmp_path)["cards"]) == {"PX-GAP-0001", "PX-GAP-0002"}


def test_head_publication_failure_recovers_complete_event_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    original = ledger._write_bytes_atomically

    def fail_head(target, data):
        if target.name == ledger.HEAD_RELATIVE.name:
            raise OSError("head blocked")
        return original(target, data)

    monkeypatch.setattr(ledger, "_write_bytes_atomically", fail_head)
    with pytest.raises(OSError, match="head blocked"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert project_events(read_events(tmp_path))["event_count"] == 2
    monkeypatch.setattr(ledger, "_write_bytes_atomically", original)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    recovered = read_snapshot(tmp_path)
    assert recovered["event_count"] == 3
    assert set(recovered["cards"]) == {"PX-GAP-0001", "PX-GAP-0002"}


def test_work_checkpoint_preserves_unresolved_branches(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    append_event(tmp_path, "work_checkpoint", {"active_gap_id": "PX-GAP-0001", "learned": "A second branch remains.", "next_action": "Implement a hash-bound editor sidecar.", "unresolved_branch_gap_ids": ["PX-GAP-0002"], "newly_discovered_gap_ids": [], "switching_to": "PX-GAP-0002", "evidence": evidence()}, actor="test")
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["work_checkpoints"][0]["unresolved_branch_gap_ids"] == ["PX-GAP-0002"]


def test_work_checkpoint_binds_switch_predecessor_and_new_branch_denominator(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    first = append_event(
        tmp_path,
        "work_checkpoint",
        {"active_gap_id": "PX-GAP-0001", "learned": "Start.", "next_action": "Implement a hash-bound editor sidecar.", "unresolved_branch_gap_ids": ["PX-GAP-0002"], "newly_discovered_gap_ids": [], "evidence": evidence()},
        actor="test",
    )
    append_event(tmp_path, "card_discovered", card("PX-GAP-0003"), actor="test")
    append_event(
        tmp_path,
        "card_annotated",
        {"gap_id": "PX-GAP-0001", "note": "Commit switch action.", "patch": {"next_action": "Switch to PX-GAP-0002."}, "evidence": evidence()},
        actor="test",
    )
    outgoing = {
        "active_gap_id": "PX-GAP-0001", "learned": "A new branch exists.",
        "next_action": "Switch to PX-GAP-0002.",
        "previous_checkpoint_event_id": first["event_id"],
        "newly_discovered_gap_ids": ["PX-GAP-0003"],
        "unresolved_branch_gap_ids": ["PX-GAP-0002", "PX-GAP-0003"],
        "switching_to": "PX-GAP-0002", "evidence": evidence(),
    }
    with pytest.raises(ValueError, match="newly discovered denominator"):
        append_event(tmp_path, "work_checkpoint", {**outgoing, "newly_discovered_gap_ids": []}, actor="test")
    second = append_event(tmp_path, "work_checkpoint", outgoing, actor="test")
    with pytest.raises(ValueError, match="outgoing switch target"):
        append_event(
            tmp_path,
            "work_checkpoint",
            {"active_gap_id": "PX-GAP-0003", "learned": "Wrong switch.", "next_action": "Implement a hash-bound editor sidecar.", "previous_checkpoint_event_id": second["event_id"], "newly_discovered_gap_ids": [], "unresolved_branch_gap_ids": [], "evidence": evidence()},
            actor="test",
        )
    incoming = append_event(
        tmp_path,
        "work_checkpoint",
        {"active_gap_id": "PX-GAP-0002", "learned": "Switch admitted.", "next_action": "Implement a hash-bound editor sidecar.", "previous_checkpoint_event_id": second["event_id"], "newly_discovered_gap_ids": [], "unresolved_branch_gap_ids": ["PX-GAP-0001", "PX-GAP-0003"], "evidence": evidence()},
        actor="test",
    )
    assert incoming["payload"]["previous_checkpoint_event_id"] == second["event_id"]


def test_closed_active_card_can_emit_one_outgoing_handoff_but_cannot_admit_work(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    closed_card = card("PX-GAP-0001")
    closed_card["completion_evidence"] = ["receipt:closed"]
    closed_card["interaction_chain"] = {
        stage: {
            "state": "present",
            "detail": f"Exact closed-card handoff evidence for {stage}.",
            "evidence": ["sha256:" + "a" * 64],
        }
        for stage in blank_interaction_chain()
    }
    append_event(tmp_path, "card_discovered", closed_card, actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    first = append_event(
        tmp_path,
        "work_checkpoint",
        {
            "active_gap_id": "PX-GAP-0001",
            "learned": "Start the exact card.",
            "next_action": "Implement a hash-bound editor sidecar.",
            "unresolved_branch_gap_ids": ["PX-GAP-0002"],
            "newly_discovered_gap_ids": [],
            "evidence": evidence("initial checkpoint"),
        },
        actor="test",
    )
    current = "discovered"
    for target in (
        "reproduced",
        "scoped",
        "approved",
        "implementing",
        "implemented",
        "narrowly_verified",
        "integrated",
        "operationally_verified",
        "closed",
    ):
        payload = transition_payload("PX-GAP-0001", current, target)
        if target == "closed":
            payload["closure_evidence"] = [
                {
                    "reference": "sha256:" + "b" * 64,
                    "claim": "Exact immutable closed-card handoff evidence.",
                }
            ]
        append_event(
            tmp_path,
            "card_transition",
            payload,
            actor="test",
        )
        current = target
    append_event(
        tmp_path,
        "card_annotated",
        {
            "gap_id": "PX-GAP-0001",
            "note": "Declare the closed-card handoff.",
            "patch": {"next_action": "Switch to PX-GAP-0002."},
            "evidence": evidence("handoff declaration"),
        },
        actor="test",
    )
    with pytest.raises(ValueError, match="explicit outgoing handoff"):
        append_event(
            tmp_path,
            "work_checkpoint",
            {
                "active_gap_id": "PX-GAP-0001",
                "learned": "Closed without a target.",
                "next_action": "Switch to PX-GAP-0002.",
                "previous_checkpoint_event_id": first["event_id"],
                "unresolved_branch_gap_ids": ["PX-GAP-0002"],
                "newly_discovered_gap_ids": [],
                "evidence": evidence("missing target"),
            },
            actor="test",
        )
    outgoing = append_event(
        tmp_path,
        "work_checkpoint",
        {
            "active_gap_id": "PX-GAP-0001",
            "learned": "The active card is closed.",
            "next_action": "Switch to PX-GAP-0002.",
            "previous_checkpoint_event_id": first["event_id"],
            "unresolved_branch_gap_ids": ["PX-GAP-0002"],
            "newly_discovered_gap_ids": [],
            "switching_to": "PX-GAP-0002",
            "evidence": evidence("closed outgoing handoff"),
        },
        actor="test",
    )
    with pytest.raises(ValueError, match="known non-closed card"):
        append_event(
            tmp_path,
            "work_admitted",
            {
                "gap_id": "PX-GAP-0001",
                "checkpoint_event_id": outgoing["event_id"],
                "effect": "write",
                "scope": ["runtime/owner.py"],
                "authority": "test authority",
                "expected_effect": "must remain refused",
                "rollback": "none required",
                "evidence": evidence("refused admission"),
            },
            actor="test",
        )
    incoming = append_event(
        tmp_path,
        "work_checkpoint",
        {
            "active_gap_id": "PX-GAP-0002",
            "learned": "Closed-card handoff admitted.",
            "next_action": "Implement a hash-bound editor sidecar.",
            "previous_checkpoint_event_id": outgoing["event_id"],
            "unresolved_branch_gap_ids": [],
            "newly_discovered_gap_ids": [],
            "evidence": evidence("incoming handoff"),
        },
        actor="test",
    )
    assert incoming["payload"]["active_gap_id"] == "PX-GAP-0002"


def test_compact_snapshot_authenticates_projection_and_ledger_head(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    snapshot = read_snapshot(tmp_path)
    assert snapshot["event_count"] == 2
    assert snapshot["ledger_size_bytes"] > 0
    assert len(snapshot["projection_sha256"]) == 64
    path = tmp_path / "registry/operational_gap_ledger.snapshot.json"
    text = path.read_text(encoding="utf-8").replace('"event_count": 2', '"event_count": 3')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot hash is invalid"):
        read_snapshot(tmp_path)


def test_incremental_checkpoint_projection_equals_full_replay(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    append_event(
        tmp_path,
        "card_annotated",
        {
            "gap_id": "PX-GAP-0001",
            "note": "Retain an incremental annotation.",
            "evidence": evidence("annotation"),
            "patch": {"next_action": "Exercise the repaired append path."},
        },
        actor="test",
    )
    cached = read_snapshot(tmp_path)
    cached.pop("ledger_size_bytes")
    cached.pop("projection_sha256")
    assert cached == project_events(read_events(tmp_path))


def test_warm_append_never_replays_or_rewrites_existing_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    path = tmp_path / "registry/operational_gap_ledger.jsonl"
    before = path.read_bytes()
    monkeypatch.setattr(
        ledger,
        "_read_events_unlocked",
        lambda *_args: (_ for _ in ()).throw(AssertionError("warm append replayed")),
    )
    event = append_event(tmp_path, "card_discovered", card(), actor="test")
    after = path.read_bytes()
    encoded = json.dumps(
        event, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    assert after[: len(before)] == before
    assert after[len(before) :] == encoded


def test_batch_append_uses_one_snapshot_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    original = ledger._write_snapshot_unlocked
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_write_snapshot_unlocked", counted)
    events = append_events(
        tmp_path,
        [
            {"event_type": "card_discovered", "payload": card("PX-GAP-0001"), "actor": "batch"},
            {"event_type": "card_discovered", "payload": card("PX-GAP-0002"), "actor": "batch"},
        ],
    )
    assert len(events) == 2
    assert calls == [1]
    assert project_events(read_events(tmp_path))["event_count"] == 3


def test_default_dashboard_uses_compact_head_without_full_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    monkeypatch.setattr(
        ledger,
        "read_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full snapshot loaded")),
    )
    monkeypatch.setattr(
        ledger,
        "FileLock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dashboard acquired mutating lease")),
    )
    page = _operational_punch_cards(tmp_path, limit=1)
    assert page["count"] == 1
    assert page["cards"][0]["id"] == "PX-GAP-0001"
    assert page["integrity_basis"]["kind"] == "incremental_from_verified_checkpoint"


def test_same_length_earlier_mutation_invalidates_checkpoint_and_full_replay(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    path = tmp_path / "registry/operational_gap_ledger.jsonl"
    original = path.read_bytes()
    changed = original.replace(b'"actor":"test"', b'"actor":"best"', 1)
    assert len(changed) == len(original) and changed != original
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="checkpoint .*stale|checkpoint is unavailable"):
        read_head(tmp_path)
    with pytest.raises(ValueError, match="invalid content hash"):
        project_events(read_events(tmp_path))


def test_torn_tail_is_retained_in_receipt_before_recovery(tmp_path: Path) -> None:
    initialize(tmp_path)
    path = tmp_path / "registry/operational_gap_ledger.jsonl"
    torn = b'{"event_type":"card_discovered"'
    with path.open("ab", buffering=0) as handle:
        handle.write(torn)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    snapshot = project_events(read_events(tmp_path))
    assert snapshot["cards"]["PX-GAP-0001"]["current_state"] == "discovered"
    receipts = list((tmp_path / "evidence/operational-gap-ledger/recovery").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["action"] == "quarantined_torn_uncommitted_suffix"
    assert base64.b64decode(receipt["suffix_base64"]) == torn


def test_snapshot_and_compact_head_bounds_fail_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    path = tmp_path / "registry/operational_gap_ledger.jsonl"
    initial_size = path.stat().st_size
    monkeypatch.setattr(ledger, "MAX_SNAPSHOT_BYTES", 1)
    with pytest.raises(ValueError, match="snapshot byte bound"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert path.stat().st_size == initial_size
    monkeypatch.setattr(ledger, "MAX_SNAPSHOT_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(ledger, "MAX_HEAD_BYTES", 1)
    with pytest.raises(ValueError, match="compact head byte bound"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert path.stat().st_size == initial_size


def test_subprocess_writers_preserve_sequence_and_hash_chain(tmp_path: Path) -> None:
    initialize(tmp_path)
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(process_discover, [(str(tmp_path), index) for index in range(1, 5)]))
    events = read_events(tmp_path)
    snapshot = project_events(events)
    assert [event["sequence"] for event in events] == list(range(1, 6))
    assert snapshot["event_count"] == 5
    assert read_snapshot(tmp_path)["head_event_sha256"] == snapshot["head_event_sha256"]


def test_full_replay_rejects_transition_that_bypasses_reopen_admission(
    tmp_path: Path,
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="test")
    current = "discovered"
    verified = None
    for state in PRIMARY_STATES[1:7]:
        verified = append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", current, state), actor="test")
        current = state
    append_event(
        tmp_path,
        "card_transition",
        {
            "gap_id": "PX-GAP-0001",
            "from_state": "narrowly_verified",
            "to_state": "reopened",
            "reason": "Contradictory evidence arrived.",
            "reopen_reason": "The reproduction was incomplete.",
            "regression_strengthening": ["add installed-host case"],
            "contradicted_transition_event_sha256": verified["event_sha256"],
            "evidence": evidence("contradiction"),
        },
        actor="test",
    )
    events = read_events(tmp_path)
    events[-1]["payload"].pop("regression_strengthening")
    events[-1]["event_sha256"] = ledger._digest(ledger._event_body(events[-1]))
    with pytest.raises(ValueError, match="reopened requires regression_strengthening"):
        project_events(events)


def test_typed_surface_refuses_legacy_add_and_accepts_typed_add(tmp_path: Path) -> None:
    initialize(tmp_path)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]},
        actor="test",
    )
    previous = hashlib.sha256(json.dumps(["save"], separators=(",", ":")).encode()).hexdigest()
    append_event(
        tmp_path,
        "surface_inventory_revised",
        {"surface_id": "workflow-studio", "previous_controls_sha256": previous, "controls": [{"control_id": "save", "kind": "action", "label": "Save", "source_refs": ["ui.js:1"]}], "retired_controls": [], "source_files": ["ui.js"], "reason": "Adopt typed inventory.", "evidence": evidence("typed")},
        actor="test",
    )
    before = len(read_events(tmp_path))
    with pytest.raises(ValueError, match="control entries must be objects"):
        append_event(tmp_path, "surface_controls_added", {"surface_id": "workflow-studio", "controls": ["reload"], "evidence": evidence()}, actor="test")
    assert len(read_events(tmp_path)) == before
    append_event(
        tmp_path,
        "surface_controls_added",
        {"surface_id": "workflow-studio", "controls": [{"control_id": "reload", "kind": "action", "label": "Reload", "source_refs": ["ui.js:2"]}], "evidence": evidence("typed addition")},
        actor="test",
    )
    surface = read_snapshot(tmp_path)["surfaces"]["workflow-studio"]
    assert surface["known_controls"] == ["reload", "save"]
    assert surface["control_records"]["reload"]["kind"] == "action"


def test_recovery_source_bound_is_enforced_before_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    path = tmp_path / "registry/operational_gap_ledger.jsonl"
    monkeypatch.setattr(ledger, "MAX_LEDGER_BYTES", path.stat().st_size - 1)
    with pytest.raises(ValueError, match="physical-file bound"):
        append_event(tmp_path, "card_discovered", card(), actor="test")
    assert not (tmp_path / "evidence/operational-gap-ledger/recovery").exists()


def test_dashboard_race_returns_coherent_or_typed_recovery_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    import threading
    import runtime.operational_gap_ledger as ledger

    initialize(tmp_path)
    original = ledger._write_bytes_atomically
    publication_started = threading.Event()

    def delayed(target, data):
        if target.name == ledger.SNAPSHOT_RELATIVE.name:
            publication_started.set()
            time.sleep(0.05)
        return original(target, data)

    monkeypatch.setattr(ledger, "_write_bytes_atomically", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(append_event, tmp_path, "card_discovered", card(), actor="writer")
        assert publication_started.wait(2)
        during = _operational_punch_cards(tmp_path)
        future.result(timeout=5)
    after = _operational_punch_cards(tmp_path)
    assert during["source_status"] in {"checkpoint_stale", "recovery_required"}
    assert during["cards"] == []
    assert after["source_status"] == "open"
    assert after["cards"][0]["id"] == "PX-GAP-0001"


def test_incremental_and_full_replay_match_across_every_event_type(tmp_path: Path) -> None:
    def exact() -> None:
        cached = read_snapshot(tmp_path)
        cached.pop("ledger_size_bytes")
        cached.pop("projection_sha256")
        assert cached == project_events(read_events(tmp_path))

    initialize(tmp_path)
    exact()
    append_event(tmp_path, "expected_inventory_registered", {"inventory_id": "expected-1", "source": "inventory-a.json", "source_sha256": "a" * 64, "surfaces": [{"surface_id": "workflow-studio", "expected_control_count": 2, "expected_controls_sha256": "b" * 64}]}, actor="test")
    exact()
    append_event(tmp_path, "surface_registered", {"surface_id": "workflow-studio", "name": "Workflow Studio", "source_files": ["ui.js"], "known_controls": ["save"], "owner": "ui", "inventory_evidence": ["ui.js"]}, actor="test")
    exact()
    append_event(tmp_path, "surface_controls_added", {"surface_id": "workflow-studio", "controls": ["reload"], "evidence": evidence("legacy addition before typed revision")}, actor="test")
    exact()
    previous = hashlib.sha256(json.dumps(["reload", "save"], separators=(",", ":")).encode()).hexdigest()
    typed = [
        {"control_id": "reload", "kind": "action", "label": "Reload", "source_refs": ["ui.js:2"]},
        {"control_id": "save", "kind": "action", "label": "Save", "source_refs": ["ui.js:1"]},
    ]
    append_event(tmp_path, "surface_inventory_revised", {"surface_id": "workflow-studio", "previous_controls_sha256": previous, "controls": typed, "retired_controls": [], "source_files": ["ui.js"], "reason": "Adopt typed controls.", "evidence": evidence("typed")}, actor="test")
    exact()
    append_event(tmp_path, "surface_alias_registered", {"alias": "workflow-builder", "surface_id": "workflow-studio"}, actor="test")
    exact()
    append_event(tmp_path, "card_discovered", card("PX-GAP-0001"), actor="test")
    append_event(tmp_path, "card_discovered", card("PX-GAP-0002"), actor="test")
    exact()
    append_event(tmp_path, "card_annotated", {"gap_id": "PX-GAP-0001", "note": "Attach current owner.", "evidence": evidence("owner"), "patch": {"assigned_owner": "test-owner"}}, actor="test")
    exact()
    append_event(tmp_path, "card_transition", transition_payload("PX-GAP-0001", "discovered", "reproduced"), actor="test")
    exact()
    append_event(tmp_path, "control_disposition", {"surface_id": "workflow-studio", "control_id": "save", "disposition": "gap", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("save gap")}, actor="test")
    append_event(tmp_path, "control_disposition", {"surface_id": "workflow-studio", "control_id": "reload", "disposition": "operational", "gap_ids": [], "evidence": evidence("reload works"), "observation": control_observation()}, actor="test")
    exact()
    append_event(tmp_path, "surface_examined", {"surface_id": "workflow-studio", "outcome": "gap", "gap_ids": ["PX-GAP-0001"], "examined_controls": ["save", "reload"], "evidence": evidence("walk")}, actor="test")
    exact()
    append_event(tmp_path, "report_registered", {"report_id": "review-all", **write_report(tmp_path, "review.json", ["finding-1"])}, actor="reviewer")
    append_event(tmp_path, "report_finding_reconciled", {"report_id": "review-all", "finding_id": "finding-1", "disposition": "card", "gap_ids": ["PX-GAP-0001"], "evidence": evidence("reconciled")}, actor="test")
    exact()
    append_event(tmp_path, "card_relationship", {"parent_gap_id": "PX-GAP-0001", "child_gap_id": "PX-GAP-0002", "relationship": "child", "evidence": evidence("branch")}, actor="test")
    append_event(tmp_path, "work_checkpoint", {"active_gap_id": "PX-GAP-0001", "learned": "Branch retained.", "next_action": "Implement a hash-bound editor sidecar.", "unresolved_branch_gap_ids": ["PX-GAP-0002"], "newly_discovered_gap_ids": [], "evidence": evidence("checkpoint")}, actor="test")
    exact()
    append_event(tmp_path, "expected_inventory_revised", {"inventory_id": "expected-2", "source": "inventory-b.json", "source_sha256": "d" * 64, "previous_source_sha256": "a" * 64, "surfaces": [{"surface_id": "workflow-studio", "expected_control_count": 2, "expected_controls_sha256": "e" * 64}]}, actor="test")
    exact()


def test_progress_cli_uses_bounded_checkpoint_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.operational_gap_ledger as command

    initialize(tmp_path)
    monkeypatch.setattr(
        command,
        "write_snapshot",
        lambda *_args: (_ for _ in ()).throw(AssertionError("progress replayed ledger")),
    )
    monkeypatch.setattr(
        "sys.argv", ["operational_gap_ledger", "--root", str(tmp_path), "progress"]
    )
    assert command.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["gaps_discovered"] == 0


def test_operator_cli_exposes_disposition_revision_and_admission_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.operational_gap_ledger as command

    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        command,
        "append_event",
        lambda _root, event_type, payload, **_kwargs: calls.append((event_type, payload)) or {"event_type": event_type},
    )
    monkeypatch.setattr(
        "sys.argv",
        ["operational_gap_ledger", "--root", str(tmp_path), "revise-disposition", "--payload", '{"surface_id":"s"}'],
    )
    assert command.main() == 0
    capsys.readouterr()
    assert calls == [("control_disposition_revised", {"surface_id": "s"})]

    monkeypatch.setattr(
        command,
        "append_transition_admission_backfill",
        lambda _root, payload, **_kwargs: calls.append(("transition_admission_backfilled", payload)) or {"event_type": "transition_admission_backfilled"},
    )
    monkeypatch.setattr(
        "sys.argv",
        ["operational_gap_ledger", "--root", str(tmp_path), "backfill-transition-admission", "--payload", '{"finding_id":"f"}'],
    )
    assert command.main() == 0
    capsys.readouterr()
    assert calls[-1] == ("transition_admission_backfilled", {"finding_id": "f"})
