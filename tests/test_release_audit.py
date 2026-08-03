from pathlib import Path
import shutil
import tempfile
import unittest

from runtime.release_audit import audit_framework


ROOT = Path(__file__).parents[1]


class ReleaseAuditTests(unittest.TestCase):
    def test_live_composed_audit_passes_without_fixed_component_counts(self) -> None:
        result = audit_framework(ROOT, require_external_manifests=True)
        self.assertTrue(result["valid"], [item for item in result["checks"] if not item["passed"]])
        self.assertEqual(result["passed"], result["check_count"])
        self.assertGreaterEqual(result["check_count"], 14)

    def test_generated_python_cache_fails_hygiene_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            cache = clone / "runtime" / "__pycache__"
            cache.mkdir()
            (cache / "module.pyc").write_bytes(b"generated")
            result = audit_framework(clone)
            hygiene = next(item for item in result["checks"] if item["id"] == "generated-artifact-hygiene")
            self.assertFalse(hygiene["passed"])

    def test_stale_python_ownership_hash_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            (clone / "runtime" / "release_audit.py").write_text("# mutation\n", encoding="utf-8")
            result = audit_framework(clone)
            ownership = next(item for item in result["checks"] if item["id"] == "python-surface-ownership")
            self.assertFalse(ownership["passed"])

    def test_duplicate_architecture_root_fails_layout_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            (clone / "integrations").mkdir()
            result = audit_framework(clone)
            layout = next(item for item in result["checks"] if item["id"] == "deploy-layout")
            self.assertFalse(layout["passed"])


if __name__ == "__main__":
    unittest.main()
