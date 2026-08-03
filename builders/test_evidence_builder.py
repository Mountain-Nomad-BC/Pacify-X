"""Focused test specifications and sanitized evidence proposals (PC-504)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .common import BuilderError, bounded_unique, canonical_digest, proposal_envelope, require_identifier, sanitize


TEST_KINDS = frozenset({"positive", "negative", "effect_boundary"})


@dataclass(frozen=True, slots=True)
class TestCase:
    __test__ = False

    case_id: str
    kind: str
    inputs: Mapping[str, object]
    expected: Mapping[str, object]
    passed: bool
    failure: str = ""


@dataclass(frozen=True, slots=True)
class TestEvidenceRequest:
    __test__ = False

    asset_id: str
    cases: tuple[TestCase, ...]
    evidence_sources: tuple[str, ...]


def propose_test_evidence(request: TestEvidenceRequest) -> dict[str, object]:
    asset_id = require_identifier(request.asset_id, "asset_id")
    cases = bounded_unique(request.cases, "cases", maximum=48)
    sources = bounded_unique(request.evidence_sources, "evidence_sources", maximum=16)
    seen_ids: set[str] = set()
    seen_kinds: set[str] = set()
    case_payloads: list[dict[str, object]] = []
    for case in cases:
        require_identifier(case.case_id, "case_id")
        if case.case_id in seen_ids:
            raise BuilderError(f"duplicate test case id: {case.case_id}")
        if case.kind not in TEST_KINDS:
            raise BuilderError(f"unknown test kind: {case.kind}")
        seen_ids.add(case.case_id)
        seen_kinds.add(case.kind)
        sanitized_inputs = sanitize(case.inputs)
        sanitized_expected = sanitize(case.expected)
        case_payloads.append(
            {
                "id": case.case_id,
                "kind": case.kind,
                "inputs": sanitized_inputs,
                "expected": sanitized_expected,
                "passed": case.passed,
                "failure": sanitize(case.failure),
            }
        )
    missing_kinds = sorted(TEST_KINDS - seen_kinds)
    if missing_kinds:
        raise BuilderError("missing required test kinds: " + ", ".join(missing_kinds))

    case_payloads.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
    failing_ids = sorted(str(item["id"]) for item in case_payloads if not item["passed"])
    summary = {
        "asset_id": asset_id,
        "total": len(case_payloads),
        "passed": len(case_payloads) - len(failing_ids),
        "failed": len(failing_ids),
        "failing_case_ids": failing_ids,
        "required_kinds": sorted(TEST_KINDS),
        "evidence_sources": sorted(sources),
        "sanitized": True,
    }
    summary["evidence_digest"] = canonical_digest({"cases": case_payloads, "summary": summary})
    body = {
        "asset_id": asset_id,
        "tests": case_payloads,
        "evidence_summary": summary,
        "admission_gate": {
            "tests_present": True,
            "all_tests_passed": not failing_ids,
            "admission_ready": not failing_ids,
            "failures_visible": True,
        },
    }
    return proposal_envelope("test-evidence", asset_id, body)
