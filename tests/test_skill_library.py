from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
import unittest

from runtime.admission_controller import KNOWN_EFFECTS
from runtime.registry import validate_registry


ROOT = Path(__file__).parents[1]


class SkillLibraryTests(unittest.TestCase):
    def test_catalog_is_metadata_only_unique_and_all_active_bodies_have_contracts(
        self,
    ) -> None:
        catalog = tomllib.loads(
            (ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            catalog["loading_rule"], "metadata_only_at_startup_body_after_selection"
        )
        self.assertEqual(catalog["default_active_limit"], 3)
        ids = [item["id"] for item in catalog["skills"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(ids), 0)
        for item in catalog["skills"]:
            self.assertTrue((ROOT / item["body"]).is_file())
            self.assertTrue((ROOT / item["contract"]).is_file())
            package_path = ROOT / item["contract"]
            if "skill_packages" in package_path.parts:
                package = json.loads(package_path.read_text(encoding="utf-8"))
                self.assertEqual(package["status"], item["status"])

    def test_skill_packages_are_provenance_backed_current_and_lazy(self) -> None:
        for path in sorted((ROOT / "registry/skill_packages").glob("*.json")):
            package = json.loads(path.read_text(encoding="utf-8"))
            body = ROOT / package["body"]
            if package.get("clean_room") is False:
                self.assertTrue(package["provenance"]["type"])
                self.assertTrue(package["provenance"]["basis"])
            else:
                self.assertTrue(package["clean_room"])
            self.assertIn(package["validation_freshness"], {"current", "pending"})
            self.assertIn("read_local", package["effects"])
            self.assertTrue(set(package["effects"]) <= KNOWN_EFFECTS)
            self.assertEqual(
                package["body_sha256"], hashlib.sha256(body.read_bytes()).hexdigest()
            )
            self.assertLessEqual(body.stat().st_size, package["context_budget_bytes"])
            self.assertTrue(
                all((ROOT / reference).is_file() for reference in package["references"])
            )

    def test_python_repair_and_governance_domains_have_diagnosis_tests_rollback_and_lineage(
        self,
    ) -> None:
        repair = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in (
                ROOT / ".px/skills/diagnose-python-repair/references"
            ).glob("*.md")
        )
        for term in (
            "async",
            "authorization",
            "schema",
            "retry",
            "transaction",
            "redaction",
            "subprocess",
            "path",
            "isolate",
            "container",
            "evidence",
            "roll back",
            "lineage",
        ):
            self.assertIn(term, repair)
        governance = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in (
                ROOT / ".px/skills/enforce-governance-controls/references"
            ).glob("*.md")
        )
        for term in (
            "verified identity",
            "visibility",
            "mutation",
            "session",
            "workflow",
            "archive",
            "containment",
            "trace",
            "immutable",
            "cleanup",
            "stale",
        ):
            self.assertIn(term, governance)

    def test_all_skills_have_valid_identity_ui_metadata_and_no_template_markers(
        self,
    ) -> None:
        for skill in sorted((ROOT / ".px/skills").iterdir()):
            body = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(body.startswith("---\n"))
            self.assertIn(f"name: {skill.name}", body)
            self.assertNotIn("TODO", body)
            self.assertTrue((skill / "agents/openai.yaml").is_file())
        self.assertTrue(
            validate_registry(ROOT)["valid"], validate_registry(ROOT)["errors"]
        )


if __name__ == "__main__":
    unittest.main()
