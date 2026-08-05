from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / "migration" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExternalBehaviorIntakeTests(unittest.TestCase):
    def test_extractor_emits_sanitized_metadata_without_body_or_absolute_path(
        self,
    ) -> None:
        extractor = load_script("extract_behavior_contracts")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product_name = "Re" + "my"
            file_path = root / f"{product_name}_service.py"
            body_marker = "BODY_MUST_NOT_APPEAR"
            file_path.write_text(
                f"def test_{product_name.lower()}_policy():\n    token = '{body_marker}'\n    return token\n",
                encoding="utf-8",
            )
            record = extractor._record("source-one", root, file_path)
            rendered = json.dumps(record)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn(body_marker, rendered)
            self.assertNotIn(product_name.casefold(), rendered.casefold())
            self.assertEqual(record["source_alias"], "source-one")
            self.assertTrue(record["tests"])

    def test_planner_uses_only_index_metadata_and_marks_direct_copy_false(self) -> None:
        planner = load_script("plan_behavior_skill_admission")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "index"
            index.mkdir()
            (index / "summary.json").write_text(
                json.dumps({"tree_sha256": "a" * 64, "file_count": 1}), encoding="utf-8"
            )
            candidate = {
                "source_alias": "source-12",
                "relative_path": "retrieval/check/SKILL.md",
                "sha256": "b" * 64,
                "name": "retrieval-check",
                "description": "Evaluate retrieval quality and search coverage",
            }
            (index / "skill-candidates.json").write_text(
                json.dumps({"skills": [candidate]}), encoding="utf-8"
            )
            record = {
                "source_alias": "source-12",
                "bytes": 5,
                "text_read": True,
                "tests": [],
                "symbols": [],
                "behavior_tags": ["evaluation"],
                "effects": [],
                "secret_indicator_count": 0,
            }
            (index / "behavior-index.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            catalog = root / "catalog.toml"
            catalog.write_text(
                '[[skills]]\nid = "verify-outcome"\ntags = ["validation", "evidence"]\n',
                encoding="utf-8",
            )
            plan = planner.build_plan(index, catalog)
            self.assertEqual(plan["counts"]["candidate_manifests"], 1)
            self.assertFalse(plan["all_skill_candidates"][0]["direct_copy_allowed"])
            self.assertFalse(plan["method"]["source_bodies_read"])
            self.assertFalse(plan["method"]["source_code_executed"])

    def test_every_staged_requirement_has_a_validated_canonical_disposition(
        self,
    ) -> None:
        report = json.loads(
            (ROOT / "evidence/external-source-admission-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["requirement_cards"], 75)
        self.assertEqual(report["indexed_files"], 6353)
        self.assertEqual(report["parse_failure_count"], 0)
        self.assertIn("active/admitted", report["runtime_truth"])
        self.assertFalse((ROOT / "planning/external_behavior_intake").exists())


if __name__ == "__main__":
    unittest.main()
