from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillSupportScriptTests(unittest.TestCase):
    def test_build_manifest_recovery_ledger_executes_with_bounded_inputs(self) -> None:
        module = load_script(".agents/skills/audit-source-capabilities/scripts/build_manifest_recovery_ledger.py")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest = temp / "manifest.json"
            reconciliation = temp / "reconciliation.json"
            manifest.write_text(json.dumps({"files": [{"path": "packs/01/skills/a/skill.json", "bytes": 2, "sha256": "a" * 64}]}), encoding="utf-8")
            reconciliation.write_text(json.dumps({
                "missing_paths": ["packs/01/skills/a/skill.json"],
                "manifest_declared_file_count": 1,
                "present_and_matching": 0,
                "missing_declared_files": 1,
                "hash_or_size_mismatches": 0,
                "unexpected_files": 0,
                "missing_by_pack": {"01": 1},
            }), encoding="utf-8")
            rows, summary = module.build(manifest, reconciliation)
            module.write_outputs(rows, summary, temp / "ledger.md", temp / "ledger.csv")
            self.assertEqual(rows[0]["artifact_type"], "skill-component")
            self.assertTrue((temp / "ledger.md").is_file())
            self.assertTrue((temp / "ledger.csv").is_file())

    def test_declared_suite_certifier_executes_current_operational_checks(self) -> None:
        module = load_script(".agents/skills/audit-source-capabilities/scripts/certify_declared_suite_reconstruction.py")
        outcomes, errors = module.validate_operational(ROOT)
        self.assertFalse(errors)
        self.assertEqual(len(outcomes), 257)
        self.assertTrue(all(record["valid"] for record in outcomes.values()))

    def test_planning_card_coverage_validator_checks_real_owners_and_tests(self) -> None:
        module = load_script(".agents/skills/audit-source-capabilities/scripts/validate_planning_card_coverage.py")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            coverage = temp / "coverage.json"
            source = temp / "source.md"
            coverage.write_text(json.dumps({"records": [{
                "id": "PC-1",
                "status": "operational",
                "owners": ["runtime/registry.py"],
                "tests": ["tests/test_config_and_registry.py"],
            }]}), encoding="utf-8")
            source.write_text("## PC-1 bounded card\n", encoding="utf-8")
            result = module.validate(coverage, ROOT, source)
            self.assertTrue(result["complete"], result["errors"])

    def test_bootstrap_audit_reporter_renders_failures_without_hiding_them(self) -> None:
        module = load_script(".agents/skills/validate-engineering-outcomes/scripts/audit_bootstrap.py")
        report = {
            "valid": False,
            "passed": 1,
            "check_count": 2,
            "checks": [
                {"id": "one", "passed": True, "detail": "ok"},
                {"id": "two", "passed": False, "detail": "blocked"},
            ],
        }
        rendered = module.markdown(report)
        self.assertIn("Result: FAIL", rendered)
        self.assertIn("- [ ] `two` - blocked", rendered)


if __name__ == "__main__":
    unittest.main()
