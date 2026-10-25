from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from runtime.scheduler import ResourceScheduler, ResourcePolicy, Admission
from tests.support.fixtures import scheduler_snapshot


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


class PXAUD076_PathAliasNormalization(unittest.TestCase):
    """PX-AUD-076: string-based path ownership misses normalized path aliases."""

    def _snapshot(self, **overrides) -> dict:
        return scheduler_snapshot(**overrides)

    def test_same_path_different_alias_detected(self) -> None:
        scheduler = ResourceScheduler()
        scheduler.admit("job-1", "light", self._snapshot(),
                        owned_paths=("workspace/src",))
        result = scheduler.admit("job-2", "light", self._snapshot(),
                                 owned_paths=("workspace/other/../src",))
        self.assertFalse(result.admitted)
        self.assertEqual(result.reason, "file ownership overlaps job-1")

    def test_path_with_dot_segments_normalized(self) -> None:
        scheduler = ResourceScheduler()
        scheduler.admit("job-1", "light", self._snapshot(),
                        owned_paths=("workspace/./src",))
        result = scheduler.admit("job-2", "light", self._snapshot(),
                                 owned_paths=("workspace/src",))
        self.assertFalse(result.admitted)
        self.assertEqual(result.reason, "file ownership overlaps job-1")

    def test_distinct_paths_not_overlapping(self) -> None:
        scheduler = ResourceScheduler()
        result1 = scheduler.admit("job-1", "light", self._snapshot(),
                                  owned_paths=("workspace/src",))
        result2 = scheduler.admit("job-2", "light", self._snapshot(),
                                  owned_paths=("workspace/lib",))
        self.assertTrue(result1.admitted)
        self.assertTrue(result2.admitted)

    def test_backslash_and_slash_equivalence(self) -> None:
        scheduler = ResourceScheduler()
        scheduler.admit("job-1", "light", self._snapshot(),
                        owned_paths=("workspace\\src",))
        result = scheduler.admit("job-2", "light", self._snapshot(),
                                 owned_paths=("workspace/src",))
        self.assertFalse(result.admitted)
        self.assertEqual(result.reason, "file ownership overlaps job-1")


if __name__ == "__main__":
    unittest.main()
