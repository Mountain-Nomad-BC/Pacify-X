from __future__ import annotations

import json
from pathlib import Path

from runtime.contracts import validate_instance
from runtime.cli import main
from runtime.knowledge_refinery import (
    DECISIONS,
    audit_graph,
    assess_calibration_proposal,
    certify_refinery_run,
    classify_novelty,
    plan_merges,
    portable_inventory,
    evaluate_retrieval,
    stage_merge_plan,
    validate_refinery_orchestration,
)


ROOT = Path(__file__).parents[1]


def artifact(identifier: str, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identifier,
        "title": "Deploy Service",
        "description": "Deploy a service with rollback",
        "capabilities": ["deployment", "rollback"],
        "mechanisms": ["container"],
        "inputs": ["application"],
        "outputs": ["service"],
        "failure_modes": ["failed deployment"],
        "invariants": ["rollback available"],
        "evidence_quality": 0.8,
        "validation_coverage": 0.8,
    }
    value.update(updates)
    return value


def test_inventory_is_portable_hash_bound_and_redacts_secret_values(
    tmp_path: Path,
) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / "safe.md").write_text("same\n", encoding="utf-8")
    (two / "safe.md").write_text("same\n", encoding="utf-8")
    assert (
        portable_inventory(one)["content_sha256"]
        == portable_inventory(two)["content_sha256"]
    )
    secret = "abcdefghijklmnop123456789"
    (one / "unsafe.txt").write_text(f"api_key={secret}\n", encoding="utf-8")
    report = portable_inventory(one)
    assert report["valid"] is False
    assert report["secret_values_recorded"] is False
    assert secret not in json.dumps(report)
    validate_instance(
        report, ROOT / "contracts/knowledge_refinery/portable-inventory.schema.json"
    )


def test_all_seven_novelty_outcomes_are_reachable_and_exactly_one_per_candidate() -> (
    None
):
    target = artifact("target")
    cases = {
        "DUPLICATE": (artifact("target"), target),
        "ENRICH": (artifact("enrich"), target),
        "VARIANT": (
            artifact("variant", description="other", failure_modes=[], invariants=[]),
            target,
        ),
        "CONFLICT": (artifact("conflict", conflicts_with=["target"]), target),
        "SUPERSEDE": (
            artifact(
                "supersede",
                title="Different",
                description="Expanded",
                capabilities=["new"],
                mechanisms=["new"],
                inputs=["new"],
                outputs=["new"],
                failure_modes=["new"],
                invariants=["new"],
                supersedes=["target"],
                evidence_quality=1.0,
                validation_coverage=1.0,
            ),
            artifact(
                "target",
                description="",
                capabilities=[],
                mechanisms=[],
                inputs=[],
                outputs=[],
                failure_modes=[],
                invariants=[],
                evidence_quality=0.0,
                validation_coverage=0.0,
            ),
        ),
        "NOVEL": (
            artifact(
                "novel",
                title="Unrelated Quantum Ledger",
                description="orthogonal proof",
                capabilities=["unrelated"],
                mechanisms=["other"],
                inputs=[],
                outputs=[],
                failure_modes=[],
                invariants=[],
            ),
            target,
        ),
        "REVIEW": (
            artifact(
                "review",
                mechanisms=["container"],
                inputs=[],
                outputs=[],
                failure_modes=[],
                invariants=[],
            ),
            target,
        ),
    }
    observed = {}
    for expected, (candidate, existing) in cases.items():
        report = classify_novelty([candidate], [existing])
        observed[expected] = report["decisions"][0]["decision"]
        assert report["candidate_count"] == report["decision_count"] == 1
    assert observed == {key: key for key in DECISIONS}


def test_ambiguous_targets_abstain_to_manual_review() -> None:
    candidate = artifact("candidate")
    first = artifact("first")
    second = artifact("second")
    decision = classify_novelty([candidate], [first, second])["decisions"][0]
    assert decision["decision"] == "REVIEW"
    assert decision["manual_review_required"] is True


def test_merge_plan_has_one_non_destructive_action_per_decision() -> None:
    report = classify_novelty(
        [artifact("target"), artifact("new", title="Other", capabilities=["other"])],
        [artifact("target")],
    )
    plan = plan_merges(report, {"target": "a" * 64})
    assert plan["valid"]
    assert (
        plan["candidate_count"] == plan["decision_count"] == plan["action_count"] == 2
    )
    assert all(
        item["canonical_write"] is False and item["hard_delete"] is False
        for item in plan["actions"]
    )
    validate_instance(
        plan, ROOT / "contracts/knowledge_refinery/merge-plan.schema.json"
    )


def test_graph_audit_catches_missing_endpoints_duplicates_self_edges_and_cycles() -> (
    None
):
    edges = [
        {"source": "a", "relation": "depends-on", "target": "b"},
        {"source": "b", "relation": "depends-on", "target": "a"},
        {"source": "a", "relation": "depends-on", "target": "b"},
        {"source": "a", "relation": "related-to", "target": "missing"},
        {"source": "a", "relation": "related-to", "target": "a"},
    ]
    result = audit_graph(["a", "b"], edges)
    assert result["valid"] is False
    assert any("forbidden cycle" in item for item in result["errors"])
    assert any("duplicate edge" in item for item in result["errors"])
    validate_instance(
        result, ROOT / "contracts/knowledge_refinery/graph-audit.schema.json"
    )


def test_stage_plan_is_review_gated_project_local_and_inert(tmp_path: Path) -> None:
    state = tmp_path / ".engineering-bootstrap/project-management/state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}\n", encoding="utf-8")
    novelty = classify_novelty([artifact("target")], [artifact("target")])
    plan = plan_merges(novelty, {"target": "a" * 64})
    preview = stage_merge_plan(tmp_path, plan, approval_evidence=[])
    assert preview["valid"] is False and preview["applied"] is False
    applied = stage_merge_plan(
        tmp_path, plan, approval_evidence=["review-1"], apply=True
    )
    assert applied["valid"] and applied["applied"]
    payload = json.loads((tmp_path / applied["receipt"]).read_text(encoding="utf-8"))
    assert payload["canonical_writes_performed"] is False
    assert payload["authority_granted"] is False


def test_refinery_workflow_is_executable() -> None:
    result = validate_refinery_orchestration(ROOT)
    assert result["valid"], result["errors"]


def test_retrieval_forbidden_hits_and_holdout_degradation_block_calibration() -> None:
    cases = [{"id": "one", "expected_ids": ["safe"], "forbidden_ids": ["unsafe"]}]
    baseline = evaluate_retrieval(cases, {"one": ["safe"]})
    degraded = evaluate_retrieval(cases, {"one": ["unsafe"]})
    assert baseline["valid"] is True and degraded["valid"] is False
    rejected = assess_calibration_proposal(
        baseline,
        baseline,
        degraded,
        degraded,
        train_case_ids=["train"],
        holdout_case_ids=["holdout"],
    )
    assert rejected["accepted"] is False
    assert rejected["automatic_deployment"] is False


def test_certification_requires_all_green_components() -> None:
    green = {"valid": True}
    components = {
        "inventory": green,
        "novelty": green,
        "merge_plan": {
            "valid": True,
            "candidate_count": 1,
            "decision_count": 1,
            "action_count": 1,
        },
        "graph": green,
        "retrieval": {"valid": True, "forbidden_hit_count": 0},
        "calibration": {"valid": True, "accepted": True},
    }
    assert certify_refinery_run(components)["status"] == "PASS"
    components["graph"] = {"valid": False}
    assert certify_refinery_run(components)["status"] == "FAIL"


def test_refinery_cli_inventory_and_validate(tmp_path: Path, capsys) -> None:
    (tmp_path / "source.md").write_text("bounded knowledge\n", encoding="utf-8")
    assert (
        main(["--root", str(ROOT), "refinery", "inventory", "--source", str(tmp_path)])
        == 0
    )
    inventory = json.loads(capsys.readouterr().out)
    assert inventory["file_count"] == 1
    assert main(["--root", str(ROOT), "refinery", "validate"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
