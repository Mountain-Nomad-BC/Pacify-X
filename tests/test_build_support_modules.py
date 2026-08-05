from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from builders.declared_suite_builder import DOMAINS, contract
from builders.declared_suite_support_builder import schema
from builders.last_round_assimilation_builder import disposition_for
from runtime.metacognitive_evolution.common.io import dump_json, load_json


class BuildSupportModuleTests(unittest.TestCase):
    def test_metacognitive_json_io_round_trips_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            text = dump_json({"b": 2, "a": 1}, path)
            self.assertEqual(text, '{\n  "a": 1,\n  "b": 2\n}\n')
            self.assertEqual(load_json(path), {"a": 1, "b": 2})

    def test_declared_suite_contract_builder_preserves_behavior_boundaries(
        self,
    ) -> None:
        card = {
            "source_id": "bounded-outcome",
            "kind": "skill",
            "source_paths": ["packs/01/skills/bounded/skill.json"],
            "implementation_targets": ["registry/example.json"],
        }
        result = contract(card, DOMAINS["01"])
        self.assertEqual(result["id"], "bounded-outcome")
        self.assertTrue(result["failure_policy"])
        self.assertTrue(result["recovery"])

    def test_support_schema_builder_is_closed_and_requires_every_field(self) -> None:
        result = schema("fixture", ["id", "evidence", "recoverable"])
        self.assertFalse(result["additionalProperties"])
        self.assertEqual(result["required"], ["id", "evidence", "recoverable"])
        self.assertEqual(result["properties"]["recoverable"]["type"], "boolean")

    def test_last_round_cache_classification_precedes_test_classification(self) -> None:
        disposition, owner = disposition_for(
            Path("tests/__pycache__/test_scheduler.pyc"), "scheduler"
        )
        self.assertEqual(
            disposition, "quarantine_generated_transient_after_intake_close"
        )
        self.assertEqual(owner, "parent temp quarantine")


if __name__ == "__main__":
    unittest.main()
