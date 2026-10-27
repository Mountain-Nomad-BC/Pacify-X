from __future__ import annotations

from unittest.mock import patch, MagicMock
import unittest

from runtime.gremlin.host_enforcement_backend import (
    ProcessSupervisorEnforcementBackend,
    _JOBOBJECT_PROCESS_COUNT,
)


class FakeSupervisor:
    def __init__(self, handle=None):
        self.handle = handle
        self.terminated = False

    def terminate(self, code):
        self.terminated = True


class PXAUD003_PartialFreezeNotSuccess(unittest.TestCase):
    """PX-AUD-003: partial freeze falsely reported as fully frozen."""

    def test_all_pids_suspended_is_frozen(self) -> None:
        backend = ProcessSupervisorEnforcementBackend()
        supervisor = FakeSupervisor(handle=MagicMock())
        with patch.object(backend, "_supervisor_for", return_value=supervisor), \
             patch.object(backend, "_job_process_pids", return_value=[100, 101, 102]), \
             patch.object(backend, "_suspend_pid", side_effect=lambda pid, *, job_handle: True):
            result = backend.freeze({"job_object_id": "job-1", "pid": 100})
        self.assertTrue(result["frozen"])
        self.assertEqual(result["pids"], [100, 101, 102])
        self.assertEqual(result["failed_pids"], [])

    def test_partial_suspend_is_not_frozen(self) -> None:
        backend = ProcessSupervisorEnforcementBackend()
        supervisor = FakeSupervisor(handle=MagicMock())
        with patch.object(backend, "_supervisor_for", return_value=supervisor), \
             patch.object(backend, "_job_process_pids", return_value=[100, 101, 102]), \
             patch.object(backend, "_suspend_pid", side_effect=lambda pid, *, job_handle: pid != 101):
            result = backend.freeze({"job_object_id": "job-1", "pid": 100})
        self.assertFalse(result["frozen"])
        self.assertEqual(result["pids"], [100, 102])
        self.assertEqual(result["expected_pids"], [100, 101, 102])
        self.assertEqual(result["failed_pids"], [101])

    def test_none_suspended_is_not_frozen(self) -> None:
        backend = ProcessSupervisorEnforcementBackend()
        supervisor = FakeSupervisor(handle=MagicMock())
        with patch.object(backend, "_supervisor_for", return_value=supervisor), \
             patch.object(backend, "_job_process_pids", return_value=[100, 101]), \
             patch.object(backend, "_suspend_pid", side_effect=lambda pid, *, job_handle: False):
            result = backend.freeze({"job_object_id": "job-1", "pid": 100})
        self.assertFalse(result["frozen"])
        self.assertEqual(result["pids"], [])
        self.assertEqual(result["expected_pids"], [100, 101])
        self.assertEqual(result["failed_pids"], [100, 101])


class PXAUD004_SixtyFourMemberJobLimit(unittest.TestCase):
    """PX-AUD-004: fixed 64-member job query prevents complete freeze verification."""

    def test_job_process_id_list_capped_at_64(self) -> None:
        self.assertEqual(_JOBOBJECT_PROCESS_COUNT, 64)

    def test_freeze_reports_expected_and_failed_pids(self) -> None:
        backend = ProcessSupervisorEnforcementBackend()
        supervisor = FakeSupervisor(handle=MagicMock())
        pids = list(range(64))
        with patch.object(backend, "_supervisor_for", return_value=supervisor), \
             patch.object(backend, "_job_process_pids", return_value=pids), \
             patch.object(backend, "_suspend_pid", side_effect=lambda pid, *, job_handle: True):
            result = backend.freeze({"job_object_id": "job-1", "pid": 0})
        self.assertTrue(result["frozen"])
        self.assertEqual(len(result["expected_pids"]), 64)
        self.assertEqual(result["failed_pids"], [])


if __name__ == "__main__":
    unittest.main()



