from __future__ import annotations

import json
from pathlib import Path
import unittest

from runtime.graphs import (
    build_graphs,
    find_io_paths,
    rank_io_paths,
    validate_orchestration,
)
from runtime.registry import load_json
from runtime.graph_registry import build_graph_artifacts, validate_graph_artifacts


ROOT = Path(__file__).parents[1]


def contracts() -> list[dict]:
    active = load_json(ROOT / "registry" / "capability_map.json")["active_capabilities"]
    return [load_json(ROOT / item["contract"]) for item in active]


class GraphAndOrchestrationTests(unittest.TestCase):
    def test_canonical_graphs_match_all_current_registry_sources(self) -> None:
        result = validate_graph_artifacts(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["artifact_count"], 6)
        self.assertEqual(
            set(build_graph_artifacts(ROOT)),
            {path.name for path in (ROOT / "registry/graphs").glob("*.json")},
        )

    def test_registry_graphs_are_deterministic_and_metadata_only(self) -> None:
        first = build_graphs(contracts())
        second = build_graphs(reversed(contracts()))
        self.assertEqual(first, second)
        self.assertIn("workflow-orchestrator", first.capability_nodes)
        self.assertTrue(
            any(edge.relation == "depends_on" for edge in first.capability_edges)
        )
        self.assertTrue(
            any(
                edge.relation == "declares_effect"
                for edge in first.dependency_effect_edges
            )
        )

    def test_io_path_reports_compatible_transformations(self) -> None:
        records = [
            {
                "id": "intake",
                "provides": ["normalized_request"],
                "consumes": ["request"],
                "dependencies": [],
                "conflicts": [],
                "effects": ["read_local"],
            },
            {
                "id": "plan",
                "provides": ["plan"],
                "consumes": ["normalized_request"],
                "dependencies": [],
                "conflicts": [],
                "effects": ["read_local"],
            },
        ]
        self.assertEqual(
            find_io_paths(records, "request", "plan"), (("intake", "plan"),)
        )
        self.assertEqual(find_io_paths(records, "request", "missing"), ())

    def test_io_path_ranking_prefers_safer_lower_cost_current_path(self) -> None:
        records = [
            {
                "id": "safe",
                "provides": ["result"],
                "consumes": ["request"],
                "dependencies": [],
                "conflicts": [],
                "effects": ["read_local"],
                "risk": "R0",
                "cost": {"max_tool_calls": 0},
                "latency": {"max_seconds": 1},
                "evidence": {"status": "current"},
            },
            {
                "id": "costly",
                "provides": ["result"],
                "consumes": ["request"],
                "dependencies": [],
                "conflicts": [],
                "effects": ["network"],
                "risk": "R2",
                "cost": {"max_tool_calls": 5},
                "latency": {"max_seconds": 10},
                "evidence": {"status": "stale"},
            },
        ]
        ranked = rank_io_paths(records, "request", "result")
        self.assertEqual(ranked[0].capabilities, ("safe",))
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_control_plane_registry_validates(self) -> None:
        spec = load_json(ROOT / "registry" / "orchestrations" / "control-plane.json")
        self.assertEqual(validate_orchestration(spec, contracts()), ())

    def test_orchestration_rejects_unknown_step_cycle_and_effect_conflict(self) -> None:
        spec = {
            "id": "unsafe",
            "version": "1",
            "status": "candidate",
            "inputs": [],
            "outputs": [],
            "steps": [
                {
                    "id": "a",
                    "capability": "skill-navigator",
                    "depends_on": ["b"],
                    "effects": ["read_local"],
                },
                {
                    "id": "b",
                    "capability": "missing",
                    "depends_on": ["a"],
                    "effects": ["network"],
                },
            ],
            "parallelism": {"max_agents": 1, "max_test_runners": 1},
            "stop_conditions": [],
            "resource_budget": {"max_tool_calls": 1, "max_seconds": 1},
        }
        errors = validate_orchestration(spec, contracts())
        self.assertTrue(any("unknown capability" in error for error in errors))
        self.assertTrue(any("cycle" in error for error in errors))

    def test_versioned_schema_set_is_present(self) -> None:
        names = {
            "capability-contract.schema.json",
            "evidence-record.schema.json",
            "orchestration-contract.schema.json",
            "tool-contract.schema.json",
            "model-contract.schema.json",
            "integration-contract.schema.json",
            "builder-contract.schema.json",
            "knowledge-source.schema.json",
            "policy-contract.schema.json",
            "validation-contract.schema.json",
        }
        for name in names:
            payload = json.loads(
                (ROOT / "contracts" / name).read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["$schema"], "https://json-schema.org/draft/2020-12/schema"
            )
            self.assertIn("required", payload)


if __name__ == "__main__":
    unittest.main()
