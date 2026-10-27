from __future__ import annotations

import math
import unittest

from runtime.capability_scheduler import Scheduler, Resources, Task


class PXAUD078_NonfiniteTaskChargeRejected(unittest.TestCase):
    """PX-AUD-078: nonfinite task charge bypasses simulated budget ceiling."""

    def _task(self, budget) -> Task:
        return Task(
            id="task-1", capability="noop",
            resources=Resources.from_mapping({"cpu_cores": 1}),
            budget=budget,
        )

    def test_nan_estimated_cost_blocked(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 10.0, "estimated_cost": float("nan")})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertFalse(ok)
        self.assertIn("budget_exhausted", reasons)

    def test_inf_estimated_cost_blocked(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 10.0, "estimated_cost": float("inf")})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertFalse(ok)
        self.assertIn("budget_exhausted", reasons)

    def test_nan_maximum_cost_blocked(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": float("nan"), "estimated_cost": 5.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertFalse(ok)
        self.assertIn("budget_exhausted", reasons)

    def test_inf_maximum_cost_blocked(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": float("inf"), "estimated_cost": 5.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertFalse(ok)
        self.assertIn("budget_exhausted", reasons)

    def test_estimated_above_maximum_blocked(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 5.0, "estimated_cost": 10.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertFalse(ok)
        self.assertIn("budget_exhausted", reasons)

    def test_estimated_at_maximum_allowed(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 10.0, "estimated_cost": 10.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertTrue(ok)
        self.assertNotIn("budget_exhausted", reasons)

    def test_estimated_below_maximum_allowed(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 10.0, "estimated_cost": 5.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertTrue(ok)
        self.assertNotIn("budget_exhausted", reasons)

    def test_no_budget_fields_allowed(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertTrue(ok)
        self.assertNotIn("budget_exhausted", reasons)

    def test_estimated_cost_zero_blocked_when_maximum_zero(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        task = self._task({"maximum_cost": 0.0, "estimated_cost": 0.0})
        scheduler.add(task)
        ok, reasons = scheduler.eligible(task)
        self.assertTrue(ok)
        self.assertNotIn("budget_exhausted", reasons)


if __name__ == "__main__":
    unittest.main()
