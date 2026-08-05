from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = (
    ROOT
    / ".agents/skills/evaluate-retrieval-readiness/scripts/evaluate_retrieval_strategy.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("evaluate_retrieval_strategy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class RetrievalStrategyTests(unittest.TestCase):
    def test_exact_reference_quality_resource_and_calibration_gates_pass(self) -> None:
        result = load_module().evaluate(
            {
                "cases": [
                    {
                        "exact_ids": ["a", "b"],
                        "candidate_ids": ["a", "b"],
                        "forbidden_ids": ["secret"],
                    }
                ],
                "thresholds": {
                    "min_mean_recall": 1.0,
                    "max_p95_ms": 10,
                    "max_peak_memory_mib": 100,
                },
                "metrics": {"p95_ms": 5, "peak_memory_mib": 50},
                "state": {
                    "compressed": True,
                    "lifecycle": "loaded",
                    "calibration_fingerprint": "v1",
                    "current_distribution_fingerprint": "v1",
                },
            }
        )
        self.assertTrue(result["complete"])

    def test_drift_or_forbidden_exposure_blocks_readiness(self) -> None:
        result = load_module().evaluate(
            {
                "cases": [
                    {
                        "exact_ids": ["a", "b"],
                        "candidate_ids": ["a", "secret"],
                        "forbidden_ids": ["secret"],
                    }
                ],
                "thresholds": {"min_mean_recall": 0.9},
                "metrics": {"p95_ms": 5, "peak_memory_mib": 50},
                "state": {
                    "compressed": True,
                    "lifecycle": "loaded",
                    "calibration_fingerprint": "old",
                    "current_distribution_fingerprint": "new",
                },
            }
        )
        self.assertFalse(result["complete"])
        self.assertFalse(result["checks"]["forbidden_exposure_zero"])
        self.assertFalse(result["checks"]["calibration_current"])


if __name__ == "__main__":
    unittest.main()
