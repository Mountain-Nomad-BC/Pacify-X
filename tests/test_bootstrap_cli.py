from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.commissioning import commission
from runtime.registry import navigation_index, validate_registry
from runtime.skill_navigator import navigate


class BootstrapSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]

    def test_active_registry_is_internally_complete(self) -> None:
        self.assertTrue(validate_registry(self.root)["valid"])

    def test_active_registry_can_be_navigated_without_skill_loading(self) -> None:
        index = navigation_index(self.root)
        result = navigate("verify outcome evidence", index, max_candidates=2)
        self.assertTrue(result.candidates)
        self.assertLessEqual(len(result.candidates), 2)

    def test_existing_project_commissioning_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = commission(Path(temporary), "existing")
            self.assertFalse(result["applied"])
            self.assertEqual(result["effects"], ["read_local"])
            self.assertEqual(result["next"], "approval")
            self.assertTrue(
                all(item["action"] == "create" for item in result["file_plan"])
            )

    def test_existing_project_requires_directory(self) -> None:
        with self.assertRaises(ValueError):
            commission(self.root / "missing-project", "existing")


if __name__ == "__main__":
    unittest.main()
