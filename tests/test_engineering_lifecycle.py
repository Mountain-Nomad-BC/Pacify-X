from pathlib import Path
import tempfile
import unittest

from runtime.commissioning import commission
from runtime.engineering_lifecycle import lifecycle_status


ROOT = Path(__file__).resolve().parents[1]


class EngineeringLifecycleTests(unittest.TestCase):
    def test_uncommissioned_project_stops_at_commissioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = lifecycle_status(ROOT, Path(directory))
        self.assertEqual(status["next_stage"], "project-commissioning")
        self.assertTrue(status["metadata_only"])

    def test_commissioned_project_advances_to_explicit_tool_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            status = lifecycle_status(ROOT, project)
        self.assertEqual(status["next_stage"], "tool-and-package-admission")
        self.assertEqual(
            status["next_stage_contract"]["skills"], ["quarantine-external-tools"]
        )


if __name__ == "__main__":
    unittest.main()
