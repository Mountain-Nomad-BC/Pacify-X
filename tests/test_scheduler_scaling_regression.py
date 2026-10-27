from __future__ import annotations

import unittest

from runtime.capability_scheduler import Scheduler, Resources, Task


class PXAUD083_SchedulerScaling(unittest.TestCase):
    """PXAUD-083: simulated scheduler reverse-dependency index avoids full scans."""

    def _independent_tasks(self, count: int) -> list[Task]:
        return [
            Task(
                id=f"task-{i}",
                capability="noop",
                resources=Resources.from_mapping({"cpu_cores": 1}),
            )
            for i in range(count)
        ]

    def test_independent_tasks_simulate(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 100}))
        for task in self._independent_tasks(50):
            scheduler.add(task)
        result = scheduler.simulate()
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["completed"]), 50)

    def test_downstream_count_zero_for_independent_tasks(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        task = Task(id="task-1", capability="noop",
                    resources=Resources.from_mapping({"cpu_cores": 1}))
        scheduler.add(task)
        score, factors = scheduler.score(task)
        self.assertEqual(factors["dependency_unblock"], 0.0)

    def test_downstream_count_correct_for_dependent_tasks(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        t1 = Task(id="task-1", capability="noop",
                  resources=Resources.from_mapping({"cpu_cores": 1}))
        t2 = Task(id="task-2", capability="noop", dependencies=["task-1"],
                  resources=Resources.from_mapping({"cpu_cores": 1}))
        t3 = Task(id="task-3", capability="noop", dependencies=["task-1"],
                  resources=Resources.from_mapping({"cpu_cores": 1}))
        scheduler.add(t1)
        scheduler.add(t2)
        scheduler.add(t3)
        score, factors = scheduler.score(t1)
        self.assertEqual(factors["dependency_unblock"], 2.0 / 2.0)

    def test_reverse_index_maintained_on_add(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        t1 = Task(id="task-1", capability="noop",
                  resources=Resources.from_mapping({"cpu_cores": 1}))
        t2 = Task(id="task-2", capability="noop", dependencies=["task-1"],
                  resources=Resources.from_mapping({"cpu_cores": 1}))
        scheduler.add(t1)
        scheduler.add(t2)
        self.assertEqual(scheduler._dependents.get("task-1"), {"task-2"})
        self.assertNotIn("task-2", scheduler._dependents)

    def test_large_independent_set_simulates(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 100}))
        for task in self._independent_tasks(800):
            scheduler.add(task)
        result = scheduler.simulate()
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["completed"]), 800)


if __name__ == "__main__":
    unittest.main()
