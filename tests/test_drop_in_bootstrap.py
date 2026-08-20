from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime.cli import main
from runtime.commissioning import commission, project_check
from runtime.project_management import COMPACT_OUTPUT_FILES, CONTROL_DIR, CONTROL_FILES
from runtime.startup import bounded_startup
from runtime.version import VERSION


ROOT = Path(__file__).parents[1]


class DropInBootstrapTests(unittest.TestCase):
    def test_new_project_creates_full_management_contract_and_prompt_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "new-project"
            result = commission(project, "new", apply=True, source_root=ROOT)
            self.assertTrue(result["applied"])
            self.assertTrue((project / "PROJECT_MANAGEMENT.md").is_file())
            for name in (*CONTROL_FILES, "state.json"):
                self.assertTrue((project / CONTROL_DIR / name).is_file(), name)
            for name in COMPACT_OUTPUT_FILES:
                self.assertTrue((project / name).is_file(), name)
            state = json.loads(
                (project / CONTROL_DIR / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["project"]["mode"], "new")
            self.assertEqual(state["controls"]["maximum_selected_skills"], 3)
            self.assertEqual(state["checkpoint"]["runtime_version"], VERSION)
            self.assertEqual(
                state["checkpoint"]["next_safe_action"],
                state["lifecycle"]["next_action"],
            )
            for relative in (*CONTROL_FILES, *COMPACT_OUTPUT_FILES):
                path = project / (
                    CONTROL_DIR / relative if relative in CONTROL_FILES else relative
                )
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("\ufffd", text)
                self.assertNotIn("â€”", text)
                self.assertNotIn("â†’", text)
            for mode in ("new", "existing"):
                prompt = (
                    project / f".engineering-bootstrap/prompts/{mode}-project.md"
                ).read_text(encoding="utf-8")
                self.assertIn("working-set", prompt)
                self.assertIn("hydrate --skill", prompt)
                self.assertIn("explicit approval", prompt)
            self.assertTrue(project_check(project, ROOT)["valid"])

    def test_existing_adoption_preserves_owned_files_and_stores_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            owned = {
                "AGENTS.md": b"existing owner\n",
                ".vscode/settings.json": b'{"editor.formatOnSave": true}\n',
                "pyproject.toml": b"[project]\nname='host'\n",
            }
            for relative, content in owned.items():
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            before = {
                path: hashlib.sha256(content).hexdigest()
                for path, content in owned.items()
            }
            preview = commission(project, "existing", source_root=ROOT)
            self.assertFalse(preview["applied"])
            self.assertIn("AGENTS.md", preview["preserved_existing"])
            applied = commission(project, "existing", apply=True, source_root=ROOT)
            self.assertTrue(applied["applied"])
            for relative, digest in before.items():
                self.assertEqual(
                    hashlib.sha256((project / relative).read_bytes()).hexdigest(),
                    digest,
                )
            inventory = json.loads(
                (
                    project / ".engineering-bootstrap/existing-project-inventory.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(inventory["mode"], "read_only")
            adoption = json.loads(
                (project / ".engineering-bootstrap/adoption-plan.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("AGENTS.md", adoption["preserved_existing"])
            self.assertTrue(project_check(project, ROOT)["valid"])

    def test_startup_is_metadata_only_and_hydration_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            startup = bounded_startup(ROOT, project)
            self.assertEqual(startup.hydrated_skill_bodies, ())
            self.assertFalse((project / ".px/skills").exists())
            self.assertEqual(
                main(["--root", str(ROOT), "hydrate", "--skill", "verify-outcome"]), 0
            )

    def test_project_check_detects_managed_prompt_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            commission(project, "new", apply=True, source_root=ROOT)
            prompt = project / ".engineering-bootstrap/prompts/new-project.md"
            prompt.write_text("tampered", encoding="utf-8")
            result = project_check(project, ROOT)
            self.assertFalse(result["valid"])
            self.assertIn(
                "managed commissioning file drift: .engineering-bootstrap/prompts/new-project.md",
                result["errors"],
            )


if __name__ == "__main__":
    unittest.main()
