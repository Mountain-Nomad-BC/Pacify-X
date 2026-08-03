import json
from pathlib import Path
import tempfile
import unittest

from runtime.commissioning import commission
from runtime.engineering_lifecycle import lifecycle_status
from runtime.tool_intake import record_tool_intake, scan_project_tooling


ROOT = Path(__file__).resolve().parents[1]


class ToolIntakeTests(unittest.TestCase):
    def test_inventory_is_fail_closed_without_license_scanner_and_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "package.json").write_text(json.dumps({"scripts": {"postinstall": "curl bad"}}), encoding="utf-8")
            result = scan_project_tooling(project, ROOT)
        self.assertEqual(result["decision"], "quarantine")
        self.assertFalse(result["execution_allowed"])
        self.assertTrue(result["components"][0]["malicious_indicators"])

    def test_record_is_versioned_and_advances_lifecycle_without_admitting_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            result = record_tool_intake(project, ROOT, apply=True)
            status = lifecycle_status(ROOT, project)
        self.assertTrue(result["applied"])
        self.assertEqual(result["decision"], "no_external_tooling")
        self.assertEqual(status["next_stage"], "architecture-and-planning")

    def test_scanner_execution_requires_separate_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                scan_project_tooling(Path(directory), ROOT, execute_scanners=True)


if __name__ == "__main__":
    unittest.main()
