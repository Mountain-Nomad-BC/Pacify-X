from pathlib import Path
import shutil
import tempfile
import unittest

from runtime.release_audit import audit_framework
from runtime.registry_envelope import discover_count_fields
from runtime.repository_scope import is_external_environment_relative


ROOT = Path(__file__).parents[1]


def _ignore_local_environments(_directory: str, names: list[str]) -> set[str]:
    directory = Path(_directory).resolve()
    if directory.name == "evidence":
        # Keep only the content-addressed custody evidence required by the
        # composed audit; mutation fixtures do not need historical UI/log data.
        return {
            name for name in names
            if name not in {"bundles", "externalized-payload-index.json"}
        }
    derived_fixture_exclusions = {
        ".git", "Python", "node_modules", ".vscode-test", "__pycache__", ".pytest_cache",
        ".operational-gap-ledger.lock", ".test-orchestration.lock",
        "quarantine", "diagnostics", "environment", "operation-bus",
        "preserved-extension-installations", "preserved-skills",
        "project-map", "project-map-history", "project-map-lock-history",
    }
    relative_directory = directory.relative_to(ROOT.resolve())
    return {
        name
        for name in names
        if name in derived_fixture_exclusions
        or name.startswith(".venv")
        or (
            not (not relative_directory.parts and name == "evidence")
            and is_external_environment_relative(relative_directory / name)
        )
    }


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
            shutil.copytree(
                ROOT,
                clone,
                ignore=_ignore_local_environments,
            )
            cache = clone / "runtime" / "__pycache__"
            cache.mkdir()
            (cache / "module.pyc").write_bytes(b"generated")
            ruff_cache = clone / ".ruff_cache"
            ruff_cache.mkdir()
            (ruff_cache / "state.json").write_text("{}\n", encoding="utf-8")
            result = audit_framework(clone)
            hygiene = next(
                item
                for item in result["checks"]
                if item["id"] == "generated-artifact-hygiene"
            )
            self.assertFalse(hygiene["passed"])
            self.assertTrue(any(".ruff_cache" in item for item in hygiene["evidence"]))
            self.assertTrue(any("__pycache__" in item for item in hygiene["evidence"]))

    def test_quarantined_cache_is_retained_but_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(
                ROOT,
                clone,
                ignore=_ignore_local_environments,
            )
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
            result = audit_framework(clone)
            hygiene = next(
                item
                for item in result["checks"]
                if item["id"] == "generated-artifact-hygiene"
            )
            self.assertTrue(hygiene["passed"], hygiene)

    def test_stale_python_ownership_hash_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(
                ROOT,
                clone,
                ignore=_ignore_local_environments,
            )
            (clone / "runtime" / "release_audit.py").write_text(
                "# mutation\n", encoding="utf-8"
            )
            result = audit_framework(clone)
            ownership = next(
                item
                for item in result["checks"]
                if item["id"] == "python-surface-ownership"
            )
            self.assertFalse(ownership["passed"])

    def test_duplicate_architecture_root_fails_layout_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "framework"
            shutil.copytree(
                ROOT,
                clone,
                ignore=_ignore_local_environments,
            )
            (clone / "integrations").mkdir()
            result = audit_framework(clone)
            layout = next(
                item for item in result["checks"] if item["id"] == "deploy-layout"
            )
            self.assertFalse(layout["passed"])


if __name__ == "__main__":
    unittest.main()
