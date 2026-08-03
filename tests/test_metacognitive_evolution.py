from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.metacognitive_evolution.facade import (
    describe_capability,
    list_capabilities,
    run_operation,
    validate_layer,
)


ROOT = Path(__file__).resolve().parents[1]


class MetacognitiveEvolutionTests(unittest.TestCase):
    def test_denominators_and_lazy_metadata(self) -> None:
        result = validate_layer(ROOT)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["counts"], {"capabilities": 50, "owners": 50, "formulas": 79, "policies": 9, "workflows": 15, "schemas": 14})
        listing = list_capabilities(ROOT)
        self.assertTrue(listing["metadata_only"])
        self.assertEqual(listing["count"], 50)
        self.assertNotIn("contract", listing["records"][0])

    def test_contract_hydrates_one_capability(self) -> None:
        result = describe_capability(ROOT, "epistemic-state-manager")
        self.assertTrue(result["valid"])
        self.assertEqual(result["owner"], "govern-metacognitive-evolution")
        self.assertIn("invariants", result["contract"])
        self.assertFalse(describe_capability(ROOT, "missing")["valid"])

    def test_epistemic_and_contradiction_operations(self) -> None:
        epistemic = run_operation("epistemic-state", {"id": "case", "hypotheses": [{"id": "h", "prior": 0.5, "evidence": [{"likelihood_if_true": 0.9, "likelihood_if_false": 0.1}]}]})
        self.assertTrue(epistemic["valid"], epistemic)
        self.assertGreater(epistemic["result"]["hypotheses"][0]["posterior"], 0.5)
        contradiction = run_operation("detect-contradictions", {"claims": [{"id": "a", "subject": "x", "value": 1}, {"id": "b", "subject": "x", "value": 2}]})
        self.assertEqual(len(contradiction["result"]["contradictions"]), 1)

    def test_trace_rejects_private_reasoning_capture(self) -> None:
        result = run_operation("reconstruct-trace", {"trace_id": "t", "events": [{"event_id": "e", "event_type": "decision", "timestamp": "2026-01-01T00:00:00Z", "summary": "selected bounded option", "private_chain_of_thought": "forbidden"}]})
        self.assertFalse(result["valid"])
        self.assertTrue(any("private chain-of-thought" in error for error in result["result"]["errors"]))

    def test_engineering_profile_blocks_protected_inference(self) -> None:
        result = run_operation("profile-engineering-practices", {"events": [{"id": "e", "pattern_type": "testing_practice", "pattern": "property tests", "successful": True, "race": "forbidden"}]})
        self.assertFalse(result["valid"])
        self.assertEqual(result["result"]["policy_violations"][0]["prohibited_fields"], ["race"])

    def test_semantic_effect_lint_and_unknown_operation_fail_closed(self) -> None:
        result = run_operation("lint-semantic-contract", {"capability_id": "x", "reads": [], "writes": ["memory.x"], "epistemic_effects": ["confidence"], "evidence_required": ["test"], "rollback": {"required": True, "method": "restore"}, "observed_effects": ["memory.x"]})
        self.assertTrue(result["valid"], result)
        self.assertFalse(run_operation("not-an-operation", {})["valid"])

    def test_optimization_is_bounded_and_reversible(self) -> None:
        payload = {"id": "exp", "baseline": {"id": "base", "metrics": {"quality": 0.8, "cost": 0.5}}, "candidates": [{"id": "better", "metrics": {"quality": 0.9, "cost": 0.4}}], "directions": {"quality": "maximize", "cost": "minimize"}, "hard_thresholds": {"quality": 0.8}, "utility_weights": {"quality": 1.0, "cost": 0.1}}
        result = run_operation("evaluate-optimization", payload)
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["result"]["rollback_required_on_failure"])
        self.assertTrue(result["result"]["promotion_requires_independent_validation"])

    def test_facade_is_payload_only_read_only_and_cannot_activate_or_cross_memory_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "foreign-project-memory.json"
            sentinel.write_text('{"private": true}\n', encoding="utf-8")
            before = sentinel.read_bytes()
            payload = {
                "id": "bounded", "hypotheses": [],
                "foreign_memory_path": str(sentinel), "automatic_activation": True,
            }
            original = json.dumps(payload, sort_keys=True)
            result = run_operation("epistemic-state", payload)
            self.assertTrue(result["read_only"])
            self.assertEqual(json.dumps(payload, sort_keys=True), original)
            self.assertEqual(sentinel.read_bytes(), before)
            self.assertNotIn("automatic_activation", result["result"])


if __name__ == "__main__":
    unittest.main()
