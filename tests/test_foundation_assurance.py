from __future__ import annotations

import math
import unittest

from runtime.foundation_assurance import (
    ContractSurface,
    RetrievalCase,
    TrainingRecord,
    compare_contract_surfaces,
    evaluate_numeric_shift,
    evaluate_retrieval_readiness,
    gate_model_dataset,
    plan_runtime_surface_validation,
    validate_dimension_steps,
)


class FoundationAssuranceTests(unittest.TestCase):
    def test_contract_comparison_covers_shape_route_owner_and_permission(self) -> None:
        provider = ContractSurface(
            "case",
            "case-service",
            "GET",
            "/cases/{id}",
            {"id": "string", "state": "string"},
            ("id",),
            ("case:read",),
        )
        consumer = ContractSurface(
            "case",
            "client",
            "GET",
            "/cases/{id}",
            {"id": "string"},
            ("id",),
            ("case:read",),
        )
        self.assertEqual(
            compare_contract_surfaces((provider,), (consumer,))["decision"],
            "compatible",
        )
        broken = ContractSurface(
            "case",
            "client",
            "POST",
            "/case",
            {"id": "integer", "missing": "string"},
            ("id", "missing"),
            ("case:admin",),
        )
        report = compare_contract_surfaces((provider,), (broken,))
        self.assertEqual(report["decision"], "incompatible")
        self.assertIn("route_mismatch", {item["kind"] for item in report["findings"]})
        self.assertIn(
            "required_field_missing", {item["kind"] for item in report["findings"]}
        )

    def test_retrieval_gate_uses_recall_mrr_coverage_and_forbidden_boundaries(
        self,
    ) -> None:
        cases = (
            RetrievalCase("one", ("a",), ("private",)),
            RetrievalCase("two", ("b",)),
        )
        ready = evaluate_retrieval_readiness(cases, {"one": ("a",), "two": ("b",)})
        self.assertTrue(ready["activation_allowed"])
        blocked = evaluate_retrieval_readiness(cases, {"one": ("private", "a")})
        self.assertEqual(blocked["decision"], "blocked")
        self.assertIn("forbidden_result_exposed", blocked["reasons"])
        self.assertIn("coverage_below_threshold", blocked["reasons"])

    def test_dataset_gate_detects_rights_privacy_and_split_leakage(self) -> None:
        digest_a, digest_b = "a" * 64, "b" * 64
        good = (
            TrainingRecord(
                "one",
                digest_a,
                "source-one",
                "internal",
                "owner-approved",
                "ok",
                "train",
                "subject-one",
            ),
            TrainingRecord(
                "two",
                digest_b,
                "source-two",
                "internal",
                "owner-approved",
                "ok",
                "test",
                "subject-two",
            ),
        )
        self.assertEqual(
            gate_model_dataset(good, allowed_licenses=("internal",))["decision"],
            "admitted_metadata",
        )
        bad = good + (
            TrainingRecord(
                "three",
                digest_a,
                "source-three",
                "unknown",
                "",
                "ok",
                "test",
                "subject-one",
                True,
                False,
            ),
        )
        report = gate_model_dataset(bad, allowed_licenses=("internal",))
        self.assertEqual(report["decision"], "blocked")
        self.assertTrue(
            any(
                reason.startswith("content_split_leakage")
                for reason in report["reasons"]
            )
        )
        self.assertTrue(
            any(
                reason.startswith("sensitive_use_not_approved")
                for reason in report["reasons"]
            )
        )

    def test_numeric_shift_handles_constant_empty_and_nonfinite_inputs(self) -> None:
        self.assertEqual(
            evaluate_numeric_shift((2, 2), (2, 2))["decision"], "within_threshold"
        )
        self.assertEqual(evaluate_numeric_shift((2, 2), (3, 3))["decision"], "drifted")
        self.assertIn("series_empty", evaluate_numeric_shift((), (1,))["errors"])
        self.assertIn(
            "non_finite_value", evaluate_numeric_shift((1,), (math.nan,))["errors"]
        )

    def test_dimension_validation_never_evaluates_source(self) -> None:
        valid = validate_dimension_steps(
            (
                {
                    "operation": "divide",
                    "left": {"length": 1},
                    "right": {"time": 1},
                    "result": {"length": 1, "time": -1},
                },
            )
        )
        self.assertEqual(valid["decision"], "valid")
        invalid = validate_dimension_steps(
            (
                {
                    "operation": "add",
                    "left": {"length": 1},
                    "right": {"time": 1},
                    "result": {"length": 1},
                },
            )
        )
        self.assertEqual(invalid["decision"], "invalid")

    def test_runtime_surface_plan_orders_checks_and_declares_approval(self) -> None:
        report = plan_runtime_surface_validation(
            (
                {
                    "id": "web",
                    "owner": "web-team",
                    "checks": ("interaction", "config", "health", "build", "unit"),
                    "mutating": False,
                },
            )
        )
        self.assertEqual(report["decision"], "planned")
        self.assertEqual(
            report["surfaces"][0]["checks"],
            ("config", "unit", "build", "health", "interaction"),
        )
        self.assertTrue(report["surfaces"][0]["approval_required"])
        self.assertFalse(report["execution_performed"])


if __name__ == "__main__":
    unittest.main()
