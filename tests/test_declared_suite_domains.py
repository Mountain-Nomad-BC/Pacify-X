from collections import Counter
from pathlib import Path

from runtime.declared_suite import (
    describe_outcome,
    list_outcomes,
    plan_outcome,
    run_script_outcome,
    validate_declared_suite,
)


ROOT = Path(__file__).resolve().parents[1]


def test_all_reconstructed_operational_outcomes_have_domain_contracts():
    result = validate_declared_suite(ROOT)
    assert result == {"valid": True, "outcomes": 257, "workflows": 62, "errors": []}
    records = list_outcomes(ROOT)["records"]
    assert Counter(record["kind"] for record in records) == {
        "skill": 134,
        "script": 61,
        "orchestration": 62,
    }
    assert len({record["owner"] for record in records}) == 7
    for record in records:
        described = describe_outcome(ROOT, record["kind"], record["source_id"])
        assert described["valid"]
        assert described["owner"] == record["owner"]
        assert described["contract"]["source_paths"]


def test_every_outcome_has_fail_closed_planning_contract():
    records = list_outcomes(ROOT)["records"]
    valid_input = {
        "target": "bounded-target",
        "constraints": {"effects": ["read_local"]},
        "evidence_context": {},
    }
    for record in records:
        plan = plan_outcome(ROOT, record["kind"], record["source_id"], valid_input)
        assert plan["valid"] and plan["dry_run"]
        assert len(plan["ordered_steps"]) == 5
        assert plan["failure_policy"] and plan["recovery"] and plan["evidence_required"]
        denied = plan_outcome(
            ROOT, record["kind"], record["source_id"], {"target": "bounded-target"}
        )
        assert not denied["valid"]


def test_every_reconstructed_script_is_executable_and_deterministic(tmp_path):
    (tmp_path / "a.txt").write_text("alpha SECRET beta", encoding="utf-8")
    payload = {
        "target": str(tmp_path),
        "constraints": {"effects": ["read_local"]},
        "evidence_context": {},
        "maximum_files": 10,
        "baseline": 10,
        "candidate": 12,
        "candidates": [
            {"id": "a", "metrics": {"quality": 0.8, "cost": -0.2}},
            {"id": "b", "metrics": {"quality": 0.7, "cost": -0.1}},
        ],
        "weights": {"quality": 1.0, "cost": 0.5},
        "text": "alpha SECRET beta",
        "patterns": ["secret"],
        "record": {"id": "x"},
        "required": ["id"],
        "allowed": ["id"],
        "seed": {"id": "seed"},
    }
    scripts = list_outcomes(ROOT, kind="script")["records"]
    assert len(scripts) == 61
    for record in scripts:
        first = run_script_outcome(ROOT, record["source_id"], payload)
        second = run_script_outcome(ROOT, record["source_id"], payload)
        assert first["valid"], (record, first)
        assert first["read_only"]
        assert first["result_sha256"] == second["result_sha256"]
        assert first["owner"] == record["owner"]


def test_unknown_outcomes_and_invalid_script_inputs_fail_closed():
    assert not describe_outcome(ROOT, "skill", "not-real")["valid"]
    denied = run_script_outcome(ROOT, "repo-mapper", {"target": "missing"})
    assert not denied["valid"]
