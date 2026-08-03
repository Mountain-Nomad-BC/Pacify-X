from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from runtime.project_stream_controls import (
    ContextObject, LeaseRequest, ScopeEnvelope, SwitchEvidence, TransferPackage,
    authorize_context, authorize_lease, authorize_transfer, validate_project_switch,
)


def scope(project: str = "prj_alpha", session: str = "ses_one") -> ScopeEnvelope:
    return ScopeEnvelope(
        "wsp_main", project, "agt_worker", session, "ws_build", "lease_one", "int_change", "corr_one",
    )


class ProjectStreamControlTests(unittest.TestCase):
    def test_foreign_private_and_untagged_context_fail_closed(self) -> None:
        items = (
            ContextObject("local", "project", "prj_alpha", "memory", "internal", "evd_one"),
            ContextObject("foreign", "project", "prj_beta", "memory", "internal", "evd_two"),
            ContextObject("global-private", "global", None, "prompt", "internal", "evd_three"),
            ContextObject("untagged", "project", "prj_alpha", "source", "", ""),
        )
        result = authorize_context(scope(), items)
        self.assertEqual(result.decision, "deny")
        self.assertEqual(result.allowed_source_ids, ("local",))
        self.assertEqual(set(result.denied_source_ids), {"foreign", "global-private", "untagged"})

    def test_approved_transfer_targets_destination_and_never_private_memory(self) -> None:
        package = TransferPackage(
            "xfer_generic", "prj_alpha", "prj_beta", "sanitized_capability", ("evd_one",),
            "MIT", (), ("test_one",), True, True, True,
        )
        self.assertEqual(authorize_transfer(package).decision, "allow")
        private = replace(package, includes_private_memory=True)
        self.assertEqual(authorize_transfer(private).decision, "deny")

    def test_one_session_cannot_hold_foreign_writable_leases(self) -> None:
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        first = LeaseRequest(scope("prj_alpha"), True, expiry, ("read", "write"), ("project-a",), {"writes": 1})
        second = LeaseRequest(scope("prj_beta"), True, expiry, ("read", "write"), ("project-b",), {"writes": 1})
        self.assertEqual(authorize_lease(second, (first,)).decision, "deny")

    def test_project_switch_requires_teardown_and_denial_evidence(self) -> None:
        passed = SwitchEvidence(True, True, True, True, True, True, True, True)
        self.assertEqual(validate_project_switch(scope("prj_alpha"), scope("prj_beta", "ses_two"), passed).decision, "allow")
        failed = SwitchEvidence(True, True, True, False, True, True, True, False)
        self.assertEqual(validate_project_switch(scope("prj_alpha"), scope("prj_beta", "ses_two"), failed).decision, "deny")


if __name__ == "__main__":
    unittest.main()
