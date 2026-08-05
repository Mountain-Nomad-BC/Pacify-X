from __future__ import annotations

import unittest
from pathlib import Path

from runtime.capability_scheduler import (
    describe_scheduling_capability,
    list_scheduling_capabilities,
    simulate_schedule,
    validate_scheduling_layer,
)


ROOT = Path(__file__).resolve().parents[1]


def task(identifier: str, **overrides):
    value = {
        "id": identifier,
        "capability": identifier,
        "priority": 500,
        "state": "pending",
        "resources": {"cpu_cores": 1},
        "acceptance": {},
    }
    value.update(overrides)
    return value


class CapabilitySchedulerTests(unittest.TestCase):
    def test_layer_denominators_and_lazy_contracts(self) -> None:
        result = validate_scheduling_layer(ROOT)
        self.assertTrue(result["valid"], result)
        self.assertEqual(
            result["counts"],
            {
                "capabilities": 30,
                "owners": 30,
                "workflows": 5,
                "policies": 3,
                "schemas": 8,
            },
        )
        listing = list_scheduling_capabilities(ROOT)
        self.assertTrue(listing["metadata_only"])
        self.assertEqual(listing["count"], 30)
        described = describe_scheduling_capability(ROOT, "priority-queue-scheduler")
        self.assertTrue(described["valid"])
        self.assertIn("authoritative_contract", described["contract"])

    def test_dependency_order_and_deterministic_replay(self) -> None:
        payload = {
            "now": "2026-01-01T00:00:00Z",
            "resources": {"cpu_cores": 2},
            "workload": {
                "tasks": [
                    task("b", priority=900, dependencies=["a"]),
                    task("a", priority=100),
                ]
            },
        }
        first = simulate_schedule(payload)
        second = simulate_schedule(payload)
        self.assertTrue(first["valid"], first)
        self.assertEqual(first["completed"], ["a", "b"])
        self.assertEqual(first["decision_hash"], second["decision_hash"])
        self.assertTrue(first["observe_only"])

    def test_cycle_and_missing_dependency_fail_closed(self) -> None:
        cycle = simulate_schedule(
            {
                "resources": {},
                "workload": {
                    "tasks": [
                        task("a", dependencies=["b"]),
                        task("b", dependencies=["a"]),
                    ]
                },
            }
        )
        self.assertFalse(cycle["valid"])
        self.assertIn("dependency cycle", cycle["errors"][0])
        missing = simulate_schedule(
            {
                "resources": {},
                "workload": {"tasks": [task("a", dependencies=["missing"])]},
            }
        )
        self.assertFalse(missing["valid"])
        self.assertIn("missing dependency", missing["errors"][0])

    def test_approval_resource_privacy_budget_and_retry_gates(self) -> None:
        tasks = [
            task("approval", approval_required=True),
            task("resource", resources={"cpu_cores": 99}),
            task("privacy", privacy="restricted", resources={"network": "external"}),
            task("budget", budget={"maximum_cost": 1, "estimated_cost": 2}),
            task("retry", attempt=2),
        ]
        result = simulate_schedule(
            {
                "resources": {"cpu_cores": 2, "network": "external"},
                "policy": {"external_network": "deny"},
                "workload": {"tasks": tasks},
            }
        )
        self.assertFalse(result["valid"])
        blocked = result["events"][-1]["blocked"]
        self.assertIn("approval_required", blocked["approval"])
        self.assertIn("resource_unavailable", blocked["resource"])
        self.assertIn("privacy_policy_denied", blocked["privacy"])
        self.assertIn("budget_exhausted", blocked["budget"])
        self.assertIn("retry_requires_idempotency_or_compensation", blocked["retry"])

    def test_scoring_records_normalized_factors_and_preserves_acceptance(self) -> None:
        result = simulate_schedule(
            {
                "now": "2026-01-01T00:00:00Z",
                "resources": {"cpu_cores": 1},
                "workload": {
                    "tasks": [
                        task(
                            "a",
                            acceptance={
                                "required_quality": 0.9,
                                "expected_success": 0.8,
                            },
                        )
                    ]
                },
            }
        )
        self.assertTrue(result["valid"], result)
        dispatch = result["events"][0]
        self.assertEqual(dispatch["event"], "would_dispatch")
        self.assertTrue(all(0 <= value <= 1 for value in dispatch["factors"].values()))
        self.assertEqual(
            result["execution_authority"], "none; dispatch events are plans only"
        )


if __name__ == "__main__":
    unittest.main()
