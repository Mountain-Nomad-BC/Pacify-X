from __future__ import annotations

import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from runtime.commissioning import commission, project_check


ROOT = Path(__file__).parents[1]


class CommissioningApplyTests(unittest.TestCase):
    def test_new_project_proposal_has_no_write_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "new-project"
            result = commission(project, "new", source_root=ROOT)
            self.assertFalse(project.exists())
            self.assertFalse(result["applied"])
            self.assertEqual(result["effects"], ["read_local"])
            self.assertIn(".codex/config.toml", result["create"])

    def test_apply_creates_bounded_scaffold_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "new-project"
            result = commission(project, "new", apply=True, source_root=ROOT)
            self.assertTrue(result["applied"])
            checked = project_check(project)
            self.assertTrue(checked["valid"], checked["errors"])
            catalog = tomllib.loads((ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8"))
            admitted = sum(item["status"] in {"active", "admitted"} for item in catalog["skills"])
            self.assertEqual(checked["skill_count"], admitted)
            config = (project / ".codex/config.toml").read_text(encoding="utf-8")
            self.assertNotIn("model =", config)
            self.assertNotIn("approval_policy", config)

    def test_existing_project_preserves_owner_and_applies_namespaced_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "AGENTS.md").write_text("existing instructions", encoding="utf-8")
            result = commission(project, "existing", apply=True, source_root=ROOT)
            self.assertTrue(result["applied"])
            self.assertEqual(result["conflicts"], ["AGENTS.md"])
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), "existing instructions")
            self.assertTrue((project / ".engineering-bootstrap/AGENTS.md").is_file())
            self.assertTrue((project / ".engineering-bootstrap/adoption-plan.json").is_file())

    def test_second_apply_is_idempotent_except_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            result = commission(project, "new", apply=True, source_root=ROOT)
            self.assertTrue(result["applied"])
            self.assertEqual(result["create"], [])
            receipt = json.loads((project / ".engineering-bootstrap/commissioning-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["blocking_conflicts"], [])

    def test_project_check_rejects_tampered_skill_registry_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            registry_path = project / ".engineering-bootstrap/project-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["skills"][0]["sha256"] = "0" * 64
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            result = project_check(project)
            self.assertFalse(result["valid"])
            self.assertTrue(any("managed commissioning file drift" in error or "canonical skill hash mismatch" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
