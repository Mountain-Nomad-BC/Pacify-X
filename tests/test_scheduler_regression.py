from __future__ import annotations

import math
import unittest

from runtime.scheduler import ResourceScheduler, ResourcePolicy, Admission
from tests.support.fixtures import scheduler_snapshot


class PXAUD074_PressureTelemetryFinite(unittest.TestCase):
    """PX-AUD-074: resource scheduler admits nonfinite/absent pressure telemetry."""

    def _snapshot(self, **overrides) -> dict:
        base = {
            "memory_percent": 50.0,
            "gpu_percent": 30.0,
            "wsl_memory_percent": 40.0,
            "docker_memory_percent": 40.0,
            "agents": 1,
        }
        base.update(overrides)
        return base

    def test_normal_snapshot_admitted(self) -> None:
        scheduler = ResourceScheduler()
        result = scheduler.admit("work-1", "light", self._snapshot())
        self.assertTrue(result.admitted)
        self.assertEqual(result.reason, "resource policy admitted work")

    def test_nan_memory_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(memory_percent=float("nan")))
        self.assertIn("memory_percent must be finite", str(ctx.exception))

    def test_inf_memory_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(memory_percent=float("inf")))
        self.assertIn("memory_percent must be finite", str(ctx.exception))

    def test_nan_gpu_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(gpu_percent=float("nan")))
        self.assertIn("gpu_percent must be finite", str(ctx.exception))

    def test_inf_gpu_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(gpu_percent=float("-inf")))
        self.assertIn("gpu_percent must be finite", str(ctx.exception))

    def test_none_memory_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(memory_percent=None))
        self.assertIn("memory_percent is required", str(ctx.exception))

    def test_bool_memory_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(memory_percent=True))
        self.assertIn("memory_percent must be a number, not bool", str(ctx.exception))

    def test_nan_agents_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(agents=float("nan")))
        self.assertIn("agents must be finite", str(ctx.exception))

    def test_none_agents_rejected(self) -> None:
        scheduler = ResourceScheduler()
        with self.assertRaises(ValueError) as ctx:
            scheduler.admit("work-1", "light", self._snapshot(agents=None))
        self.assertIn("agents is required", str(ctx.exception))

    def test_high_memory_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        result = scheduler.admit("work-1", "light", self._snapshot(memory_percent=90.0))
        self.assertFalse(result.admitted)
        self.assertEqual(result.reason, "memory pressure threshold reached")

    def test_high_gpu_percent_rejected(self) -> None:
        scheduler = ResourceScheduler()
        result = scheduler.admit("work-1", "light", self._snapshot(gpu_percent=95.0))
        self.assertFalse(result.admitted)
        self.assertEqual(result.reason, "GPU pressure threshold reached")


if __name__ == "__main__":
    unittest.main()
