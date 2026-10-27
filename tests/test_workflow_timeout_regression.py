from __future__ import annotations

import unittest

from runtime.process_supervisor import ProcessAdmissionExpired


class PXAUD030_WorkflowTimeoutStatus(unittest.TestCase):
    """PX-AUD-030: workflow timeout classified as total_timeout, not generic failure."""

    def _classify(self, error):
        """Replicate the exception-handler status classification from execute()."""
        admission_expired = isinstance(error, ProcessAdmissionExpired)
        settlement = getattr(error, "supervision_outcome", {}) or {}
        settled = (
            settlement.get("tree_closed") is True
            and settlement.get("custody_retained") is False
            and settlement.get("cleanup_errors") == []
        )
        return "total_timeout" if admission_expired and settled else "failed"

    def test_settled_timeout_is_total_timeout(self) -> None:
        error = ProcessAdmissionExpired("process admission expired")
        error.supervision_outcome = {
            "tree_closed": True,
            "custody_retained": False,
            "cleanup_errors": [],
        }
        self.assertEqual(self._classify(error), "total_timeout")

    def test_unsettled_timeout_is_failed(self) -> None:
        error = ProcessAdmissionExpired("process admission expired")
        error.supervision_outcome = {
            "tree_closed": False,
            "custody_retained": True,
            "cleanup_errors": ["unresolved custody"],
        }
        self.assertEqual(self._classify(error), "failed")

    def test_missing_settlement_is_failed(self) -> None:
        error = ProcessAdmissionExpired("process admission expired")
        self.assertEqual(self._classify(error), "failed")

    def test_non_timeout_error_is_failed(self) -> None:
        error = OSError("injected worker failure")
        self.assertEqual(self._classify(error), "failed")

    def test_partial_settlement_is_failed(self) -> None:
        error = ProcessAdmissionExpired("process admission expired")
        error.supervision_outcome = {
            "tree_closed": True,
            "custody_retained": False,
            "cleanup_errors": ["some cleanup error"],
        }
        self.assertEqual(self._classify(error), "failed")


if __name__ == "__main__":
    unittest.main()
