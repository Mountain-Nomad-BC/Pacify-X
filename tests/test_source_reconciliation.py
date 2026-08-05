from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceReconciliationTests(unittest.TestCase):
    def test_unknown_mechanism_prevents_completion(self) -> None:
        script = (
            ROOT
            / ".agents/skills/audit-source-capabilities/scripts/reconcile_mechanism_records.py"
        )
        spec = importlib.util.spec_from_file_location(
            "reconcile_mechanism_records", script
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "report.json"
            mappings = root / "mappings.json"
            report.write_text(
                json.dumps(
                    {
                        "candidate_count": 1,
                        "records": [
                            {
                                "path": "a",
                                "sha256": "a" * 64,
                                "mechanisms": ["new"],
                                "disposition": "review_required",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            mappings.write_text(json.dumps({"mappings": {}}), encoding="utf-8")
            self.assertFalse(module.reconcile(report, mappings)["summary"]["complete"])
            mappings.write_text(
                json.dumps({"mappings": {"new": ["owner"]}}), encoding="utf-8"
            )
            self.assertTrue(module.reconcile(report, mappings)["summary"]["complete"])


if __name__ == "__main__":
    unittest.main()
