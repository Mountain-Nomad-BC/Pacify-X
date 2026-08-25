from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "cleanup_python_caches.py"
SPEC = importlib.util.spec_from_file_location("cleanup_python_caches", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CacheQuarantineTests(unittest.TestCase):
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
                / ".engineering-bootstrap/test-evidence/adversarial-repair-gates"
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
