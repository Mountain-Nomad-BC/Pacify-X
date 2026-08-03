"""Golden-query regression certification for metadata-only capability selection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .skill_navigator import CapabilitySummary, navigate


def certify_queries(capabilities: Iterable[CapabilitySummary], cases: Iterable[dict[str, object]]) -> dict[str, object]:
    index = tuple(capabilities)
    results: list[dict[str, object]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        goal = str(case.get("goal", ""))
        maximum = int(case.get("max_candidates", 3))
        constraints = case.get("constraints", {})
        if not isinstance(constraints, dict):
            raise ValueError(f"{case_id}: constraints must be an object")
        first = navigate(goal, index, max_candidates=maximum, constraints=constraints)
        second = navigate(goal, reversed(index), max_candidates=maximum, constraints=constraints)
        returned = [item.capability_id for item in first.candidates]
        expected = {str(value) for value in case.get("must_include", ())}
        forbidden = {str(value) for value in case.get("must_exclude", ())}
        missing = sorted(expected - set(returned))
        violations = sorted(forbidden & set(returned))
        deterministic = first == second
        results.append({
            "id": case_id,
            "passed": not missing and not violations and deterministic,
            "returned": returned,
            "missing_required": missing,
            "forbidden_returned": violations,
            "deterministic": deterministic,
            "index_revision": first.index_revision,
        })
    return {
        "schema_version": "1.0",
        "complete": bool(results) and all(bool(item["passed"]) for item in results),
        "case_count": len(results),
        "passed": sum(bool(item["passed"]) for item in results),
        "failed": sum(not bool(item["passed"]) for item in results),
        "cases": results,
    }


def load_cases(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", ())
    if not isinstance(cases, list) or not all(isinstance(item, dict) for item in cases):
        raise ValueError("golden query cases must be an object list")
    return cases
