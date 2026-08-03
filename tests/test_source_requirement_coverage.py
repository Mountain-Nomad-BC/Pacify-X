from pathlib import Path
import unittest

from runtime.source_coverage import validate_source_coverage


ROOT = Path(__file__).resolve().parents[1]


class SourceRequirementCoverageTests(unittest.TestCase):
    def test_every_distilled_requirement_has_a_real_owner_and_honest_state(self) -> None:
        result = validate_source_coverage(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertGreaterEqual(result["control_count"], 9)


if __name__ == "__main__":
    unittest.main()
