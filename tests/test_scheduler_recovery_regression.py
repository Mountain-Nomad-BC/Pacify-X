from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from runtime.scheduler import ResourceScheduler, ResourcePolicy, Admission
from tests.support.fixtures import telemetry as _telemetry


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _scheduler(lost_seconds=120) -> ResourceScheduler:
    return ResourceScheduler(ResourcePolicy(lost_worker_seconds=lost_seconds))


class PXAUD075_LostWorkerRecoveryPreservesLiveJobs(unittest.TestCase):
    """PX-AUD-075: lost-worker recovery must not release jobs still owned by live workers."""

    def test_recover_lost_keeps_job_when_live_worker_still_assigned(self) -> None:
        scheduler = _scheduler()
        scheduler.admit("job-1", "light", _telemetry())
        scheduler.assign_worker("worker-a", "job-1")
        scheduler.assign_worker("worker-b", "job-1")
        scheduler.heartbeat("worker-a", NOW - timedelta(seconds=200))
        scheduler.heartbeat("worker-b", NOW)
        recovered = scheduler.recover_lost(NOW)
        self.assertEqual(recovered, ())
        self.assertIn("worker-b", scheduler._assignments)
        self.assertEqual(scheduler._assignments["worker-b"], "job-1")
        self.assertIn("job-1", scheduler._lanes)

    def test_recover_lost_releases_job_when_all_workers_lost(self) -> None:
        scheduler = _scheduler()
        scheduler.admit("job-1", "light", _telemetry())
        scheduler.assign_worker("worker-a", "job-1")
        scheduler.heartbeat("worker-a", NOW - timedelta(seconds=200))
        recovered = scheduler.recover_lost(NOW)
        self.assertEqual(recovered, ("job-1",))
        self.assertNotIn("job-1", scheduler._lanes)
        self.assertNotIn("worker-a", scheduler._assignments)

    def test_recover_lost_no_lost_workers(self) -> None:
        scheduler = _scheduler()
        scheduler.admit("job-1", "light", _telemetry())
        scheduler.assign_worker("worker-a", "job-1")
        scheduler.heartbeat("worker-a", NOW)
        recovered = scheduler.recover_lost(NOW)
        self.assertEqual(recovered, ())
        self.assertIn("job-1", scheduler._lanes)

    def test_normal_admit_and_release_still_works(self) -> None:
        scheduler = _scheduler()
        result = scheduler.admit("job-1", "light", _telemetry())
        self.assertTrue(result.admitted)
        scheduler.assign_worker("worker-a", "job-1")
        released = scheduler.release("job-1")
        self.assertTrue(released)
        self.assertNotIn("job-1", scheduler._lanes)


if __name__ == "__main__":
    unittest.main()
