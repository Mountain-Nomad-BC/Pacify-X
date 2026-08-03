from pathlib import Path
import unittest

from runtime.contracts import ContractValidationError, build_minimal_instance
from runtime.research_assimilation import RESEARCH_CONTRACTS, validate_research_candidate


ROOT = Path(__file__).parents[1]


class ResearchContractAdmissionTests(unittest.TestCase):
    def test_each_research_contract_is_a_live_candidate_only_boundary(self) -> None:
        for kind, name in RESEARCH_CONTRACTS.items():
            with self.subTest(kind=kind):
                record = build_minimal_instance(ROOT / "contracts/research_ops" / name)
                result = validate_research_candidate(ROOT, kind, record)
                self.assertTrue(result["valid"])
                self.assertEqual(result["state"], "candidate_only")
                self.assertFalse(result["auto_activate"])

    def test_invalid_research_record_fails_closed(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_research_candidate(ROOT, "research-record", {})


if __name__ == "__main__":
    unittest.main()
