from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


def run_cli(*arguments: str, expected: int = 0) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.cli", "--root", str(ROOT), *arguments],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if completed.returncode != expected:
        raise AssertionError(f"CLI returned {completed.returncode}, expected {expected}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return json.loads(completed.stdout)


class WorkspaceCliTests(unittest.TestCase):
    def test_drop_activate_memory_and_switch_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            preview = run_cli("workspace", "init", "--workspace", str(workspace), "--workspace-id", "wsp_cli")
            self.assertTrue(preview["approval_required"])
            run_cli("workspace", "init", "--workspace", str(workspace), "--workspace-id", "wsp_cli", "--apply")
            alpha = workspace / "projects/alpha"
            beta = workspace / "projects/beta"
            alpha.mkdir()
            beta.mkdir()
            source = alpha / "decision.md"
            source.write_text("# Memory decision\n- Keep project facts isolated with evidence.\n", encoding="utf-8")
            (beta / "README.md").write_text("# Beta\n", encoding="utf-8")
            discovered = run_cli("workspace", "discover", "--workspace", str(workspace), "--apply")
            self.assertEqual(discovered["registered_count"], 2)
            status = run_cli("workspace", "status", "--workspace", str(workspace))
            self.assertTrue(status["valid"])
            run_cli("project", "activate", "--workspace", str(workspace), "--project-id", "prj_alpha")
            ingested = run_cli(
                "memory", "ingest", "--workspace", str(workspace), "--project-id", "prj_alpha",
                "--source", str(source), "--apply",
            )
            memory_ids = ingested["outputs"]["memory_ids"]
            empty = run_cli(
                "memory", "search", "--workspace", str(workspace), "--project-id", "prj_alpha",
                "--query", "Keep project facts isolated with evidence",
            )
            self.assertEqual(empty["results"], [])
            for memory_id in memory_ids:
                run_cli(
                    "memory", "transition", "--workspace", str(workspace), "--project-id", "prj_alpha",
                    "--memory-id", memory_id, "--target", "validated", "--evidence", "cli-test", "--apply",
                )
                run_cli(
                    "memory", "transition", "--workspace", str(workspace), "--project-id", "prj_alpha",
                    "--memory-id", memory_id, "--target", "certified", "--evidence", "cli-test", "--apply",
                )
            found = run_cli(
                "memory", "search", "--workspace", str(workspace), "--project-id", "prj_alpha",
                "--query", "Keep project facts isolated with evidence",
            )
            self.assertTrue(found["results"])
            self.assertIn(found["results"][0]["memory_id"], memory_ids)
            denied = run_cli(
                "project", "activate", "--workspace", str(workspace), "--project-id", "prj_beta", expected=1,
            )
            self.assertTrue(denied["approval_required"])
            switched = run_cli(
                "project", "activate", "--workspace", str(workspace), "--project-id", "prj_beta",
                "--context-reset-confirmed",
            )
            self.assertTrue(switched["activated"])
            foreign = run_cli(
                "memory", "search", "--workspace", str(workspace), "--project-id", "prj_alpha",
                "--query", "Keep project facts isolated with evidence", expected=1,
            )
            self.assertIn("outside the active project session", foreign["errors"][0])


if __name__ == "__main__":
    unittest.main()
