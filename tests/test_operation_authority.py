from __future__ import annotations

import unittest

from runtime.operation_authority import AuthorityRequest, authority_roles, decide


class OperationAuthorityTests(unittest.TestCase):
    def test_read_only_codex_host_is_single_owner(self) -> None:
        result = decide(AuthorityRequest("codex-host", ("read_local",)))
        self.assertTrue(result.allowed)
        self.assertEqual(result.executor_owner, "codex-host")

    def test_observation_cannot_impersonate_write_authority(self) -> None:
        result = decide(
            AuthorityRequest(
                "codex-host",
                ("workspace-write",),
                observed_only=True,
                user_approval_id="approval",
                px_policy_decision_id="policy",
                claim_id="claim",
                claim_status="active",
                idempotency_key="once",
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("observation cannot authorize", " ".join(result.reasons))

    def test_claim_never_replaces_user_or_policy_approval(self) -> None:
        result = decide(
            AuthorityRequest(
                "codex-host",
                ("workspace-write",),
                claim_id="claim",
                claim_status="active",
                idempotency_key="once",
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("current user approval", " ".join(result.reasons))
        self.assertIn("PX policy decision", " ".join(result.reasons))

    def test_workspace_write_requires_active_claim_and_idempotency(self) -> None:
        result = decide(
            AuthorityRequest(
                "codex-host",
                ("workspace-write",),
                user_approval_id="approval",
                px_policy_decision_id="policy",
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("active repository claim", " ".join(result.reasons))
        self.assertIn("idempotency key", " ".join(result.reasons))

    def test_px_executor_requires_delegation(self) -> None:
        result = decide(AuthorityRequest("px-owned-executor", ("read",)))
        self.assertFalse(result.allowed)
        self.assertIn("explicit delegation", " ".join(result.reasons))

    def test_nested_px_executor_is_denied(self) -> None:
        result = decide(
            AuthorityRequest(
                "px-owned-executor",
                ("read",),
                explicit_delegation=True,
                active_executors=("codex-host",),
            )
        )
        self.assertFalse(result.allowed)
        self.assertIn("overlapping active executor", " ".join(result.reasons))
        self.assertIn("nested executor", " ".join(result.reasons))

    def test_complete_non_read_authority_composition_is_allowed(self) -> None:
        result = decide(
            AuthorityRequest(
                "codex-host",
                ("workspace-write",),
                user_approval_id="approval",
                px_policy_decision_id="policy",
                claim_id="claim",
                claim_status="active",
                idempotency_key="once",
                active_executors=("codex-host",),
            )
        )
        self.assertTrue(result.allowed)
        self.assertTrue(result.requires_user_approval)
        self.assertTrue(result.requires_claim)

    def test_roles_do_not_share_approval_policy_claim_or_execution(self) -> None:
        roles = authority_roles()
        self.assertTrue(roles["codex-host"]["may_execute"])
        self.assertTrue(roles["px-control-plane"]["may_issue_px_policy"])
        self.assertTrue(roles["repository-claim"]["may_issue_repository_claim"])
        self.assertTrue(roles["extension"]["presentation_and_observation_only"])


if __name__ == "__main__":
    unittest.main()
