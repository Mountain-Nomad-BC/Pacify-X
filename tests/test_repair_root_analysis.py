from __future__ import annotations

import pytest

from runtime.repair_root_analysis import (
    build_discriminating_test_plan,
    group_candidate_roots,
)


FAILURES = (
    {"failure_id": "a", "evidence_refs": ("log:1",), "owners": ("owner:x",), "dependencies": ("dep:1",)},
    {"failure_id": "b", "evidence_refs": ("log:1",), "owners": ("owner:x",), "dependencies": ("dep:1",)},
    {"failure_id": "c", "evidence_refs": ("log:2",), "owners": ("owner:y",), "dependencies": ()},
)


def test_groups_only_exact_shared_evidence_and_remains_unconfirmed():
    first = group_candidate_roots(FAILURES, expected_failure_ids=("a", "b", "c"))
    second = group_candidate_roots(reversed(FAILURES), expected_failure_ids=("c", "b", "a"))
    assert first == second
    assert [row["failure_ids"] for row in first["candidate_groups"]] == [("a", "b"), ("c",)]
    assert all(row["status"] == "candidate_unconfirmed" for row in first["candidate_groups"])
    assert first["mutation_authorized"] is False


def test_omitted_failure_denominator_fails_closed():
    with pytest.raises(ValueError, match="complete unique failure denominator"):
        group_candidate_roots(FAILURES[:2], expected_failure_ids=("a", "b", "c"))


def test_discriminating_plan_has_no_repair_execution_path():
    analysis = group_candidate_roots(FAILURES, expected_failure_ids=("a", "b", "c"))
    plan = build_discriminating_test_plan(analysis)
    assert plan["tests"]
    assert plan["repair_authorized"] is False
    assert plan["execution_primitive"] is None
    with pytest.raises(ValueError, match="unknown candidate"):
        build_discriminating_test_plan(analysis, confirmed_candidate_ids=("guessed",))
