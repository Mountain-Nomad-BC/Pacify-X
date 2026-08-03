from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from runtime.workspace_manager import (
    activate_project,
    correct_memory,
    current_project,
    discover_projects,
    ingest_memory,
    initialize_workspace,
    maintain_memory,
    memory_status,
    list_workflows,
    list_projects,
    release_project,
    reconcile_memory,
    rebuild_workspace_projections,
    renew_project,
    search_memory,
    transition_memory,
    transition_project,
    workspace_status,
    workspace_monitor,
    run_workflow_request,
    show_project,
)


ROOT = Path(__file__).parents[1]


class WorkspaceManagerTests(unittest.TestCase):
    def _workspace_with_projects(self, root: Path) -> Path:
        workspace = root / "workspace"
        preview = initialize_workspace(workspace, workspace_id="wsp_test", apply=False)
        self.assertTrue(preview["valid"])
        self.assertFalse(workspace.exists())
        applied = initialize_workspace(workspace, workspace_id="wsp_test", apply=True)
        self.assertTrue(applied["applied"])
        alpha = workspace / "projects" / "alpha"
        beta = workspace / "projects" / "beta"
        alpha.mkdir()
        beta.mkdir()
        (alpha / "notes.md").write_text("# Decision\n- Preserve evidence and validate project memory.\n", encoding="utf-8")
        (beta / "README.md").write_text("# Beta\n\nIndependent project.\n", encoding="utf-8")
        admitted = discover_projects(workspace, source_root=ROOT, apply=True)
        self.assertTrue(admitted["valid"])
        self.assertEqual(admitted["registered_count"], 2)
        return workspace

    def test_workspace_init_is_previewable_idempotent_and_persists_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "engineering"
            preview = initialize_workspace(workspace, workspace_id="wsp_engineering", apply=False)
            self.assertTrue(preview["approval_required"])
            self.assertFalse(workspace.exists())
            created = initialize_workspace(workspace, workspace_id="wsp_engineering", apply=True)
            self.assertTrue(created["applied"])
            for name in ("projects", "projects_tracking", "repo_quarantine", "shared_capabilities"):
                self.assertTrue((workspace / name).is_dir())
            self.assertTrue((workspace / "projects_tracking/project-registry.json").is_file())
            self.assertTrue((workspace / "projects_tracking/PROJECT_MANAGEMENT.md").is_file())
            repeated = initialize_workspace(workspace, workspace_id="wsp_engineering", apply=True)
            self.assertTrue(repeated["already_initialized"])
            self.assertTrue(repeated["valid"])
            config = workspace / "engineering-workspace.toml"
            config.write_text(config.read_text(encoding="utf-8").replace("default_minutes = 60", "default_minutes = 30"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configuration integrity seal"):
                list_projects(workspace)

    def test_drop_discovery_commissions_projects_and_creates_isolated_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            registry = json.loads((workspace / "projects_tracking/project-registry.json").read_text(encoding="utf-8"))
            self.assertEqual({item["project_id"] for item in registry["projects"]}, {"prj_alpha", "prj_beta"})
            roots = {Path(item["memory_root"]).as_posix() for item in registry["projects"]}
            self.assertEqual(len(roots), 2)
            for item in registry["projects"]:
                self.assertTrue((workspace / item["memory_root"]).is_dir())
                self.assertTrue((workspace / item["project_management"]).is_file())
            repeated = discover_projects(workspace, source_root=ROOT, apply=True)
            self.assertEqual(repeated["admitted"], [])
            self.assertEqual(repeated["registered_count"], 2)
            self.assertTrue(workspace_status(workspace, source_root=ROOT)["valid"])
            monitor = workspace_monitor(workspace, source_root=ROOT)
            self.assertTrue(monitor["valid"])
            self.assertEqual({item["project_id"] for item in monitor["memory"]}, {"prj_alpha", "prj_beta"})
            self.assertTrue(monitor["integrations"]["smoke_tested"])

    def test_active_session_memory_and_project_switch_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            first = activate_project(workspace, "prj_alpha")
            self.assertTrue(first["activated"])
            self.assertEqual(len(list_projects(workspace)["projects"]), 2)
            self.assertIn("session_operator", show_project(workspace, "prj_alpha")["active_sessions"])
            self.assertTrue(renew_project(workspace, minutes=30)["renewed"])
            source = workspace / "projects/alpha/notes.md"
            ingested = ingest_memory(workspace, "prj_alpha", (source,), source_root=ROOT, apply=True)
            self.assertTrue(ingested["valid"])
            memory_id = ingested["outputs"]["memory_ids"][0]
            self.assertEqual(search_memory(workspace, "prj_alpha", "evidence memory", actor_id="agent_operator")["results"], [])
            transition_memory(workspace, "prj_alpha", memory_id, "validated", ("test-validation",), apply=True)
            transition_memory(workspace, "prj_alpha", memory_id, "certified", ("test-certification",), apply=True)
            results = search_memory(workspace, "prj_alpha", "evidence project memory", actor_id="agent_operator")["results"]
            self.assertEqual([item["memory_id"] for item in results], [memory_id])
            correction = correct_memory(
                workspace, "prj_alpha", memory_id, "mem-corrected", source,
                title="Corrected project decision", summary="Current corrected memory with evidence",
                memory_type="decision", apply=True,
            )
            self.assertTrue(correction["applied"])
            empty = workspace / "projects/alpha/empty.md"
            empty.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "textual evidence"):
                correct_memory(
                    workspace, "prj_alpha", memory_id, "mem-empty", empty,
                    title="Invalid", summary="Invalid empty evidence", apply=True,
                )
            self.assertEqual(
                [item["memory_id"] for item in search_memory(workspace, "prj_alpha", "project memory", actor_id="agent_operator")["results"]],
                [memory_id],
            )
            transition_memory(workspace, "prj_alpha", "mem-corrected", "validated", ("correction-reviewed",), apply=True)
            transition_memory(workspace, "prj_alpha", "mem-corrected", "certified", ("correction-certified",), apply=True)
            self.assertEqual(
                [item["memory_id"] for item in search_memory(workspace, "prj_alpha", "corrected memory", actor_id="agent_operator")["results"]],
                ["mem-corrected"],
            )
            with self.assertRaisesRegex(ValueError, "does not own"):
                search_memory(workspace, "prj_alpha", "evidence", actor_id="agent_spoofed")
            denied = activate_project(workspace, "prj_beta")
            self.assertFalse(denied["valid"])
            switched = activate_project(workspace, "prj_beta", context_reset_confirmed=True)
            self.assertTrue(switched["activated"])
            self.assertTrue(switched["switch"]["decision"] == "active")
            with self.assertRaisesRegex(ValueError, "outside the active project session"):
                search_memory(workspace, "prj_alpha", "evidence", actor_id="agent_operator")
            transfer_request = Path(directory) / "transfer.json"
            transfer_request.write_text(json.dumps({
                "schema_version": "1.0", "workflow_id": "cross_project_transfer",
                "project_id": "prj_beta", "session_id": "session_operator", "idempotency_key": "transfer_alpha_beta_001",
                "approved_effects": ["read_local", "write_workspace"],
                "payload": {
                    "source": "notes.md", "destination": "imports/alpha-note.md",
                    "package": {
                        "transfer_id": "transfer_alpha_beta", "source_project_id": "prj_alpha",
                        "destination_project_id": "prj_beta", "content_kind": "sanitized_capability",
                        "provenance": ["projects/alpha/notes.md"], "license": "internal-reference",
                        "assumptions": ["destination reviews imported content"], "tests": ["hash equality"],
                        "sanitization_passed": True, "human_approved": True,
                        "destination_owned": True, "includes_private_memory": False,
                    },
                },
            }, indent=2) + "\n", encoding="utf-8")
            transferred = run_workflow_request(workspace, transfer_request, source_root=ROOT, apply=True)
            self.assertTrue(transferred["valid"])
            self.assertEqual(
                (workspace / "projects/beta/imports/alpha-note.md").read_bytes(),
                (workspace / "projects/alpha/notes.md").read_bytes(),
            )
            self.assertEqual(current_project(workspace)["active"]["project_id"], "prj_beta")
            released = release_project(workspace, context_reset_confirmed=True)
            self.assertTrue(released["released"])
            self.assertIsNone(current_project(workspace)["active"])
            paused = transition_project(workspace, "prj_beta", "pause", ("test-pause",), apply=True)
            self.assertEqual(paused["state"], "paused")
            with self.assertRaisesRegex(ValueError, "cannot be activated"):
                activate_project(workspace, "prj_beta")
            resumed = transition_project(workspace, "prj_beta", "resume", ("test-resume",), apply=True)
            self.assertEqual(resumed["state"], "registered")

    def test_memory_maintenance_is_append_only_and_status_is_project_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            ingest_memory(workspace, "prj_alpha", (workspace / "projects/alpha/notes.md",), source_root=ROOT, apply=True)
            maintained = maintain_memory(workspace, "prj_alpha", source_root=ROOT, apply=True)
            self.assertTrue(maintained["valid"])
            self.assertEqual(maintained["outputs"]["memory_health_report"], "index_published")
            status = memory_status(workspace, "prj_alpha", actor_id="agent_operator")
            self.assertTrue(status["valid"])
            self.assertGreater(status["record_count"], 0)
            self.assertEqual(status["index"]["authoritative_generation"], "000001")
            self.assertFalse(status["index"]["hard_delete"])
            orphan = Path(status["memory_root"]) / ".memory-control/index/generations/000002"
            orphan.mkdir(parents=True)
            (orphan / "entries.json").write_text("[]\n", encoding="utf-8")
            preview = reconcile_memory(workspace, "prj_alpha", apply=False)
            self.assertEqual(preview["orphan_generations"], ["000002"])
            reconciled = reconcile_memory(workspace, "prj_alpha", apply=True)
            self.assertTrue(reconciled["valid"])
            self.assertFalse(reconciled["hard_delete"])
            self.assertFalse(orphan.exists())
            self.assertTrue((Path(reconciled["quarantine"]) / "000002/entries.json").is_file())
            self.assertTrue((Path(reconciled["quarantine"]) / "QUARANTINE_MANIFEST.json").is_file())

    def test_three_sessions_run_three_projects_without_cross_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            gamma = workspace / "projects/gamma"
            gamma.mkdir()
            (gamma / "README.md").write_text("# Gamma\n", encoding="utf-8")
            discover_projects(workspace, source_root=ROOT, apply=True)
            activate_project(workspace, "prj_alpha", agent_id="agent_alpha", session_id="session_alpha")
            activate_project(workspace, "prj_beta", agent_id="agent_beta", session_id="session_beta")
            activate_project(workspace, "prj_gamma", agent_id="agent_gamma", session_id="session_gamma")
            status = workspace_status(workspace, source_root=ROOT)
            self.assertTrue(status["valid"])
            self.assertEqual(status["active_session_count"], 3)
            self.assertEqual(status["active_project_ids"], ["prj_alpha", "prj_beta", "prj_gamma"])
            self.assertEqual(current_project(workspace, session_id="session_alpha")["active"]["project_id"], "prj_alpha")
            self.assertEqual(current_project(workspace, session_id="session_beta")["active"]["project_id"], "prj_beta")
            with self.assertRaisesRegex(ValueError, "outside the active project session"):
                search_memory(workspace, "prj_beta", "anything", actor_id="agent_alpha", session_id="session_alpha")
            release_project(workspace, session_id="session_alpha", context_reset_confirmed=True)
            release_project(workspace, session_id="session_beta", context_reset_confirmed=True)
            release_project(workspace, session_id="session_gamma", context_reset_confirmed=True)
            self.assertEqual(workspace_status(workspace, source_root=ROOT)["active_session_count"], 0)

    def test_workspace_status_detects_project_record_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            record = workspace / "projects/alpha/.engineering-bootstrap/project-record.json"
            value = json.loads(record.read_text(encoding="utf-8"))
            value["cross_project_access"] = "explicit-only"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertTrue(any("project record hash drift" in error for error in status["errors"]))

    def test_workspace_registry_rebuilds_from_integrity_checked_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            registry = workspace / "projects_tracking/project-registry.json"
            registry.write_text("{broken projection\n", encoding="utf-8")
            preview = rebuild_workspace_projections(workspace, apply=False)
            self.assertEqual(preview["registered_count"], 2)
            self.assertEqual(preview["active_project_ids"], ["prj_alpha"])
            rebuilt = rebuild_workspace_projections(workspace, apply=True)
            self.assertTrue(rebuilt["applied"])
            status = workspace_status(workspace, source_root=ROOT)
            self.assertTrue(status["valid"])
            self.assertEqual(status["active_project_id"], "prj_alpha")

    def test_expired_active_lease_blocks_memory_and_workspace_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            active_path = workspace / "projects_tracking/sessions/session_operator.json"
            active = json.loads(active_path.read_text(encoding="utf-8"))
            active["expires_utc"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            active_path.write_text(json.dumps(active, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lease expired"):
                search_memory(workspace, "prj_alpha", "anything", actor_id="agent_operator")
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertIn("active_session_lease_expired", status["errors"])

    def test_lease_renewal_cannot_exceed_cumulative_workspace_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            session = workspace / "projects_tracking/sessions/session_operator.json"
            value = json.loads(session.read_text(encoding="utf-8"))
            value["created_utc"] = (datetime.now(timezone.utc) - timedelta(minutes=479)).isoformat()
            session.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cumulative active lifetime"):
                renew_project(workspace, minutes=2)

    def test_registered_workflow_runs_from_json_with_idempotent_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            self.assertEqual(list_workflows(ROOT)["workflow_count"], 17)
            request = {
                "schema_version": "1.0", "workflow_id": "nightly_project_health",
                "project_id": "prj_alpha", "session_id": "session_operator", "idempotency_key": "health_alpha_001",
                "approved_effects": ["read_local"],
                "payload": {"metrics": {name: 1.0 for name in ("tests", "security", "evidence", "dependencies", "memory", "operations")}},
            }
            request_path = temp / "request.json"
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            preview = run_workflow_request(workspace, request_path, source_root=ROOT, apply=False)
            self.assertTrue(preview["approval_required"])
            executed = run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            self.assertTrue(executed["valid"])
            self.assertEqual(executed["receipt"]["result"]["status"], "completed")
            replay = run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            self.assertTrue(replay["replayed"])
            request["payload"]["metrics"]["tests"] = 0.5
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "idempotency key"):
                run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            malformed = {**request, "idempotency_key": "health_alpha_bad", "payload": {}}
            request_path.write_text(json.dumps(malformed, indent=2) + "\n", encoding="utf-8")
            checkpoint_count = len(tuple((workspace / "projects_tracking/checkpoints").rglob("*.json")))
            with self.assertRaisesRegex(ValueError, "payload contract"):
                run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            self.assertEqual(len(tuple((workspace / "projects_tracking/checkpoints").rglob("*.json"))), checkpoint_count)
            missing_effect = {**request, "idempotency_key": "health_alpha_effect", "approved_effects": []}
            request_path.write_text(json.dumps(missing_effect, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "effects are not fully approved"):
                run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            denial_events = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (workspace / "projects_tracking/events").glob("*.json")
            ]
            self.assertTrue(any(item["kind"] == "workflow-policy-denied" for item in denial_events))

    def test_workflow_paths_reject_parent_traversal_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            request_path = temp / "traversal.json"
            request_path.write_text(json.dumps({
                "schema_version": "1.0", "workflow_id": "continuous_improvement",
                "project_id": "prj_alpha", "session_id": "session_operator",
                "idempotency_key": "traversal_denied_001", "approved_effects": ["read_local"],
                "payload": {"sources": ["../beta/README.md"]},
            }, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "parent traversal"):
                run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)

    def test_pending_workspace_intent_is_detected_and_explicitly_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            events = workspace / "projects_tracking/events"
            from runtime.project_control_plane import append_event
            append_event(events, "workspace-operation-intent", {
                "operation_id": "interrupted-fixture", "operation": "activate",
                "project_id": "prj_alpha", "session_id": "session_operator",
            })
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertEqual(status["pending_operation_ids"], ["interrupted-fixture"])
            rebuilt = rebuild_workspace_projections(workspace, apply=True)
            self.assertIn("interrupted-fixture", rebuilt["pending_operation_ids"])
            self.assertTrue(workspace_status(workspace, source_root=ROOT)["valid"])

    def test_shared_capability_promotion_is_evidence_gated_and_not_auto_activated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            candidate = workspace / "projects/alpha/candidate-tool.py"
            candidate.write_text("def check():\n    return True\n", encoding="utf-8")
            request_path = temp / "promote.json"
            request_path.write_text(json.dumps({
                "schema_version": "1.0", "workflow_id": "shared_capability_promote",
                "project_id": "prj_alpha", "session_id": "session_operator",
                "idempotency_key": "promote_candidate_001",
                "approved_effects": ["read_local", "write_workspace"],
                "payload": {
                    "candidate": "candidate-tool.py",
                    "evidence": {
                        "capability_id": "candidate-tool", "version": "1.0.0",
                        "provenance": ["projects/alpha/candidate-tool.py"],
                        "license": "internal-reference", "tests": ["unit"],
                        "benchmark": ["golden"], "approval_id": "approval-001",
                        "tests_passed": True, "benchmark_passed": True,
                    },
                },
            }, indent=2) + "\n", encoding="utf-8")
            result = run_workflow_request(workspace, request_path, source_root=ROOT, apply=True)
            release = result["receipt"]["result"]["outputs"]["shared_capability_release"]
            self.assertEqual(release["decision"], "released")
            self.assertFalse(release["automatic_activation"])
            target = Path(release["target"])
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), candidate.read_bytes())


if __name__ == "__main__":
    unittest.main()
