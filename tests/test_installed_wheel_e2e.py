from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


class InstalledWheelEndToEndTests(unittest.TestCase):
    def _run(
        self, command: list[str], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command, cwd=cwd, text=True, capture_output=True, timeout=120
        )
        self.assertEqual(
            result.returncode,
            0,
            f"command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def _json(self, command: list[str], *, cwd: Path) -> dict:
        return json.loads(self._run(command, cwd=cwd).stdout)

    def test_wheel_installs_and_commissions_new_and_existing_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            certified_wheel = os.environ.get("PACIFY_X_CERTIFIED_WHEEL")
            if certified_wheel:
                wheel = Path(certified_wheel).resolve(strict=True)
                expected = os.environ.get("PACIFY_X_CERTIFIED_WHEEL_SHA256")
                self.assertEqual(
                    hashlib.sha256(wheel.read_bytes()).hexdigest(), expected
                )
                self.assertEqual(
                    os.environ.get("PACIFY_X_RELEASE_BUILD_PROHIBITED"), "1"
                )
            else:
                source = temp / "source"
                source.mkdir()
                for name in (
                    ".agents",
                    ".px",
                    ".ai",
                    ".cursor",
                    ".github",
                    ".windsurf",
                    "bootstrap",
                    "builders",
                    "contracts",
                    "evidence",
                    "LICENSES",
                    "models",
                    "orchestration",
                    "policies",
                    "providers",
                    "registry",
                    "runtime",
                    "templates",
                    "tests",
                ):
                    shutil.copytree(
                        ROOT / name,
                        source / name,
                        ignore=(
                            shutil.ignore_patterns(
                                "preserved-skills",
                                "preserved-extension-installations",
                            )
                            if name == ".px"
                            else None
                        ),
                    )
                for name in (
                    "AGENTS.md",
                    "AI_ASSISTANT.md",
                    "CLAUDE.md",
                    "GEMINI.md",
                    "LICENSE",
                    "MANIFEST.in",
                    "NOTICE",
                    "README.md",
                    "pyproject.toml",
                    "requirements-release.txt",
                ):
                    shutil.copy2(ROOT / name, source / name)
                wheel_dir = temp / "wheel"
                wheel_dir.mkdir()
                self._run(
                    [
                        sys.executable,
                        "-m",
                        "build",
                        "--wheel",
                        "--no-isolation",
                        "--outdir",
                        str(wheel_dir),
                    ],
                    cwd=source,
                )
                wheel = next(wheel_dir.glob("*.whl"))
            venv = temp / "venv"
            self._run([sys.executable, "-m", "venv", str(venv)], cwd=temp)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            executable = venv / (
                "Scripts/engineering-bootstrap.exe"
                if os.name == "nt"
                else "bin/engineering-bootstrap"
            )
            self._run(
                [str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=temp
            )
            self.assertTrue(
                self._json([str(executable), "validate"], cwd=temp)["valid"]
            )
            self.assertTrue(
                self._json(
                    [str(executable), "doctor", "--require", "syntax"], cwd=temp
                )["valid"]
            )
            self.assertTrue(
                self._json([str(executable), "profiles"], cwd=temp)["valid"]
            )
            tool_certification = self._json(
                [str(executable), "tools", "certify"], cwd=temp
            )
            self.assertTrue(tool_certification["valid"])
            self.assertEqual(
                tool_certification["passed_tools"], tool_certification["admitted_tools"]
            )
            self.assertEqual(
                tool_certification["passed_domain_wrappers"],
                tool_certification["domain_wrappers"],
            )
            self.assertTrue(tool_certification["python_surfaces"]["valid"])
            self.assertEqual(
                tool_certification["python_surfaces"]["python_file_count"],
                tool_certification["python_surfaces"]["syntax_valid_count"],
            )

            new_project = temp / "new-project"
            preview = self._json(
                [
                    str(executable),
                    "commission",
                    "--mode",
                    "new",
                    "--project",
                    str(new_project),
                ],
                cwd=temp,
            )
            self.assertTrue(preview["valid"])
            self.assertFalse(new_project.exists())
            applied = self._json(
                [
                    str(executable),
                    "commission",
                    "--mode",
                    "new",
                    "--project",
                    str(new_project),
                    "--apply",
                ],
                cwd=temp,
            )
            self.assertTrue(applied["applied"])
            self.assertTrue(
                self._json(
                    [str(executable), "project-check", "--project", str(new_project)],
                    cwd=temp,
                )["valid"]
            )
            startup = self._json(
                [str(executable), "startup", "--project", str(new_project)], cwd=temp
            )
            self.assertEqual(startup["hydrated_skill_bodies"], [])
            working_set = self._json(
                [
                    str(executable),
                    "working-set",
                    "--goal",
                    "verify deployment evidence",
                ],
                cwd=temp,
            )
            self.assertTrue(working_set["valid"])
            self.assertLessEqual(len(working_set["capability_ids"]), 3)
            hydrated = self._json(
                [
                    str(executable),
                    "hydrate",
                    "--skill",
                    working_set["capability_ids"][0],
                ],
                cwd=temp,
            )
            self.assertTrue(hydrated["valid"])
            self.assertEqual(len(hydrated["active_ids"]), 1)

            existing = temp / "existing-project"
            existing.mkdir()
            owner = existing / "AGENTS.md"
            owner.write_text("host-owned instructions\n", encoding="utf-8")
            (existing / "pyproject.toml").write_text(
                "[project]\nname='host'\n", encoding="utf-8"
            )
            before = hashlib.sha256(owner.read_bytes()).hexdigest()
            existing_preview = self._json(
                [
                    str(executable),
                    "commission",
                    "--mode",
                    "existing",
                    "--project",
                    str(existing),
                ],
                cwd=temp,
            )
            self.assertIn("AGENTS.md", existing_preview["preserved_existing"])
            existing_apply = self._json(
                [
                    str(executable),
                    "commission",
                    "--mode",
                    "existing",
                    "--project",
                    str(existing),
                    "--apply",
                ],
                cwd=temp,
            )
            self.assertTrue(existing_apply["applied"])
            self.assertEqual(hashlib.sha256(owner.read_bytes()).hexdigest(), before)
            self.assertTrue(
                self._json(
                    [str(executable), "project-check", "--project", str(existing)],
                    cwd=temp,
                )["valid"]
            )

            workspace = temp / "multi-workspace"
            workspace_preview = self._json(
                [
                    str(executable),
                    "workspace",
                    "init",
                    "--workspace",
                    str(workspace),
                    "--workspace-id",
                    "wsp_wheel",
                ],
                cwd=temp,
            )
            self.assertTrue(workspace_preview["approval_required"])
            self.assertFalse(workspace.exists())
            self.assertTrue(
                self._json(
                    [
                        str(executable),
                        "workspace",
                        "init",
                        "--workspace",
                        str(workspace),
                        "--workspace-id",
                        "wsp_wheel",
                        "--apply",
                    ],
                    cwd=temp,
                )["applied"]
            )
            self.assertTrue(
                self._json(
                    [
                        str(executable),
                        "workspace",
                        "create-project",
                        "--workspace",
                        str(workspace),
                        "--name",
                        "green",
                        "--apply",
                    ],
                    cwd=temp,
                )["applied"]
            )
            dropped = workspace / "projects/legacy"
            dropped.mkdir()
            dropped_owner = dropped / "AGENTS.md"
            dropped_owner.write_text("legacy owner\n", encoding="utf-8")
            (dropped / "README.md").write_text("# Legacy\n", encoding="utf-8")
            dropped_hash = hashlib.sha256(dropped_owner.read_bytes()).hexdigest()
            discovery = self._json(
                [
                    str(executable),
                    "workspace",
                    "discover",
                    "--workspace",
                    str(workspace),
                    "--apply",
                ],
                cwd=temp,
            )
            self.assertEqual(discovery["registered_count"], 2)
            self.assertEqual(
                hashlib.sha256(dropped_owner.read_bytes()).hexdigest(), dropped_hash
            )
            workspace_check = self._json(
                [str(executable), "workspace", "status", "--workspace", str(workspace)],
                cwd=temp,
            )
            self.assertTrue(workspace_check["valid"])
            self.assertEqual(workspace_check["registered_count"], 2)
            self.assertTrue(
                self._json(
                    [
                        str(executable),
                        "project",
                        "activate",
                        "--workspace",
                        str(workspace),
                        "--project-id",
                        "prj_green",
                    ],
                    cwd=temp,
                )["activated"]
            )
            memory_source = workspace / "projects/green/decision.md"
            memory_source.write_text(
                "# Decision\n- Keep installed workspace memory isolated with evidence.\n",
                encoding="utf-8",
            )
            memory = self._json(
                [
                    str(executable),
                    "memory",
                    "ingest",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--source",
                    str(memory_source),
                    "--apply",
                ],
                cwd=temp,
            )
            self.assertTrue(memory["valid"])
            for memory_id in memory["outputs"]["memory_ids"]:
                self.assertTrue(
                    self._json(
                        [
                            str(executable),
                            "memory",
                            "transition",
                            "--workspace",
                            str(workspace),
                            "--project-id",
                            "prj_green",
                            "--memory-id",
                            memory_id,
                            "--target",
                            "validated",
                            "--evidence",
                            "wheel-test",
                            "--apply",
                        ],
                        cwd=temp,
                    )["valid"]
                )
                self.assertTrue(
                    self._json(
                        [
                            str(executable),
                            "memory",
                            "transition",
                            "--workspace",
                            str(workspace),
                            "--project-id",
                            "prj_green",
                            "--memory-id",
                            memory_id,
                            "--target",
                            "certified",
                            "--evidence",
                            "wheel-test",
                            "--apply",
                        ],
                        cwd=temp,
                    )["valid"]
                )
            found = self._json(
                [
                    str(executable),
                    "memory",
                    "search",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--query",
                    "Keep installed workspace memory isolated with evidence",
                ],
                cwd=temp,
            )
            self.assertTrue(found["results"])
            original_memory_id = memory["outputs"]["memory_ids"][0]
            correction_source = workspace / "projects/green/correction.md"
            correction_source.write_text(
                "# Correction\nThe current installed-wheel decision is corrected.\n",
                encoding="utf-8",
            )
            correction = self._json(
                [
                    str(executable),
                    "memory",
                    "correct",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--previous-memory-id",
                    original_memory_id,
                    "--memory-id",
                    "mem-wheel-correction",
                    "--source",
                    str(correction_source),
                    "--title",
                    "Corrected installed decision",
                    "--summary",
                    "Current installed-wheel decision is corrected",
                    "--apply",
                ],
                cwd=temp,
            )
            self.assertTrue(correction["applied"])
            candidate_search = self._json(
                [
                    str(executable),
                    "memory",
                    "search",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--query",
                    "installed workspace memory isolated evidence",
                ],
                cwd=temp,
            )
            self.assertIn(
                original_memory_id,
                [item["memory_id"] for item in candidate_search["results"]],
            )
            for target in ("validated", "certified"):
                self.assertTrue(
                    self._json(
                        [
                            str(executable),
                            "memory",
                            "transition",
                            "--workspace",
                            str(workspace),
                            "--project-id",
                            "prj_green",
                            "--memory-id",
                            "mem-wheel-correction",
                            "--target",
                            target,
                            "--evidence",
                            "wheel-correction",
                            "--apply",
                        ],
                        cwd=temp,
                    )["valid"]
                )
            corrected_search = self._json(
                [
                    str(executable),
                    "memory",
                    "search",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--query",
                    "current installed wheel decision corrected",
                ],
                cwd=temp,
            )
            corrected_ids = [item["memory_id"] for item in corrected_search["results"]]
            self.assertEqual(corrected_ids[0], "mem-wheel-correction")
            self.assertNotIn(original_memory_id, corrected_ids)
            workflows = self._json([str(executable), "workflow", "list"], cwd=temp)
            self.assertEqual(workflows["workflow_count"], 17)
            request_path = temp / "health-request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "workflow_id": "nightly_project_health",
                        "project_id": "prj_green",
                        "session_id": "session_operator",
                        "idempotency_key": "wheel_health_001",
                        "approved_effects": ["read_local"],
                        "payload": {
                            "metrics": {
                                name: 1.0
                                for name in (
                                    "tests",
                                    "security",
                                    "evidence",
                                    "dependencies",
                                    "memory",
                                    "operations",
                                )
                            }
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertTrue(
                self._json(
                    [
                        str(executable),
                        "workflow",
                        "run",
                        "--workspace",
                        str(workspace),
                        "--request",
                        str(request_path),
                        "--apply",
                    ],
                    cwd=temp,
                )["valid"]
            )
            parallel = self._json(
                [
                    str(executable),
                    "project",
                    "activate",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_legacy",
                    "--agent-id",
                    "agent_parallel",
                    "--session-id",
                    "session_parallel",
                ],
                cwd=temp,
            )
            self.assertTrue(parallel["activated"])
            concurrent = self._json(
                [str(executable), "workspace", "status", "--workspace", str(workspace)],
                cwd=temp,
            )
            self.assertEqual(concurrent["active_session_count"], 2)
            self.assertTrue(
                self._json(
                    [
                        str(executable),
                        "project",
                        "release",
                        "--workspace",
                        str(workspace),
                        "--session-id",
                        "session_parallel",
                        "--context-reset-confirmed",
                    ],
                    cwd=temp,
                )["released"]
            )
            switched = self._json(
                [
                    str(executable),
                    "project",
                    "activate",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_legacy",
                    "--context-reset-confirmed",
                ],
                cwd=temp,
            )
            self.assertTrue(switched["activated"])
            foreign = subprocess.run(
                [
                    str(executable),
                    "memory",
                    "search",
                    "--workspace",
                    str(workspace),
                    "--project-id",
                    "prj_green",
                    "--query",
                    "evidence",
                ],
                cwd=temp,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(foreign.returncode, 1)
            self.assertIn("outside the active project session", foreign.stdout)


if __name__ == "__main__":
    unittest.main()
