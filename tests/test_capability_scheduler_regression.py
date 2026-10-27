from __future__ import annotations

import unittest

from runtime.capability_scheduler import Resources, Scheduler, Task


class PXAUD077_NegativeResourceNeedsRejected(unittest.TestCase):
    """PX-AUD-077: capability scheduler accepts negative resource needs."""

    def test_negative_cpu_cores_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"cpu_cores": -2.0})
        self.assertIn("cpu_cores must be non-negative", str(ctx.exception))

    def test_negative_ram_gb_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"ram_gb": -1.5})
        self.assertIn("ram_gb must be non-negative", str(ctx.exception))

    def test_negative_gpu_count_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"gpu_count": -1})
        self.assertIn("gpu_count must be non-negative", str(ctx.exception))

    def test_negative_vram_gb_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"vram_gb": -0.5})
        self.assertIn("vram_gb must be non-negative", str(ctx.exception))

    def test_negative_disk_gb_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"disk_gb": -10.0})
        self.assertIn("disk_gb must be non-negative", str(ctx.exception))

    def test_bool_cpu_cores_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"cpu_cores": True})
        self.assertIn("cpu_cores must be a non-negative number, not bool", str(ctx.exception))

    def test_non_numeric_cpu_cores_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Resources.from_mapping({"cpu_cores": "two"})
        self.assertIn("cpu_cores must be a non-negative number", str(ctx.exception))

    def test_zero_resources_accepted(self) -> None:
        resources = Resources.from_mapping({})
        self.assertEqual(resources.cpu_cores, 0.0)
        self.assertEqual(resources.ram_gb, 0.0)
        self.assertEqual(resources.gpu_count, 0)
        self.assertEqual(resources.vram_gb, 0.0)
        self.assertEqual(resources.disk_gb, 0.0)

    def test_positive_resources_accepted(self) -> None:
        resources = Resources.from_mapping({
            "cpu_cores": 4.0, "ram_gb": 16.0, "gpu_count": 1,
            "vram_gb": 8.0, "disk_gb": 100.0, "network": "local",
        })
        self.assertEqual(resources.cpu_cores, 4.0)
        self.assertEqual(resources.gpu_count, 1)
        self.assertEqual(resources.network, "local")

    def test_scheduler_rejects_negative_task_resources(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 1}))
        with self.assertRaises(ValueError) as ctx:
            scheduler.add(Task(
                id="task-1", capability="noop",
                resources=Resources.from_mapping({"cpu_cores": -2.0}),
            ))
        self.assertIn("cpu_cores must be non-negative", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
