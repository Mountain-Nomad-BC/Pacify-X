from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from builders.adapter_builder import (
    AdapterRequest,
    FieldContract,
    TypeContract,
    propose_adapter,
    transform,
)
from builders.common import BuilderError, DuplicateAssetError, GapNotProvenError, write_proposal
from builders.orchestration_builder import (
    OrchestrationRequest,
    ResourceBudget,
    WorkflowStep,
    propose_orchestration,
)
from builders.repair_pattern_builder import (
    RepairPatternRequest,
    RepairVariant,
    propose_repair_pattern,
)
from builders.skill_builder import SkillRequest, propose_skill
from builders.test_evidence_builder import TestCase, TestEvidenceRequest, propose_test_evidence


def capability(
    capability_id: str,
    consumes: tuple[str, ...],
    provides: tuple[str, ...],
    *,
    effects: tuple[str, ...] = ("read_local",),
    dependencies: tuple[str, ...] = (),
    calls: int = 1,
    seconds: int = 2,
) -> dict[str, object]:
    return {
        "id": capability_id,
        "status": "active",
        "consumes": list(consumes),
        "provides": list(provides),
        "effects": list(effects),
        "dependencies": list(dependencies),
        "conflicts": [],
        "cost": {"max_tool_calls": calls},
        "latency": {"max_seconds": seconds},
        "validation": {"passed": 2, "failed": 0},
        "evidence": {"status": "current"},
    }


class SkillBuilderTests(unittest.TestCase):
    def request(self, **changes: object) -> SkillRequest:
        values: dict[str, object] = {
            "capability_id": "new-capability",
            "purpose": "Create a bounded local report",
            "provides": ("local report",),
            "consumes": ("request",),
            "effects": ("read_local",),
            "source_references": ("reference/design.md",),
            "test_requirements": ("positive", "negative"),
            "validation_evidence": ("focused suite",),
        }
        values.update(changes)
        return SkillRequest(**values)

    def test_missing_skill_produces_bounded_candidate_proposal(self) -> None:
        proposal = propose_skill(self.request(), [])
        template = proposal["body"]["skill_template"]
        self.assertEqual(proposal["status"], "candidate")
        self.assertFalse(proposal["auto_activate"])
        self.assertTrue(proposal["body"]["gap_check"]["registry_gap_proven"])
        self.assertEqual(template["io_contract"]["provides"], ["local report"])
        self.assertTrue(template["tests"])
        self.assertTrue(template["validation_evidence"])

    def test_duplicate_or_already_filled_gap_is_rejected(self) -> None:
        with self.assertRaises(DuplicateAssetError):
            propose_skill(self.request(), [{"id": "new-capability", "provides": []}])
        with self.assertRaises(GapNotProvenError):
            propose_skill(
                self.request(),
                [{"id": "existing", "provides": ["local report"]}],
            )

    def test_restricted_source_requires_explicit_clean_room_status(self) -> None:
        with self.assertRaisesRegex(BuilderError, "clean_room"):
            propose_skill(self.request(restricted_sources=True), [])
        proposal = propose_skill(
            self.request(restricted_sources=True, clean_room=True), []
        )
        self.assertTrue(proposal["body"]["skill_template"]["provenance"]["clean_room"])


class OrchestrationBuilderTests(unittest.TestCase):
    def test_resolves_io_dependencies_and_adds_approval_evidence_and_budget(self) -> None:
        contracts = [
            capability("normalize", ("request",), ("normalized",)),
            capability(
                "persist",
                ("normalized",),
                ("receipt",),
                effects=("read_local", "write_workspace"),
            ),
        ]
        request = OrchestrationRequest(
            "save-report",
            ("request",),
            ("receipt",),
            (WorkflowStep("save", "persist"), WorkflowStep("prepare", "normalize")),
            ("budget exhausted", "approval denied"),
            ResourceBudget(2, 4),
        )

        proposal = propose_orchestration(request, contracts)
        body = proposal["body"]

        self.assertEqual(body["resolved_order"], ["prepare", "save"])
        self.assertEqual(body["workflow"]["steps"][1]["depends_on"], ["prepare"])
        self.assertEqual(body["approval_gates"][0]["before_step"], "save")
        self.assertEqual(len(body["evidence_steps"]), 2)
        self.assertTrue(body["budget_analysis"]["known_before_execution"])
        self.assertTrue(body["dag_validation"]["valid"])

    def test_invalid_graph_unvalidated_capability_and_insufficient_budget_fail(self) -> None:
        valid = capability("normalize", ("request",), ("normalized",))
        invalid = {**valid, "id": "draft", "status": "candidate"}
        with self.assertRaisesRegex(BuilderError, "not admitted"):
            propose_orchestration(
                OrchestrationRequest(
                    "draft-flow",
                    ("request",),
                    ("normalized",),
                    (WorkflowStep("draft", "draft"),),
                    ("failure",),
                    ResourceBudget(2, 4),
                ),
                [invalid],
            )
        with self.assertRaisesRegex(BuilderError, "cycle"):
            propose_orchestration(
                OrchestrationRequest(
                    "cycle-flow",
                    ("request",),
                    ("normalized",),
                    (WorkflowStep("one", "normalize", ("two",)), WorkflowStep("two", "normalize", ("one",))),
                    ("failure",),
                    ResourceBudget(3, 6),
                ),
                [valid],
            )
        with self.assertRaisesRegex(BuilderError, "max_tool_calls"):
            propose_orchestration(
                OrchestrationRequest(
                    "small-budget",
                    ("request",),
                    ("normalized",),
                    (WorkflowStep("one", "normalize"),),
                    ("failure",),
                    ResourceBudget(0, 4),
                ),
                [valid],
            )


class AdapterBuilderTests(unittest.TestCase):
    def request(self) -> AdapterRequest:
        return AdapterRequest(
            "user-adapter",
            TypeContract(
                "source-user",
                (FieldContract("user_name", "string"), FieldContract("age", "integer")),
            ),
            TypeContract(
                "target-user",
                (FieldContract("name", "string"), FieldContract("years", "integer")),
            ),
            (("user_name", "name"), ("age", "years")),
            ("contracts/user.json",),
        )

    def test_adapter_is_one_contract_strict_mapping_and_registry_visible(self) -> None:
        request = self.request()
        proposal = propose_adapter(request, [])
        adapter = proposal["body"]["adapter"]
        self.assertTrue(adapter["transforms_exactly_one_contract"])
        self.assertFalse(adapter["business_logic_allowed"])
        self.assertEqual(
            transform(request, {"user_name": "Ada", "age": 37}),
            {"name": "Ada", "years": 37},
        )
        self.assertEqual(proposal["body"]["registry_candidate"]["visible_as"], "candidate")

    def test_invalid_input_and_incompatible_mapping_fail_clearly(self) -> None:
        with self.assertRaisesRegex(BuilderError, "invalid input type"):
            transform(self.request(), {"user_name": "Ada", "age": "unknown"})
        bad = AdapterRequest(
            "bad-adapter",
            TypeContract("source", (FieldContract("value", "integer"),)),
            TypeContract("target", (FieldContract("value", "string"),)),
            (("value", "value"),),
            ("contract.json",),
        )
        with self.assertRaisesRegex(BuilderError, "incompatible"):
            propose_adapter(bad, [])


class RepairPatternBuilderTests(unittest.TestCase):
    def test_structured_pattern_preserves_lineage_diagnosis_validation_and_rollback(self) -> None:
        proposal = propose_repair_pattern(
            RepairPatternRequest(
                "cache-repair",
                ("stale response",),
                "cache invalidation omitted",
                ("restart repeatedly",),
                ("reproduce", "invalidate bounded key", "verify"),
                ("focused regression",),
                ("restore previous cache entry",),
                ("test receipt",),
                ("incident-42",),
                (RepairVariant("python", ("validate key", "invalidate key"), "Python service owns the cache"),),
            )
        )
        pattern = proposal["body"]["pattern"]
        self.assertEqual(pattern["purpose"], "diagnosis-and-validated-repair")
        self.assertTrue(pattern["source_lineage"])
        self.assertTrue(pattern["validation_tests"])
        self.assertTrue(pattern["rollback"])
        self.assertFalse(pattern["blind_copying_allowed"])

    def test_unsafe_variant_is_quarantined_and_snippet_is_not_activated(self) -> None:
        proposal = propose_repair_pattern(
            RepairPatternRequest(
                "unsafe-repair",
                ("failure",),
                "unsafe manual workaround",
                ("copy command",),
                ("diagnose first",),
                ("safe test",),
                ("restore snapshot",),
                ("review record",),
                ("incident-7",),
                (RepairVariant("python", ("review only",), "Historical comparison", "os.system('danger')"),),
            )
        )
        variant = proposal["body"]["pattern"]["variants"][0]
        self.assertEqual(variant["status"], "quarantined")
        self.assertFalse(variant["activation_allowed"])
        self.assertEqual(variant["snippet"], "[QUARANTINED UNSAFE SNIPPET]")


class TestEvidenceBuilderTests(unittest.TestCase):
    def cases(self, failing: bool = False) -> tuple[TestCase, ...]:
        return (
            TestCase("happy", "positive", {"value": "ok"}, {"status": "ok"}, True),
            TestCase(
                "invalid",
                "negative",
                {"api_key": "should-not-survive"},
                {"status": "blocked"},
                not failing,
                "password=also-private" if failing else "",
            ),
            TestCase("boundary", "effect_boundary", {"effect": "network"}, {"approval": True}, True),
        )

    def test_evidence_is_deterministic_sanitized_and_failures_remain_visible(self) -> None:
        request = TestEvidenceRequest("new-asset", self.cases(failing=True), ("local-test-run",))
        first = propose_test_evidence(request)
        second = propose_test_evidence(request)
        self.assertEqual(first, second)
        text = json.dumps(first)
        self.assertNotIn("should-not-survive", text)
        self.assertNotIn("also-private", text)
        summary = first["body"]["evidence_summary"]
        self.assertEqual(summary["failing_case_ids"], ["invalid"])
        self.assertFalse(first["body"]["admission_gate"]["admission_ready"])

    def test_all_test_classes_are_required_before_proposal(self) -> None:
        with self.assertRaisesRegex(BuilderError, "missing required test kinds"):
            propose_test_evidence(
                TestEvidenceRequest("new-asset", self.cases()[:1], ("local-test-run",))
            )

    def test_proposals_write_only_to_requested_directory_and_never_activate(self) -> None:
        proposal = propose_test_evidence(
            TestEvidenceRequest("new-asset", self.cases(), ("local-test-run",))
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            destination = write_proposal(output, proposal)
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(destination.parent, output)
            self.assertEqual(payload["registry_action"], "proposal_only")
            self.assertFalse(payload["auto_activate"])
            with self.assertRaises(DuplicateAssetError):
                write_proposal(output, proposal)


if __name__ == "__main__":
    unittest.main()
