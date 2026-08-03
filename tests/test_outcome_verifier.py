from __future__ import annotations

import unittest

from runtime.outcome_verifier import verify


class OutcomeVerifierTests(unittest.TestCase):
    def test_verifies_only_with_postconditions_and_current_evidence(self) -> None:
        result = verify({"tests": True, "mapping": True}, [{"id": "E-2", "status": "current", "valid": True}], policy_allowed=True, executor_claimed_complete=True)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.approved_evidence_ids, ("E-2",))

    def test_executor_cannot_self_certify_failed_postcondition(self) -> None:
        result = verify({"tests": False}, [{"id": "E", "status": "current", "valid": True}], policy_allowed=True, executor_claimed_complete=True)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.warnings)

    def test_no_current_evidence_is_partial(self) -> None:
        result = verify({"tests": True}, [{"id": "old", "status": "stale", "valid": True}], policy_allowed=True, executor_claimed_complete=True)
        self.assertEqual(result.status, "partial")

    def test_policy_denial_blocks_even_passing_result(self) -> None:
        result = verify({"tests": True}, [{"id": "E", "status": "current", "valid": True}], policy_allowed=False, executor_claimed_complete=True)
        self.assertEqual(result.status, "blocked")

    def test_missing_postconditions_fails(self) -> None:
        result = verify({}, [], policy_allowed=True, executor_claimed_complete=False)
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
