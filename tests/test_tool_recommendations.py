from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.tool_recommendations import assess_project_tooling


ROOT = Path(__file__).parents[1]


class ToolRecommendationTests(unittest.TestCase):
    def test_assessment_is_read_only_signal_based_and_requests_install_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for index in range(20):
                (project / f"note-{index}.md").write_text("note\n", encoding="utf-8")
            before = {path.name: path.read_bytes() for path in project.iterdir()}
            result = assess_project_tooling(ROOT, project, resolver=lambda _candidate: None)
            after = {path.name: path.read_bytes() for path in project.iterdir()}
            self.assertTrue(result["valid"])
            self.assertTrue(result["read_only"])
            self.assertFalse(result["executed_changes"])
            self.assertEqual(before, after)
            obsidian = next(item for item in result["recommendations"] if item["id"] == "obsidian")
            self.assertTrue(obsidian["relevant"])
            self.assertEqual(obsidian["disposition"], "offer_optional_installation")
            self.assertEqual([item["tool"] for item in result["approval_requests"]], ["obsidian"])

    def test_graphify_falls_back_to_governed_capabilities_without_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for index in range(50):
                (project / f"module-{index}.py").write_text("pass\n", encoding="utf-8")
            result = assess_project_tooling(ROOT, project, resolver=lambda _candidate: None)
            graphify = next(item for item in result["recommendations"] if item["id"] == "graphify")
            self.assertEqual(graphify["disposition"], "use_governed_built_in_alternatives")
            self.assertIn("validate-knowledge-relationships", graphify["built_in_alternatives"])
            self.assertNotIn("graphify", [item["tool"] for item in result["approval_requests"]])

    def test_missing_project_fails_closed(self) -> None:
        result = assess_project_tooling(ROOT, ROOT / "does-not-exist", resolver=lambda _candidate: None)
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()

