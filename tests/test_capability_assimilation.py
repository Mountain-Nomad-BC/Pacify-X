from __future__ import annotations

from pathlib import Path
import unittest

from runtime.capability_assimilation import validate_capability_assimilation


ROOT = Path(__file__).resolve().parents[1]


class CapabilityAssimilationTests(unittest.TestCase):
    def test_scans_dispositions_and_lazy_workflows_reconcile(self) -> None:
        result = validate_capability_assimilation(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertGreaterEqual(result["scan_count"], 5)
        self.assertGreaterEqual(result["files_accounted"], 100_000)
        self.assertGreaterEqual(result["disposition_count"], 30)
        self.assertGreaterEqual(result["workflow_count"], 4)


if __name__ == "__main__":
    unittest.main()
