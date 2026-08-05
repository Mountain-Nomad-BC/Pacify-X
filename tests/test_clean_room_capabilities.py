from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.agent_fleet_controls import (
    admit_inbox_message,
    evaluate_fleet_readiness,
    plan_terminal_session_action,
)
from runtime.backend_capabilities import (
    BACKEND_DOMAINS,
    select_backend_capabilities,
    validate_backend_capability_model,
)
from runtime.behavioral_certification import (
    certify_behavioral_delta,
    compare_shadow_behavior,
)
from runtime.clean_room_capabilities import (
    OPERATIONS,
    run_clean_room_operation,
    validate_clean_room_capability_workflow,
)
from runtime.cli import main
from runtime.durable_state import close_specification_lifecycle, transition_durable_goal
from runtime.memory_remediation import plan_memory_graph_remediation
from runtime.reasoning_controls import (
    compact_communication,
    run_independent_hypothesis_panel,
)


ROOT = Path(__file__).resolve().parents[1]
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def test_independent_hypothesis_panel_converges_and_preserves_dissent() -> None:
    branches = [
        {
            "branch_id": "a",
            "isolated": True,
            "conclusion": "repair",
            "confidence": 0.9,
            "evidence_ids": ["e1"],
        },
        {
            "branch_id": "b",
            "isolated": True,
            "conclusion": "repair",
            "confidence": 0.8,
            "evidence_ids": ["e2"],
        },
        {
            "branch_id": "c",
            "isolated": True,
            "conclusion": "replace",
            "confidence": 0.2,
            "evidence_ids": ["e3"],
        },
    ]
    result = run_independent_hypothesis_panel(branches, convergence_threshold=0.75)
    assert result["converged"] is True
    assert result["selected_conclusion"] == "repair"
    assert result["dissent"] == [
        {
            "branch_id": "c",
            "conclusion": "replace",
            "confidence": 0.2,
            "evidence_ids": ["e3"],
        }
    ]
    assert result["critic"]["private_reasoning_requested"] is False
    correlated = [dict(branch, evidence_ids=["shared"]) for branch in branches]
    assert run_independent_hypothesis_panel(correlated)["converged"] is False


def test_behavioral_delta_requires_negative_gate_and_current_evidence() -> None:
    cases = [
        {
            "id": "p",
            "kind": "positive",
            "baseline_decision": "old",
            "candidate_decision": "new",
            "expected_candidate_decision": "new",
            "evidence_sha256": HASH_A,
        },
        {
            "id": "n",
            "kind": "negative_trigger",
            "baseline_decision": "allow",
            "candidate_decision": "deny",
            "expected_candidate_decision": "deny",
            "evidence_sha256": HASH_B,
        },
        {
            "id": "g",
            "kind": "hard_gate",
            "baseline_decision": "allow",
            "candidate_decision": "require_approval",
            "expected_candidate_decision": "require_approval",
            "evidence_sha256": HASH_C,
        },
    ]
    certificate = certify_behavioral_delta(
        cases, baseline_sha256=HASH_A, candidate_sha256=HASH_B
    )
    assert certificate["certified"] is True
    assert certificate["private_reasoning_collected"] is False
    assert (
        certify_behavioral_delta(
            cases[:1], baseline_sha256=HASH_A, candidate_sha256=HASH_B
        )["certified"]
        is False
    )


def test_communication_budget_preserves_mandatory_records_and_fails_when_too_small() -> (
    None
):
    messages = [
        {"id": "f", "category": "failure", "text": "test failed"},
        {"id": "u", "category": "uncertainty", "text": "cause unknown"},
        {"id": "a", "category": "authority", "text": "write not approved"},
        {"id": "r", "category": "recovery", "text": "restore checkpoint"},
        {
            "id": "e",
            "category": "evidence",
            "text": "log hash",
            "evidence_ids": ["log-1"],
        },
        {"id": "x1", "category": "progress", "text": "scanned", "repeat_key": "scan"},
        {"id": "x2", "category": "progress", "text": "scanned", "repeat_key": "scan"},
    ]
    compacted = compact_communication(messages, max_items=6)
    assert compacted["valid"] is True
    assert {item["category"] for item in compacted["items"]} >= {
        "failure",
        "uncertainty",
        "authority",
        "recovery",
        "evidence",
    }
    assert (
        next(item for item in compacted["items"] if item["category"] == "progress")[
            "repeat_count"
        ]
        == 2
    )
    assert (
        compact_communication(messages, max_items=4)["decision"]
        == "budget_insufficient"
    )


def test_fleet_readiness_and_inbox_enforce_project_identity_cost_and_bounds() -> None:
    agents = [
        {
            "agent_id": "agent-a",
            "project_id": "p1",
            "permissions": ["read"],
            "owner_id": "human-a",
            "heartbeat_age_seconds": 5,
            "reserved_cost": 2.0,
        },
        {
            "agent_id": "agent-b",
            "project_id": "p1",
            "permissions": ["read"],
            "owner_id": "human-b",
            "heartbeat_age_seconds": 10,
            "reserved_cost": 3.0,
        },
    ]
    assert (
        evaluate_fleet_readiness(
            "p1", agents, required_permissions=["read"], total_cost_cap=5
        )["valid"]
        is True
    )
    cross_project = [dict(agents[0], project_id="p2")]
    assert evaluate_fleet_readiness("p1", cross_project)["valid"] is False
    candidate = {
        "message_id": "m1",
        "project_id": "p1",
        "sender_id": "agent-a",
        "body": "done",
    }
    assert (
        admit_inbox_message(
            "p1", [], candidate, allowed_senders=["agent-a"], max_messages=1
        )["valid"]
        is True
    )
    assert (
        admit_inbox_message("p2", [], candidate, allowed_senders=["agent-a"])[
            "decision"
        ]
        == "reject"
    )


def test_memory_remediation_orders_dependencies_and_never_mutates() -> None:
    nodes = [
        {
            "id": "source",
            "project_id": "p1",
            "citations": ["doc:1"],
            "temporal_claims": [{"type": "observed_at", "value": "2026-08-04"}],
        },
        {"id": "derived", "project_id": "p1", "citations": [], "temporal_claims": []},
    ]
    result = plan_memory_graph_remediation(
        "p1", nodes, [("source", "derived")], mutation_approved=True, spend_cap=1.0
    )
    assert result["dependency_order"] == ["source", "derived"]
    assert result["mutated"] is False
    assert result["steps"][0]["apply"] is True
    cross = [dict(nodes[0], project_id="p2")]
    assert plan_memory_graph_remediation("p1", cross, [], spend_cap=0)["valid"] is False


def test_durable_goal_requires_budget_acceptance_evidence_and_repeated_blocker() -> (
    None
):
    base = {
        "goal_id": "g1",
        "project_id": "p1",
        "status": "in_progress",
        "continuation_budget": 2,
        "history": [],
    }
    assert (
        transition_durable_goal(base, "complete", project_id="p1", session_id="s1")[
            "event_applied"
        ]
        is False
    )
    complete = transition_durable_goal(
        base,
        "complete",
        project_id="p1",
        session_id="s1",
        evidence_ids=["test-log"],
        acceptance_results={"tests": True},
    )
    assert complete["status"] == "complete"
    assert (
        transition_durable_goal(
            base, "continue", project_id="p1", session_id="s1", continuation_cost=3
        )["event_applied"]
        is False
    )
    blocked_base = dict(
        base,
        history=[
            {"event": "block", "blocker": "network"},
            {"event": "block", "blocker": "network"},
        ],
    )
    assert (
        transition_durable_goal(
            blocked_base, "block", project_id="p1", session_id="s1", blocker="network"
        )["status"]
        == "blocked"
    )
    with pytest.raises(ValueError, match="project boundary"):
        transition_durable_goal(base, "pause", project_id="p2", session_id="s1")


def test_terminal_adapter_never_executes_without_separate_authority() -> None:
    adapter = {
        "adapter_id": "local-terminal",
        "capabilities": ["inspect", "execute"],
        "project_scoped": True,
    }
    denied = plan_terminal_session_action(adapter, "execute", authority={"read": True})
    assert denied["decision"] == "denied"
    planned = plan_terminal_session_action(
        adapter, "execute", authority={"execute": True}
    )
    assert planned["decision"] == "planned"
    assert planned["executed"] is False
    assert planned["authority_granted"] is False


def _backend_records() -> list[dict[str, object]]:
    return [
        {
            "id": f"local-{domain}",
            "domain": domain,
            "provider_adapter": f"adapters.{domain}",
            "effects": ["read_local"],
            "cost": index,
        }
        for index, domain in enumerate(BACKEND_DOMAINS)
    ]


def test_backend_model_is_vendor_neutral_complete_and_least_effect_routed() -> None:
    records = _backend_records()
    assert validate_backend_capability_model(records)["valid"] is True
    selected = select_backend_capabilities(records, ["data", "payments"])
    assert selected["valid"] is True
    assert [item["domain"] for item in selected["selected"]] == ["data", "payments"]
    assert validate_backend_capability_model(records[:-1])["valid"] is False


def test_shadow_comparison_returns_incumbent_contains_effects_and_honors_kill_switch() -> (
    None
):
    mismatch = compare_shadow_behavior(
        {"answer": 1}, {"answer": 2}, cutover_authorized=True
    )
    assert mismatch["returned_result"] == {"answer": 1}
    assert mismatch["mismatch"] is True
    assert mismatch["cutover_eligible"] is False
    escaped = compare_shadow_behavior(
        "old", "old", candidate_effects=["external_mutation"]
    )
    assert escaped["candidate_observed"] is False
    killed = compare_shadow_behavior("old", "new", kill_switch=True)
    assert killed["candidate_observed"] is False
    assert killed["returned_result"] == "old"


def test_specification_lifecycle_detects_orphans_and_closes_complete_chain() -> None:
    artifacts = [
        {"id": "p", "stage": "principles", "depends_on": []},
        {"id": "s", "stage": "specification", "depends_on": ["p"]},
        {"id": "c", "stage": "clarification", "depends_on": ["s"]},
        {"id": "d", "stage": "design", "depends_on": ["c"]},
        {"id": "t", "stage": "tasks", "depends_on": ["d"]},
        {
            "id": "i",
            "stage": "implementation_evidence",
            "depends_on": ["t"],
            "evidence_sha256": HASH_A,
        },
        {"id": "a", "stage": "acceptance", "depends_on": ["i"], "passed": True},
    ]
    assert close_specification_lifecycle(artifacts)["closed"] is True
    broken = [dict(item) for item in artifacts]
    broken[5]["depends_on"] = []
    assert close_specification_lifecycle(broken)["closed"] is False


def test_clean_room_dispatch_and_workflow_cover_every_operation() -> None:
    validation = validate_clean_room_capability_workflow(ROOT)
    assert validation["valid"], validation["errors"]
    result = run_clean_room_operation(
        "shadow-behavior-comparison",
        {"incumbent_result": "stable", "candidate_result": "stable"},
    )
    assert result["returned_result"] == "stable"
    assert validation["operation_count"] == len(OPERATIONS) == 12


def test_capability_control_cli_is_metadata_first_and_executes_structured_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(ROOT), "capability-control", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["operation_count"] == 12
    assert status["hydrated_skill_bodies"] == 0
    payload = tmp_path / "shadow.json"
    payload.write_text(
        '{"incumbent_result":"stable","candidate_result":"stable"}\n',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(ROOT),
                "capability-control",
                "run",
                "--operation",
                "shadow-behavior-comparison",
                "--input",
                str(payload),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["returned_result"] == "stable"
    assert result["authority_granted"] is False
