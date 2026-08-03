from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtime.query_certification import certify_queries
from runtime.semantic_index import build_semantic_index, load_semantic_index, validate_semantic_index
from runtime.skill_navigator import CapabilitySummary, capability_index_revision, navigate


ROOT = Path(__file__).parents[1]


class SemanticCapabilityQueryTests(unittest.TestCase):
    def test_weighted_semantic_metadata_is_deterministic_and_explainable(self) -> None:
        records = (
            CapabilitySummary("generic", "manage task", aliases=("work",)),
            CapabilitySummary("retrieval", "rank documents", concepts=("recall", "hybrid retrieval"), synonyms=("search quality",)),
        )
        first = navigate("hybrid retrieval recall", records, max_candidates=1)
        second = navigate("hybrid retrieval recall", reversed(records), max_candidates=1)
        self.assertEqual(first, second)
        self.assertEqual(first.candidates[0].capability_id, "retrieval")
        self.assertTrue(first.candidates[0].reasons)
        self.assertEqual(first.index_revision, capability_index_revision(records))

    def test_lifecycle_risk_kind_and_tool_constraints_fail_closed(self) -> None:
        records = (
            CapabilitySummary("safe", "inspect model", risk="R1", tools=("python",)),
            CapabilitySummary("risky", "inspect model", risk="R3"),
            CapabilitySummary("draft", "inspect model", status="candidate"),
        )
        result = navigate("inspect model", records, constraints={"max_risk": "R1", "available_tools": []})
        self.assertFalse(result.candidates)
        excluded = dict(result.excluded)
        self.assertIn("missing tools", excluded["safe"])
        self.assertIn("exceeds", excluded["risky"])
        self.assertIn("not selectable", excluded["draft"])

    def test_semantic_index_is_metadata_only_hash_bound_and_current(self) -> None:
        built = build_semantic_index(ROOT)
        loaded = load_semantic_index(ROOT)
        self.assertEqual(built, loaded)
        self.assertEqual(built["record_count"], 89)
        self.assertTrue(validate_semantic_index(ROOT)["valid"])

    def test_recovery_aliases_route_to_canonical_owners(self) -> None:
        from runtime.registry import skill_navigation_index

        index = skill_navigation_index(ROOT)
        cases = {
            "manifest reconciler": "manage-revocable-certification",
            "capacity planner": "govern-runtime-protocol-deployment",
            "prompt injection defense": "secure-agent-supply-chain",
            "reproduction minimizer": "analyze-repository-intelligence",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                returned = [item.capability_id for item in navigate(query, index, max_candidates=3).candidates]
                self.assertIn(expected, returned)

    def test_golden_query_certification_detects_missing_and_replays_deterministically(self) -> None:
        index = (CapabilitySummary("alpha", "audit sources", aliases=("source audit",)),)
        passed = certify_queries(index, ({"id": "ok", "goal": "source audit", "must_include": ["alpha"]},))
        failed = certify_queries(index, ({"id": "bad", "goal": "source audit", "must_include": ["missing"]},))
        self.assertTrue(passed["complete"])
        self.assertFalse(failed["complete"])


if __name__ == "__main__":
    unittest.main()
