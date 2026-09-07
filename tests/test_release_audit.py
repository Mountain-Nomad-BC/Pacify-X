from pathlib import Path
import tempfile
import unittest

from runtime.release_audit import (
    audit_deploy_layout,
    audit_framework,
    audit_generated_artifact_hygiene,
    audit_python_surface_ownership,
)
from runtime.registry_envelope import discover_count_fields


ROOT = Path(__file__).parents[1]

class ReleaseAuditTests(unittest.TestCase):
    def test_live_composed_audit_passes_without_fixed_component_counts(self) -> None:
        result = audit_framework(ROOT, require_external_manifests=True)
        self.assertTrue(
            result["valid"], [item for item in result["checks"] if not item["passed"]]
        )
        self.assertEqual(result["passed"], result["check_count"])
        self.assertGreaterEqual(result["check_count"], 14)
        envelope = next(
            item for item in result["checks"] if item["id"] == "registry-envelopes"
        )
        self.assertEqual(
            envelope["detail"], f"owned count fields={len(discover_count_fields(ROOT))}"
        )

    def test_generated_python_cache_fails_hygiene_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            cache = clone / "runtime" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"generated")
            ruff_cache = clone / ".ruff_cache"
            ruff_cache.mkdir()
            (ruff_cache / "state.json").write_text("{}\n", encoding="utf-8")
            hygiene = audit_generated_artifact_hygiene(clone)
            self.assertFalse(hygiene["passed"])
            self.assertTrue(any(".ruff_cache" in item for item in hygiene["evidence"]))
            self.assertTrue(any("__pycache__" in item for item in hygiene["evidence"]))

    def test_repository_root_pytest_cache_is_external_tool_custody(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            cache = clone / ".pytest_cache"
            cache.mkdir(parents=True)
            (cache / "state.json").write_text("{}\n", encoding="utf-8")

            hygiene = audit_generated_artifact_hygiene(clone)

            self.assertTrue(hygiene["passed"], hygiene)

    def test_quarantined_cache_is_retained_but_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            cache = (
                clone
                / ".engineering-bootstrap"
                / "quarantine"
                / "disposable-cache"
                / "retained"
                / "runtime"
                / "__pycache__"
            )
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "module.pyc").write_bytes(b"retained")
            hygiene = audit_generated_artifact_hygiene(clone)
            self.assertTrue(hygiene["passed"], hygiene)

    def test_stale_python_ownership_hash_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            target = clone / "runtime" / "release_audit.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "# mutation\n", encoding="utf-8"
            )
            ownership_path = clone / "registry" / "python_surface_ownership.json"
            ownership_path.parent.mkdir(parents=True)
            ownership_path.write_text(
                '{"records":[{"path":"runtime/release_audit.py",'
                '"sha256":"0000000000000000000000000000000000000000000000000000000000000000"}]}\n',
                encoding="utf-8",
            )
            ownership = audit_python_surface_ownership(clone)
            self.assertFalse(ownership["passed"])
            self.assertIn("hash mismatch: runtime/release_audit.py", ownership["evidence"])

    def test_duplicate_architecture_root_fails_layout_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            (clone / "integrations").mkdir(parents=True)
            layout = audit_deploy_layout(clone)
            self.assertFalse(layout["passed"])


if __name__ == "__main__":
    unittest.main()
