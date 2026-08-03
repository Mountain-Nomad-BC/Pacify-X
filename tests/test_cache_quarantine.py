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
            self.assertEqual((destination / ".ruff_cache/state.json").read_text(encoding="utf-8"), "{}\n")
            receipt = json.loads((destination / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["operation"], "recoverable_cache_quarantine")
            self.assertEqual(
                {record["path"] for record in receipt["records"]},
                {".ruff_cache/state.json", "pkg/__pycache__/module.pyc"},
            )


if __name__ == "__main__":
    unittest.main()
