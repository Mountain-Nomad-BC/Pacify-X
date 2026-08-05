from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / ".agents"
    / "skills"
    / "audit-source-capabilities"
    / "scripts"
    / "reconcile_staged_capabilities.py"
)
SPEC = importlib.util.spec_from_file_location("reconcile_staged_capabilities", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StagedReconciliationTests(unittest.TestCase):
    def _fixture(self, root: Path, presence: str, disposition: str) -> dict:
        candidates = root / "candidates.json"
        policy = root / "policy.json"
        catalog = root / "catalog.toml"
        candidates.write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "kind": "skill",
                            "id": "candidate",
                            "presence": presence,
                            "sources": [],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        policy.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "id": "rule",
                            "priority": 1,
                            "when": {"presence": presence},
                            "disposition": disposition,
                            "targets": ["owner"],
                            "rationale": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        catalog.write_text('[[skills]]\nid = "owner"\n', encoding="utf-8")
        return MODULE.reconcile(candidates, policy, catalog)

    def test_resolves_exactly_one_explicit_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._fixture(Path(folder), "actual", "MERGE")
            self.assertTrue(report["summary"]["complete"])
            self.assertEqual(report["summary"]["resolved_candidates"], 1)

    def test_manifest_only_cannot_be_adopted_as_implementation(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._fixture(Path(folder), "manifest-only", "ADOPT")
            self.assertFalse(report["summary"]["complete"])
            self.assertEqual(
                report["errors"][0]["error"],
                "absent-artifact-cannot-be-implementation-evidence",
            )

    def test_equal_priority_rules_fail_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidates = root / "candidates.json"
            policy = root / "policy.json"
            catalog = root / "catalog.toml"
            candidates.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "kind": "skill",
                                "id": "candidate",
                                "presence": "actual",
                                "sources": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rule = {
                "priority": 1,
                "when": {"presence": "actual"},
                "disposition": "MERGE",
                "targets": ["owner"],
                "rationale": "test",
            }
            policy.write_text(
                json.dumps({"rules": [{"id": "one", **rule}, {"id": "two", **rule}]}),
                encoding="utf-8",
            )
            catalog.write_text('[[skills]]\nid = "owner"\n', encoding="utf-8")
            report = MODULE.reconcile(candidates, policy, catalog)
            self.assertFalse(report["summary"]["complete"])
            self.assertEqual(report["errors"][0]["error"], "ambiguous-disposition")


if __name__ == "__main__":
    unittest.main()
