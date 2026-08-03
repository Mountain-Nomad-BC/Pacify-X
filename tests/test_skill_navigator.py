from __future__ import annotations

import unittest

from runtime.skill_navigator import CapabilitySummary, navigate


class SkillNavigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = [
            CapabilitySummary("repository-discovery", "Map repository architecture and ownership", ("analyze repository",), ("repo map",), ("project_root",)),
            CapabilitySummary("tool-admission", "Review tool provenance permissions and effects", ("install scanner",), ("admit tool",), ("tool_manifest",), risk="R2"),
            CapabilitySummary("draft-only", "Unreviewed repository helper", ("repository",), status="candidate"),
            CapabilitySummary("evidence-assembler", "Build typed evidence for claims", ("assemble evidence",), required_inputs=("claims",)),
        ]

    def test_returns_bounded_ranked_metadata_only(self) -> None:
        result = navigate("analyze repository and make a repo map", self.index, {"project_root": "."}, max_candidates=1)
        self.assertEqual(result.candidates[0].capability_id, "repository-discovery")
        self.assertTrue(result.truncated is False)
        self.assertEqual(result.candidates[0].missing_inputs, ())

    def test_candidate_status_is_not_discoverable(self) -> None:
        result = navigate("use the unreviewed repository helper", self.index)
        self.assertNotIn("draft-only", [item.capability_id for item in result.candidates])

    def test_reports_missing_inputs_without_loading_or_execution(self) -> None:
        result = navigate("install scanner", self.index)
        self.assertEqual(result.candidates[0].capability_id, "tool-admission")
        self.assertEqual(result.candidates[0].missing_inputs, ("tool_manifest",))

    def test_deterministic_tie_breaking_and_limit(self) -> None:
        index = [CapabilitySummary("z-skill", "validate result"), CapabilitySummary("a-skill", "validate result")]
        first = navigate("validate result", index, max_candidates=1)
        second = navigate("validate result", reversed(index), max_candidates=1)
        self.assertEqual(first, second)
        self.assertEqual(first.candidates[0].capability_id, "a-skill")
        self.assertTrue(first.truncated)

    def test_rejects_invalid_budget(self) -> None:
        with self.assertRaises(ValueError):
            navigate("anything", self.index, max_candidates=0)


if __name__ == "__main__":
    unittest.main()
