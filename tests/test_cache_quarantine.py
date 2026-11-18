from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "cleanup_python_caches.py"
SPEC = importlib.util.spec_from_file_location("cleanup_python_caches", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CacheQuarantineTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows cache name casing")
    def test_windows_cache_directory_casing_is_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pkg/__PYCACHE__/metadata.json"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"cache metadata")
            result = MODULE.cleanup(root, apply=True)
            self.assertEqual(result["cache_directory_count"], 1)
            self.assertEqual(result["inventoried_file_count"], 1)
            self.assertFalse(source.exists())
            destination = root / result["quarantine_destination"]
            self.assertEqual((destination / "pkg/__PYCACHE__/metadata.json").read_bytes(), b"cache metadata")

    def test_relative_quarantine_uses_selected_project_not_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            source = root / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"owned")
            with patch("os.getcwd", return_value=str(base)):
                result = MODULE.cleanup(root, apply=True, quarantine_root=Path("retained"))
            destination = root / result["quarantine_destination"]
            self.assertTrue(destination.is_relative_to(root / "retained"))
            self.assertEqual((destination / "pkg/__pycache__/module.pyc").read_bytes(), b"owned")
            self.assertFalse((base / "retained").exists())

    def test_relative_quarantine_traversal_is_refused_before_moves(self) -> None:
        from runtime.confined_output import ConfinementError
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            source = root / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"owned")
            with patch("os.getcwd", return_value=str(base)):
                with self.assertRaises(ConfinementError):
                    MODULE.cleanup(root, apply=True, quarantine_root=Path("../escape"))
            self.assertEqual(source.read_bytes(), b"owned")
            self.assertFalse((base / "escape").exists())

    def test_cli_relative_report_uses_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project, installation = base / "project", base / "installation"
            project.mkdir()
            installation.mkdir()
            with patch.object(MODULE, "ROOT", installation), patch(
                "sys.argv", ["cleanup", "--root", str(project), "--output", "reports/cache.json"]
            ):
                self.assertEqual(MODULE.main(), 0)
            report = json.loads((project / "reports/cache.json").read_text())
            self.assertEqual(report["operation"], "quarantine_dry_run")
            self.assertFalse((installation / "reports").exists())

    def test_cli_absolute_report_inside_selected_project_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project, installation = base / "project", base / "installation"
            project.mkdir()
            installation.mkdir()
            target = project / "reports/cache.json"
            with patch.object(MODULE, "ROOT", installation), patch(
                "sys.argv", ["cleanup", "--root", str(project), "--output", str(target)]
            ):
                self.assertEqual(MODULE.main(), 0)
            self.assertEqual(json.loads(target.read_text())["inventoried_file_count"], 0)

    def test_cli_escaping_report_is_refused_before_cache_moves(self) -> None:
        from runtime.confined_output import ConfinementError
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project, installation = base / "project", base / "installation"
            source = project / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"owned")
            installation.mkdir()
            target = installation / "cache.json"
            with patch.object(MODULE, "ROOT", installation), patch(
                "sys.argv", ["cleanup", "--root", str(project), "--apply", "--output", str(target)]
            ):
                with self.assertRaises(ConfinementError):
                    MODULE.main()
            self.assertEqual(source.read_bytes(), b"owned")
            self.assertFalse((project / ".agentic_engineering_os_px").exists())
            self.assertFalse(target.exists())

    def test_repeat_run_preserves_custom_quarantine_and_its_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"compiled")
            quarantine = root / "retained-cache"
            first = MODULE.cleanup(root, apply=True, quarantine_root=quarantine)
            destination = root / first["quarantine_destination"]
            receipt = (destination / "receipt.json").read_bytes()
            second = MODULE.cleanup(root, apply=True, quarantine_root=quarantine)
            self.assertEqual(second["inventoried_file_count"], 0)
            self.assertIsNone(second["quarantine_destination"])
            self.assertEqual((destination / "receipt.json").read_bytes(), receipt)
            self.assertEqual((destination / "pkg/__pycache__/module.pyc").read_bytes(), b"compiled")

    def test_nested_cache_directories_are_relocated_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ["pkg/__pycache__/outer.pyc", "pkg/__pycache__/nested/__pycache__/inner.pyc"]
            for relative in paths:
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(relative.encode())
            result = MODULE.cleanup(root, apply=True)
            destination = root / result["quarantine_destination"]
            self.assertEqual(result["cache_directory_count"], 1)
            self.assertEqual(result["inventoried_file_count"], 2)
            for relative in paths:
                self.assertFalse((root / relative).exists())
                self.assertEqual((destination / relative).read_bytes(), relative.encode())

    def test_quarantine_inside_cache_is_refused_before_any_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"compiled")
            quarantine = source.parent / "retained"
            with self.assertRaisesRegex(ValueError, "quarantine.*inside.*cache"):
                MODULE.cleanup(root, apply=True, quarantine_root=quarantine)
            self.assertEqual(source.read_bytes(), b"compiled")
            self.assertFalse(quarantine.exists())

    def test_quarantine_outside_selected_project_is_refused_before_moves(self) -> None:
        from runtime.confined_output import ConfinementError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            source = root / "pkg/__pycache__/module.pyc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"owned")
            outside = Path(directory) / "outside"
            with self.assertRaises(ConfinementError):
                MODULE.cleanup(root, apply=True, quarantine_root=outside)
            self.assertEqual(source.read_bytes(), b"owned")
            self.assertFalse(outside.exists())

    def test_repository_root_pytest_cache_is_external_tool_custody(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / ".pytest_cache"
            cache.mkdir()
            (cache / "state.json").write_text("{}\n", encoding="utf-8")

            result = MODULE.cleanup(root, apply=False)

            self.assertEqual(result["cache_directory_count"], 0)
            self.assertEqual(result["inventoried_file_count"], 0)

    def test_external_runtime_caches_are_never_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv_cache = root / ".venv-certify/Lib/site-packages/pkg/__pycache__/module.pyc"
            vscode_cache = root / "extension/.vscode-test/runtime/__pycache__/host.pyc"
            for path in (venv_cache, vscode_cache):
                path.parent.mkdir(parents=True)
                path.write_bytes(b"external")

            result = MODULE.cleanup(root, apply=True)

            self.assertEqual(result["inventoried_file_count"], 0)
            self.assertTrue(venv_cache.is_file())
            self.assertTrue(vscode_cache.is_file())

    def test_preserved_skill_backups_are_never_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / ".px/preserved-skills/initial/workspace-original/pkg/__pycache__/module.pyc"
            protected.parent.mkdir(parents=True)
            protected.write_bytes(b"custody")

            result = MODULE.cleanup(root, apply=True)

            self.assertTrue(protected.is_file())
            self.assertEqual(protected.read_bytes(), b"custody")
            self.assertEqual(result["inventoried_file_count"], 0)

    def test_hostile_local_test_evidence_is_pruned_before_cache_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hostile = (
                root
                / ".agentic_engineering_os_px/test-evidence/adversarial-repair-gates"
                / "__pycache__/fixture.pyc"
            )
            owned = root / "runtime/__pycache__/owned.pyc"
            for path, value in ((hostile, b"hostile"), (owned, b"owned")):
                path.parent.mkdir(parents=True)
                path.write_bytes(value)

            result = MODULE.cleanup(root, apply=True)

            self.assertTrue(hostile.is_file())
            self.assertFalse(owned.exists())
            self.assertEqual(result["inventoried_file_count"], 1)

    def test_generated_source_boundaries_stay_pruned_while_owned_cache_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = [
                root / "extension/build/__pycache__/build.pyc",
                root / "extension/dist/__pycache__/dist.pyc",
                root / "extension/evidence/__pycache__/evidence.pyc",
            ]
            owned = root / "runtime/__pycache__/owned.pyc"
            for path in [*generated, owned]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"compiled")

            result = MODULE.cleanup(root, apply=True)

            self.assertEqual(result["inventoried_file_count"], 1)
            self.assertFalse(owned.exists())
            self.assertTrue(all(path.is_file() for path in generated))

    def test_apply_moves_and_hash_verifies_without_hard_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "pkg" / "__pycache__"
            cache.mkdir(parents=True)
            bytecode = cache / "module.pyc"
            bytecode.write_bytes(b"compiled")
            ruff_cache = root / ".ruff_cache"
            ruff_cache.mkdir()
            (ruff_cache / "state.json").write_text("{}\n", encoding="utf-8")
            result = MODULE.cleanup(root, apply=True)
            self.assertFalse(result["hard_delete"])
            self.assertFalse(bytecode.exists())
            destination = root / str(result["quarantine_destination"])
            moved = destination / "pkg" / "__pycache__" / "module.pyc"
            self.assertEqual(moved.read_bytes(), b"compiled")
            self.assertEqual(
                (destination / ".ruff_cache/state.json").read_text(encoding="utf-8"),
                "{}\n",
            )
            receipt = json.loads(
                (destination / "receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["operation"], "recoverable_cache_quarantine")
            self.assertEqual(
                {record["path"] for record in receipt["records"]},
                {".ruff_cache/state.json", "pkg/__pycache__/module.pyc"},
            )


if __name__ == "__main__":
    unittest.main()
