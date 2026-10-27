from __future__ import annotations

import unittest

from runtime.capability_scheduler import Scheduler, Resources, Task


class PXAUD082_DeepDAGNoRecursionError(unittest.TestCase):
    """PX-AUD-082: deep legal-shaped DAG must not raise RecursionError."""

    def _build_chain(self, count: int) -> list[Task]:
        tasks = []
        for i in range(count):
            deps = [f"task-{i - 1}"] if i > 0 else []
            tasks.append(Task(
                id=f"task-{i}",
                capability="noop",
                dependencies=deps,
                resources=Resources.from_mapping({"cpu_cores": 1}),
            ))
        return tasks

    def test_deep_chain_validates_without_recursion_error(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 100}))
        for task in self._build_chain(1100):
            scheduler.add(task)
        scheduler.validate_dag()

    def test_deep_chain_simulates(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 100}))
        for task in self._build_chain(1100):
            scheduler.add(task)
        result = scheduler.simulate()
        self.assertTrue(result["valid"])

    def test_cycle_still_detected(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        scheduler.add(Task(id="a", capability="noop", dependencies=["b"],
                           resources=Resources.from_mapping({"cpu_cores": 1})))
        scheduler.add(Task(id="b", capability="noop", dependencies=["a"],
                           resources=Resources.from_mapping({"cpu_cores": 1})))
        with self.assertRaises(ValueError) as ctx:
            scheduler.validate_dag()
        self.assertIn("dependency cycle", str(ctx.exception))

    def test_missing_dependency_still_detected(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        scheduler.add(Task(id="a", capability="noop", dependencies=["missing"],
                           resources=Resources.from_mapping({"cpu_cores": 1})))
        with self.assertRaises(ValueError) as ctx:
            scheduler.validate_dag()
        self.assertIn("missing dependency", str(ctx.exception))

    def test_normal_small_dag_still_works(self) -> None:
        scheduler = Scheduler(Resources.from_mapping({"cpu_cores": 10}))
        scheduler.add(Task(id="a", capability="noop",
                           resources=Resources.from_mapping({"cpu_cores": 1})))
        scheduler.add(Task(id="b", capability="noop", dependencies=["a"],
                           resources=Resources.from_mapping({"cpu_cores": 1})))
        scheduler.validate_dag()
        result = scheduler.simulate()
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
