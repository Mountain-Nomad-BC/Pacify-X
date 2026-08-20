from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.dashboard_api import (
    _hardware,
    _knowledge_core,
    _memory,
    _provider_activity,
    build_snapshot,
    query_catalog,
    query_graph,
)
from runtime.provider_budget import _sealed


ROOT = Path(__file__).resolve().parents[1]


class DashboardApiTests(unittest.TestCase):
    def test_visual_fixture_declares_demo_data_and_tracks_current_denominators(self) -> None:
        preview = (ROOT / "extension/tests/preview.html").read_text(encoding="utf-8")
        counts = build_snapshot(ROOT)["counts"]
        self.assertIn("DEMO DATA · VISUAL LAYOUT FIXTURE · NOT OPERATIONAL EVIDENCE", preview)
        for fragment in (
            f"skills: {counts['skills']}",
            f"agents_registered: {counts['agents_registered']}",
            f"workflow_definitions: {counts['workflow_definitions']}",
            f"graphRecords: {counts['graph_records']}",
            f"graphEdges: {counts['graph_edges']}",
        ):
            self.assertIn(fragment, preview)

    def test_knowledge_core_rejects_absolute_and_traversing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "outside-knowledge.json"
            result = _knowledge_core(
                root,
                [
                    {"id": "absolute", "location": str(outside)},
                    {"id": "traversal", "location": "../outside-knowledge.json"},
                ],
            )
        self.assertEqual(result["record_count"], 2)
        self.assertTrue(all(not row["available"] for row in result["records"]))
        self.assertEqual(
            {row["reason"] for row in result["invalid_records"]},
            {"declared_source_outside_project"},
        )

    def test_hardware_sensor_probe_uses_bounded_derived_ttl_cache(self) -> None:
        report = {"valid": True, "telemetry": {"available_count": 3}}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "runtime.hardware_routing.hardware_report", return_value=report
            ) as probe,
        ):
            root = Path(directory)
            first = _hardware(root, now=1000.0, cache_ttl_seconds=300.0)
            second = _hardware(root, now=1010.0, cache_ttl_seconds=300.0)
            forced = _hardware(
                root, now=1020.0, cache_ttl_seconds=300.0, force_refresh=True
            )
            expired = _hardware(root, now=1321.0, cache_ttl_seconds=300.0)
        self.assertEqual(first["cache"]["status"], "miss")
        self.assertEqual(second["cache"]["status"], "hit")
        self.assertEqual(second["cache"]["age_seconds"], 10.0)
        self.assertTrue(second["cache"]["fresh"])
        self.assertEqual(forced["cache"]["refresh_trigger"], "forced")
        self.assertEqual(expired["cache"]["status"], "miss")
        self.assertEqual(probe.call_count, 3)

    def test_corrupt_hardware_cache_is_rebuilt_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = (
                root
                / ".engineering-bootstrap"
                / "diagnostics"
                / "hardware-dashboard-cache.json"
            )
            cache.parent.mkdir(parents=True)
            cache.write_text("{broken", encoding="utf-8")
            with patch(
                "runtime.hardware_routing.hardware_report",
                return_value={"valid": True, "telemetry": {"available_count": 0}},
            ) as probe:
                result = _hardware(root, now=1000.0)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(result["cache"]["status"], "miss")
            self.assertIn("JSONDecodeError", result["cache"]["read_error"])
            rebuilt = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(
                rebuilt["schema_version"], "px.hardware-dashboard-cache/1.1"
            )
            self.assertEqual(len(rebuilt["report_sha256"]), 64)

    def test_tampered_or_future_hardware_cache_is_never_reused(self) -> None:
        report = {"valid": True, "telemetry": {"available_count": 1}}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "runtime.hardware_routing.hardware_report", return_value=report
            ) as probe,
        ):
            root = Path(directory)
            _hardware(root, now=1000.0)
            cache = (
                root
                / ".engineering-bootstrap"
                / "diagnostics"
                / "hardware-dashboard-cache.json"
            )
            payload = json.loads(cache.read_text(encoding="utf-8"))
            payload["report"]["telemetry"]["available_count"] = 99
            cache.write_text(json.dumps(payload), encoding="utf-8")
            rebuilt = _hardware(root, now=1010.0)
            payload = json.loads(cache.read_text(encoding="utf-8"))
            payload["sampled_epoch"] = 2000.0
            cache.write_text(json.dumps(payload), encoding="utf-8")
            future = _hardware(root, now=1020.0)
        self.assertEqual(rebuilt["cache"]["status"], "miss")
        self.assertIn("integrity", rebuilt["cache"]["read_error"])
        self.assertEqual(future["cache"]["status"], "miss")
        self.assertIn("future", future["cache"]["read_error"])
        self.assertEqual(probe.call_count, 3)

    def test_hardware_cache_ttl_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "TTL"):
            _hardware(ROOT, cache_ttl_seconds=3601.0)

    def test_snapshot_cardinalities_match_authoritative_sources(self) -> None:
        snapshot = build_snapshot(ROOT)
        runtime = snapshot["runtime"]
        self.assertEqual(runtime["core"]["schema_version"], "px.runtime-work-plane/1.0")
        self.assertIn("producer_trace_summary", runtime["core"])
        self.assertIn("execution_placement", runtime)
        gpu_policy = runtime["execution_placement"]["gpu_policy"]
        self.assertIn(gpu_policy["current_route"], {"cpu", "cuda-eligible"})
        self.assertIsInstance(gpu_policy["executor_ready"], bool)
        self.assertIn("host_startup", runtime)
        self.assertTrue(runtime["skill_index_integrity"]["valid"])
        self.assertIn("px_policy_enforced_during_direct_host_selection", runtime["skill_host_boundary"]["codex_host"])
        self.assertIn("legacy_direct_producers", runtime["bottlenecks"])
        agents = json.loads(
            (ROOT / "registry" / "agency_agent_registry.json").read_text(
                encoding="utf-8"
            )
        )["agents"]
        tools = json.loads(
            (ROOT / "registry" / "tools.json").read_text(encoding="utf-8")
        )["tools"]
        project = json.loads(
            (ROOT / "registry" / "project_stream_orchestrations.json").read_text(
                encoding="utf-8"
            )
        )["orchestrations"]
        skills = json.loads(
            (ROOT / "registry" / "skill_orchestrations.json").read_text(
                encoding="utf-8"
            )
        )["workflows"]
        bindings_payload = json.loads(
            (ROOT / "registry" / "workflow_execution_bindings.json").read_text(
                encoding="utf-8"
            )
        )
        bindings = next(
            bindings_payload[key]
            for key in ("bindings", "workflows", "records")
            if isinstance(bindings_payload.get(key), list)
        )
        self.assertEqual(snapshot["counts"]["agents"], len(agents))
        self.assertEqual(snapshot["counts"]["tools"], len(tools))
        self.assertEqual(
            snapshot["counts"]["skills"],
            len(list((ROOT / "registry" / "skill_packages").glob("*.json"))),
        )
        self.assertEqual(
            snapshot["counts"]["orchestrations_total"],
            len(project) + len(skills) + len(bindings),
        )
        self.assertEqual(
            snapshot["counts"]["workflow_definitions"], len(project) + len(skills)
        )
        self.assertEqual(snapshot["counts"]["workflow_validator_bindings"], 15)
        self.assertEqual(snapshot["counts"]["workflow_runtime_bindings"], 6)
        effects = json.loads(
            (ROOT / "registry" / "effect_surface_ownership.json").read_text(
                encoding="utf-8"
            )
        )["records"]
        self.assertEqual(snapshot["counts"]["effects"], len(effects))
        self.assertEqual(snapshot["mode"], "canonical-dashboard-api")

    def test_every_skill_is_reachable_through_bounded_pagination(self) -> None:
        index = json.loads(
            (ROOT / ".px" / "skill-index.json").read_text(encoding="utf-8")
        )
        expected = sum(
            row.get("domain") == "px-standard" and row.get("native")
            for row in index["records"]
        )
        ids: list[str] = []
        offset = 0
        while True:
            page = query_catalog(ROOT, "skills", offset=offset, limit=37)
            ids.extend(item["id"] for item in page["items"])
            if not page["has_more"]:
                break
            offset += page["limit"]
        self.assertEqual(len(ids), expected)
        self.assertEqual(len(set(ids)), expected)

    def test_preserved_vendor_and_enterprise_skill_tabs_are_distinct(self) -> None:
        preserved = query_catalog(ROOT, "preserved-skills", limit=200)
        vendor = query_catalog(ROOT, "microsoft-skills", limit=200)
        enterprise = query_catalog(ROOT, "enterprise-skills", limit=200)
        self.assertGreaterEqual(preserved["total"], 176)
        self.assertEqual(vendor["total"], 6)
        self.assertEqual(enterprise["total"], 20)
        self.assertTrue(
            all(
                item["details"]["domain"] == "microsoft-vendor"
                for item in vendor["items"]
            )
        )
        self.assertTrue(
            all(item["details"].get("backup") for item in preserved["items"])
        )

    def test_agent_search_retains_details_and_provenance(self) -> None:
        page = query_catalog(
            ROOT, "agents", query="multi-agent systems architect", limit=10
        )
        self.assertGreaterEqual(page["filtered"], 1)
        item = page["items"][0]
        self.assertIn("details", item)
        self.assertIn("manifest_path", item["details"])
        self.assertEqual(item["agent_model"]["schema_version"], "1.0")
        self.assertEqual(item["agent_model"]["identity"]["id"], item["id"])
        self.assertGreater(item["agent_model"]["readiness"]["total"], 0)
        self.assertIn("boundaries", item["agent_model"])
        self.assertEqual(page["source"], "runtime.dashboard_api")

    def test_snapshot_exposes_conservative_machine_readable_readiness(self) -> None:
        readiness = build_snapshot(ROOT)["readiness"]
        self.assertEqual(readiness["assessment"], "structural-agent-readiness")
        self.assertEqual(len(readiness["dimensions"]), 9)
        self.assertEqual(
            {item["id"] for item in readiness["dimensions"]},
            {f"D{i}" for i in range(1, 10)},
        )
        self.assertTrue(all(item["score"] <= 4 for item in readiness["dimensions"]))
        self.assertIn("advisory", readiness["authority"])
        self.assertGreater(len(readiness["safe_now"]), 0)
        self.assertGreater(len(readiness["requires_fresh_gate"]), 0)

    def test_unconfigured_canonical_memory_is_explicitly_detached(self) -> None:
        snapshot = build_snapshot(ROOT)
        memory = snapshot["memory"]
        self.assertFalse(memory["instrumented"])
        self.assertEqual(memory["status"], "detached")
        self.assertEqual(memory["authority"], "canonical workspace memory vault")
        self.assertIn("workspaceRoot", memory["error"])
        self.assertNotIn(
            "Canonical memory telemetry unavailable",
            {item["title"] for item in snapshot["attention"]},
        )

    def test_configured_empty_workspace_memory_is_valid_but_not_attached_or_ready(
        self,
    ) -> None:
        with patch(
            "runtime.workspace_manager.workspace_monitor",
            return_value={
                "workspace": {"valid": True, "active_session_count": 0},
                "memory": [],
                "memory_valid": True,
                "memory_errors": [],
                "integrations": {"valid": True},
            },
        ):
            memory = _memory(ROOT, ROOT)
        self.assertFalse(memory["instrumented"])
        self.assertTrue(memory["configuration_valid"])
        self.assertFalse(memory["project_registered"])
        self.assertFalse(memory["lease_active"])
        self.assertFalse(memory["retrieval_ready"])
        self.assertEqual(memory["status"], "empty")
        self.assertEqual(memory["record_count"], 0)

    def test_expired_workspace_lease_never_reports_retrieval_ready(self) -> None:
        with patch(
            "runtime.workspace_manager.workspace_monitor",
            return_value={
                "workspace": {
                    "valid": False,
                    "registered_count": 1,
                    "active_session_count": 0,
                    "expired_session_ids": ["vscode-dashboard"],
                    "errors": [
                        "active_session_lease_expired:vscode-dashboard"
                    ],
                },
                "memory": [],
                "memory_valid": False,
                "memory_errors": [],
                "integrations": {"valid": False},
            },
        ):
            memory = _memory(ROOT, ROOT)
        self.assertFalse(memory["instrumented"])
        self.assertFalse(memory["configuration_valid"])
        self.assertTrue(memory["project_registered"])
        self.assertFalse(memory["lease_active"])
        self.assertFalse(memory["retrieval_ready"])
        self.assertEqual(memory["lease"]["state"], "expired")
        self.assertEqual(memory["status"], "degraded")

    def test_workflow_catalog_combines_all_owned_workflow_kinds(self) -> None:
        page = query_catalog(ROOT, "workflows", limit=100)
        kinds = {item["kind"] for item in page["items"]}
        self.assertEqual(
            kinds, {"project-orchestration", "skill-orchestration", "execution-binding"}
        )
        self.assertEqual(page["total"], page["filtered"])

    def test_execution_bindings_have_stable_human_readable_identity(self) -> None:
        page = query_catalog(ROOT, "workflows", limit=100, sort="id")
        bindings = [
            item for item in page["items"] if item["kind"] == "execution-binding"
        ]
        self.assertGreater(len(bindings), 0)
        self.assertTrue(
            all(item["id"].startswith("execution-binding:") for item in bindings)
        )
        self.assertTrue(
            all(not item["label"].startswith("workflows-") for item in bindings)
        )
        self.assertTrue(
            all(
                item["summary"] and item["details"].get("entrypoint") in item["summary"]
                for item in bindings
            )
        )

    def test_every_workflow_has_a_human_readable_label_and_machine_identity(
        self,
    ) -> None:
        page = query_catalog(ROOT, "workflows", limit=100, sort="id")
        self.assertGreater(page["total"], 52)
        for item in page["items"]:
            self.assertTrue(item["id"])
            self.assertTrue(item["label"])
            self.assertNotEqual(item["label"], item["id"])
            self.assertNotIn("_", item["label"])
            self.assertFalse(item["label"].startswith("Workflow "))

    def test_graph_query_returns_bounded_real_typed_neighborhood(self) -> None:
        result = query_graph(ROOT, query="Anthropologist", max_nodes=8, max_edges=12)
        self.assertIsNotNone(result["selected"])
        self.assertLessEqual(len(result["nodes"]), 8)
        self.assertLessEqual(len(result["edges"]), 12)
        keys = {item["key"] for item in result["nodes"]}
        self.assertIn(result["selected"], keys)
        self.assertTrue(
            all(
                edge["source"] in keys and edge["target"] in keys
                for edge in result["edges"]
            )
        )
        self.assertTrue(
            all(edge["relation"] and edge["why"] for edge in result["edges"])
        )
        self.assertGreater(len(result["search_results"]), 0)
        self.assertEqual(result["search_results"][0]["rank"], 1)

    def test_graph_typo_is_ranked_globally_before_neighborhood_expansion(self) -> None:
        result = query_graph(ROOT, query="Anthropxlogist", max_nodes=8, max_edges=12)
        self.assertEqual(result["selected"], "agent:agency.academic.anthropologist")
        self.assertEqual(result["search_results"][0]["title"], "Anthropologist")
        self.assertIn("fuzzy-token", result["search_results"][0]["match"])

    def test_graph_depth_can_expand_beyond_initial_neighborhood_with_hard_bounds(
        self,
    ) -> None:
        result = query_graph(ROOT, depth=4, max_nodes=96, max_edges=192)
        self.assertEqual(result["depth"], 4)
        self.assertLessEqual(len(result["nodes"]), 96)
        self.assertLessEqual(len(result["edges"]), 192)
        clamped = query_graph(ROOT, depth=99, max_nodes=9999, max_edges=9999)
        self.assertEqual(clamped["depth"], 6)
        self.assertEqual(clamped["limits"], {"max_nodes": 500, "max_edges": 1000})

    def test_graph_overview_accounts_for_every_node_and_edge_without_raw_crowding(
        self,
    ) -> None:
        overview = query_graph(ROOT, mode="overview")
        self.assertEqual(overview["mode"], "overview")
        self.assertFalse(overview["truncated"])
        self.assertEqual(overview["covered_nodes"], overview["total_nodes"])
        self.assertEqual(overview["covered_edges"], overview["total_edges"])
        self.assertTrue(all(item["kind"] == "cluster" for item in overview["nodes"]))
        self.assertTrue(all(item["member_count"] > 0 for item in overview["nodes"]))
        self.assertTrue(all(item["count"] > 0 for item in overview["edges"]))
        self.assertLess(len(overview["nodes"]), overview["total_nodes"])

    def test_graph_cluster_drill_selects_a_member_of_the_requested_kind(self) -> None:
        overview = query_graph(ROOT, mode="overview")
        requested = overview["nodes"][0]["cluster_kind"]
        detail = query_graph(ROOT, mode="neighborhood", cluster=requested)
        selected = next(item for item in detail["nodes"] if item["key"] == detail["selected"])
        self.assertEqual(detail["mode"], "neighborhood")
        self.assertEqual(detail["cluster"], requested)
        self.assertEqual(selected["kind"], requested)

    def test_graph_query_rejects_invalid_direction(self) -> None:
        with self.assertRaisesRegex(ValueError, "direction"):
            query_graph(ROOT, direction="sideways")

    def test_repository_graph_query_uses_current_project_map(self) -> None:
        result = query_graph(
            ROOT, project=ROOT, view="repository", query="dashboard_api", max_nodes=12
        )
        self.assertEqual(result["view"], "repository")
        self.assertIn("architecture-graph.json", result["source"])
        self.assertIsNotNone(result["selected"])
        self.assertTrue(any("dashboard_api" in item["key"] for item in result["nodes"]))

    def test_missing_repository_graph_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = query_graph(ROOT, project=project, view="repository")
        self.assertFalse(result["available"])
        self.assertIsNone(result["total_nodes"])
        self.assertEqual(result["build_action"]["operation"], "project-map build")

    def test_bare_duplicate_graph_id_requires_qualified_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry").mkdir()
            (root / "registry/cognitive_map_index.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"key": "skill:same", "id": "same", "title": "Skill Same"},
                            {"key": "agent:same", "id": "same", "title": "Agent Same"},
                        ],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            result = query_graph(root, node="same")
        self.assertIsNone(result["selected"])
        self.assertEqual(
            {row["key"] for row in result["ambiguous_matches"]},
            {"skill:same", "agent:same"},
        )

    def test_enterprise_catalog_is_separate_complete_and_disabled_by_default(
        self,
    ) -> None:
        enterprise = json.loads(
            (ROOT / "registry" / "ms_enterprise_catalog.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot = build_snapshot(ROOT)
        self.assertEqual(snapshot["enterprise"]["catalog_id"], "px-ms-enterprise")
        self.assertEqual(
            snapshot["counts"]["enterprise_skills"], len(enterprise["skills"])
        )
        self.assertEqual(
            snapshot["counts"]["enterprise_agents"], len(enterprise["agents"])
        )
        self.assertEqual(
            snapshot["enterprise"]["defaults"]["billable_services"], "disabled"
        )
        self.assertTrue(
            all(
                not row["default_enabled"]
                for row in enterprise["packs"]
                if row["id"]
                not in {
                    "ms-enterprise/governance",
                    "ms-enterprise/ui-accessibility",
                    "ms-enterprise/structured-memory",
                }
            )
        )
        self.assertTrue(
            all(
                row["status"] in {"disabled", "not-installed"}
                for row in enterprise["connectors"]
            )
        )
        self.assertEqual(
            query_catalog(ROOT, "enterprise-agents", limit=100)["total"],
            len(enterprise["agents"]),
        )
        self.assertEqual(
            query_catalog(ROOT, "enterprise-workflows", limit=100)["total"],
            len(enterprise["workflows"]),
        )

    def test_provider_activity_is_empty_without_an_enabled_budget(self) -> None:
        self.assertEqual(_provider_activity(ROOT), [])
        snapshot = build_snapshot(ROOT)
        self.assertEqual(snapshot["providerActivity"], [])
        self.assertEqual(snapshot["provenance"]["providerActivity"]["class"], "LIVE")

    def test_provider_activity_projects_active_budget_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry").mkdir()
            ledger_root = root / ".engineering-bootstrap" / "provider-budget"
            ledger_root.mkdir(parents=True)
            (root / "registry" / "provider_adapters.json").write_text(
                json.dumps(
                    {
                        "adapters": [
                            {
                                "provider_id": "openai",
                                "mode": "remote",
                                "admitted": True,
                                "status": "ready",
                                "billing_state": "actual",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "registry" / "provider_budget_policy.json").write_text(
                json.dumps(
                    {
                        "budgets": [
                            {
                                "budget_id": "daily",
                                "actor_id": "agent-a",
                                "provider_id": "openai",
                                "currency": "USD",
                                "enabled": True,
                                "hard_limit_microunits": 10_000_000,
                                "warning_threshold_microunits": 7_000_000,
                                "max_requests": 100,
                                "max_input_tokens": 1000,
                                "max_output_tokens": 1000,
                                "fallback_adapter_ids": ["fallback"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            state = _sealed(
                {
                    "schema_version": "px.provider-budget-ledger/1.0",
                    "revision": 1,
                    "budgets": {
                        "daily\u241fagent-a\u241fopenai": {
                            "settled_charge_microunits": 2_000_000,
                            "reserved_charge_microunits": 1_000_000,
                            "settled_input_tokens": 100,
                            "reserved_input_tokens": 20,
                            "settled_output_tokens": 50,
                            "reserved_output_tokens": 10,
                            "request_count": 2,
                        }
                    },
                    "invocations": {
                        "invoke-a": {
                            "budget_id": "daily",
                            "actor_id": "agent-a",
                            "provider_id": "openai",
                            "state": "reserved",
                            "billing_state": "actual",
                            "fallback_from": "primary-secret-never-exported",
                        }
                    },
                },
                "state_sha256",
            )
            (ledger_root / "ledger.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            rows = _provider_activity(root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["activityState"], "active")
        self.assertEqual(rows[0]["budgetPercent"], 30.0)
        self.assertEqual(rows[0]["budgetRemaining"], 7.0)
        self.assertTrue(rows[0]["fallbackActive"])
        self.assertNotIn("primary-secret-never-exported", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
