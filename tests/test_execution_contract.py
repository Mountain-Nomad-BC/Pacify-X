from __future__ import annotations

import unittest

from runtime.execution_contract import ExecutionRequest, PolicyDecision, enforce


class ExecutionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = {"id": "repo-reader", "status": "active", "effects": ["read_local"]}

    def test_allows_declared_read_only_request(self) -> None:
        result = enforce(ExecutionRequest("repo-reader", ("read_local",), 30, 2), PolicyDecision(True, ("read_local",)), self.manifest)
        self.assertTrue(result.approved)
        self.assertFalse(result.requires_verification)

    def test_rejects_unadmitted_or_mismatched_capability(self) -> None:
        manifest = {"id": "other", "status": "candidate", "effects": ["read_local"]}
        result = enforce(ExecutionRequest("repo-reader", ("read_local",), 30, 1), PolicyDecision(True, ("read_local",)), manifest)
        self.assertFalse(result.approved)
        self.assertIn("manifest capability mismatch", result.reasons)

    def test_rejects_undeclared_effect(self) -> None:
        result = enforce(ExecutionRequest("repo-reader", ("write_workspace",), 30, 1, "k"), PolicyDecision(True, ("write_workspace",), "A-1"), self.manifest)
        self.assertFalse(result.approved)
        self.assertIn("request contains undeclared effects", result.reasons)

    def test_non_read_requires_approval_and_idempotency(self) -> None:
        manifest = {"id": "writer", "status": "active", "effects": ["write_workspace"]}
        result = enforce(ExecutionRequest("writer", ("write_workspace",), 30, 1), PolicyDecision(True, ("write_workspace",)), manifest)
        self.assertFalse(result.approved)
        self.assertEqual(len(result.reasons), 3)
        self.assertIn("non-read effects require an enforced runtime effect grant", result.reasons)

    def test_enforces_budgets_and_policy(self) -> None:
        result = enforce(ExecutionRequest("repo-reader", ("read_local",), 121, 13), PolicyDecision(False, ()), self.manifest)
        self.assertFalse(result.approved)
        self.assertIn("policy denied execution", result.reasons)
        self.assertIn("timeout outside budget", result.reasons)
        self.assertIn("tool-call budget outside limit", result.reasons)


if __name__ == "__main__":
    unittest.main()
