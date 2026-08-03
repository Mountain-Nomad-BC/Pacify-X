from __future__ import annotations

from pathlib import Path
import json
import tempfile
import tomllib
import unittest

from runtime.commissioning import commission, project_check
from runtime.intake import inspect_existing_project
from runtime.profiles import validate_profile_set


ROOT = Path(__file__).parents[1]


class ProjectOnboardingTests(unittest.TestCase):
    def test_all_portable_profiles_validate_and_serialize_heavy_work(self) -> None:
        result = validate_profile_set(ROOT / "bootstrap" / "profiles")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["profile_count"], 5)
        self.assertTrue(all(item["profile"]["resources"]["max_heavy_lanes"] == 1 for item in result["profiles"]))

    def test_existing_intake_is_reproducible_read_only_and_preserves_owner_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
            (project / "AGENTS.md").write_text("owner", encoding="utf-8")
            (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            before = {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            first = inspect_existing_project(project)
            second = inspect_existing_project(project)
            after = {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            self.assertEqual(first, second)
            self.assertEqual(before, after)
            self.assertIn("AGENTS.md", first["canonical_owner_candidates"])
            self.assertEqual(first["languages"]["python"], 2)

    def test_new_project_manifest_has_guardrails_and_safe_watcher_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            result = commission(project, "new", apply=True, source_root=ROOT)
            self.assertTrue(result["applied"])
            manifest = json.loads((project / ".engineering-bootstrap/bootstrap-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tool_installation"], "approval_required")
            self.assertTrue(manifest["baselines"]["accessibility"])
            settings = json.loads((project / ".vscode/settings.json").read_text(encoding="utf-8"))
            self.assertIn("**/quarantine/**", settings["files.watcherExclude"])
            registry = json.loads((project / ".engineering-bootstrap/project-registry.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["max_selected_skills"], 3)
            catalog = tomllib.loads((ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8"))
            admitted = sum(item["status"] in {"active", "admitted"} for item in catalog["skills"])
            self.assertEqual(len(registry["skills"]), admitted)
            self.assertTrue(project_check(project)["valid"])
            self.assertTrue((project / "AI_ASSISTANT.md").is_file())
            self.assertTrue((project / ".ai/assistant.toml").is_file())
            self.assertTrue((project / ".github/copilot-instructions.md").is_file())


if __name__ == "__main__":
    unittest.main()
