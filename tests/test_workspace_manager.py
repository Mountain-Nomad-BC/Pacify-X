from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from runtime.workspace_manager import (
    activate_project,
    browse_canonical_memory,
    capture_memory_source,
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
import runtime.workspace_manager as workspace_runtime
from runtime.file_lock import FileLock, FileLockTimeout
from runtime.event_ledger import validate_event_ledger
from runtime.test_profiles import ProcessingOrderBlocked


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
        (alpha / "notes.md").write_text(
            "# Decision\n- Preserve evidence and validate project memory.\n",
            encoding="utf-8",
        )
        (beta / "README.md").write_text(
            "# Beta\n\nIndependent project.\n", encoding="utf-8"
        )
        admitted = discover_projects(workspace, source_root=ROOT, apply=True)
        self.assertTrue(admitted["valid"])
        self.assertEqual(admitted["registered_count"], 2)
        return workspace

    def test_memory_capture_uses_active_project_scope_and_immutable_l0_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            source = workspace / "projects/alpha/notes.md"
            preview = capture_memory_source(
                workspace, "prj_alpha", source, source_kind="document"
            )
            self.assertFalse(preview["apply"])
            memory_root = workspace / "projects_tracking/projects/prj_alpha/memory"
            self.assertFalse((memory_root / preview["path"]).exists())
            applied = capture_memory_source(
                workspace, "prj_alpha", source, source_kind="document", apply=True
            )
            self.assertEqual(applied["event"]["scope"]["project_id"], "prj_alpha")
            self.assertTrue((memory_root / applied["path"]).is_file())
            with self.assertRaisesRegex(
                ValueError, "outside the active project session"
            ):
                capture_memory_source(
                    workspace,
                    "prj_beta",
                    workspace / "projects/beta/README.md",
                    source_kind="document",
                )

    def test_workspace_init_is_previewable_idempotent_and_persists_control_plane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "engineering"
            preview = initialize_workspace(
                workspace, workspace_id="wsp_engineering", apply=False
            )
            self.assertTrue(preview["approval_required"])
            self.assertFalse(workspace.exists())
            created = initialize_workspace(
                workspace, workspace_id="wsp_engineering", apply=True
            )
            self.assertTrue(created["applied"])
            for name in (
                "projects",
                "projects_tracking",
                "repo_quarantine",
                "shared_capabilities",
            ):
                self.assertTrue((workspace / name).is_dir())
            self.assertTrue(
                (workspace / "projects_tracking/project-registry.json").is_file()
            )
            self.assertTrue(
                (workspace / "projects_tracking/PROJECT_MANAGEMENT.md").is_file()
            )
            repeated = initialize_workspace(
                workspace, workspace_id="wsp_engineering", apply=True
            )
            self.assertTrue(repeated["already_initialized"])
            self.assertTrue(repeated["valid"])
            config = workspace / "engineering-workspace.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "default_minutes = 60", "default_minutes = 30"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "configuration integrity seal"):
                list_projects(workspace)

    def test_drop_discovery_commissions_projects_and_creates_isolated_tracking(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            registry = json.loads(
                (workspace / "projects_tracking/project-registry.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                {item["project_id"] for item in registry["projects"]},
                {"prj_alpha", "prj_beta"},
            )
            roots = {
                Path(item["memory_root"]).as_posix() for item in registry["projects"]
            }
            self.assertEqual(len(roots), 2)
            for item in registry["projects"]:
                self.assertTrue((workspace / item["memory_root"]).is_dir())
                self.assertTrue((workspace / item["project_management"]).is_file())
                project = workspace / item["path"]
                campaign = (
                    project
                    / ".engineering-bootstrap/processing-order/repair-campaign.json"
                )
                self.assertTrue(campaign.is_file())
                state = json.loads(campaign.read_text(encoding="utf-8"))
                self.assertEqual(state["phase"], "intake")
                self.assertTrue(state["intake_open"])
            repeated = discover_projects(workspace, source_root=ROOT, apply=True)
            self.assertEqual(repeated["admitted"], [])
            self.assertEqual(repeated["registered_count"], 2)
            self.assertTrue(workspace_status(workspace, source_root=ROOT)["valid"])
            monitor = workspace_monitor(workspace, source_root=ROOT)
            self.assertTrue(monitor["valid"])
            self.assertTrue(monitor["memory_valid"])
            self.assertEqual(
                {item["project_id"] for item in monitor["memory"]},
                {"prj_alpha", "prj_beta"},
            )
            self.assertTrue(all(item["integrity"]["valid"] for item in monitor["memory"]))
            self.assertTrue(all(item["status"] == "healthy" for item in monitor["memory"]))
            self.assertTrue(all("layer_counts" in item for item in monitor["memory"]))
            self.assertTrue(all("lifecycle_counts" in item for item in monitor["memory"]))
            self.assertTrue(monitor["integrations"]["smoke_tested"])

    def test_activation_fails_closed_when_managed_project_order_state_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            campaign = (
                workspace
                / "projects/alpha/.engineering-bootstrap/processing-order/repair-campaign.json"
            )
            campaign.unlink()
            with self.assertRaisesRegex(
                ProcessingOrderBlocked, "managed project is missing"
            ):
                activate_project(workspace, "prj_alpha")

    def test_active_session_memory_and_project_switch_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            first = activate_project(workspace, "prj_alpha")
            self.assertTrue(first["activated"])
            self.assertEqual(len(list_projects(workspace)["projects"]), 2)
            self.assertIn(
                "session_operator",
                show_project(workspace, "prj_alpha")["active_sessions"],
            )
            self.assertTrue(renew_project(workspace, minutes=30)["renewed"])
            source = workspace / "projects/alpha/notes.md"
            ingested = ingest_memory(
                workspace, "prj_alpha", (source,), source_root=ROOT, apply=True
            )
            self.assertTrue(ingested["valid"])
            memory_id = ingested["outputs"]["memory_ids"][0]
            self.assertEqual(
                search_memory(
                    workspace, "prj_alpha", "evidence memory", actor_id="agent_operator"
                )["results"],
                [],
            )
            transition_memory(
                workspace,
                "prj_alpha",
                memory_id,
                "validated",
                ("test-validation",),
                apply=True,
            )
            transition_memory(
                workspace,
                "prj_alpha",
                memory_id,
                "certified",
                ("test-certification",),
                apply=True,
            )
            results = search_memory(
                workspace,
                "prj_alpha",
                "evidence project memory",
                actor_id="agent_operator",
            )["results"]
            self.assertEqual([item["memory_id"] for item in results], [memory_id])
            browser = browse_canonical_memory(workspace, "evidence project memory")
            self.assertEqual([item["memory_id"] for item in browser["records"]], [memory_id])
            self.assertEqual(browser["records"][0]["authority"], "canonical workspace memory vault")
            self.assertEqual(len(browser["records"][0]["record_sha256"]), 64)
            correction = correct_memory(
                workspace,
                "prj_alpha",
                memory_id,
                "mem-corrected",
                source,
                title="Corrected project decision",
                summary="Current corrected memory with evidence",
                memory_type="decision",
                apply=True,
            )
            self.assertTrue(correction["applied"])
            empty = workspace / "projects/alpha/empty.md"
            empty.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "textual evidence"):
                correct_memory(
                    workspace,
                    "prj_alpha",
                    memory_id,
                    "mem-empty",
                    empty,
                    title="Invalid",
                    summary="Invalid empty evidence",
                    apply=True,
                )

            self.assertEqual(
                [
                    item["memory_id"]
                    for item in search_memory(
                        workspace,
                        "prj_alpha",
                        "project memory",
                        actor_id="agent_operator",
                    )["results"]
                ],
                [memory_id],
            )
            transition_memory(
                workspace,
                "prj_alpha",
                "mem-corrected",
                "validated",
                ("correction-reviewed",),
                apply=True,
            )
            transition_memory(
                workspace,
                "prj_alpha",
                "mem-corrected",
                "certified",
                ("correction-certified",),
                apply=True,
            )
            self.assertEqual(
                [
                    item["memory_id"]
                    for item in search_memory(
                        workspace,
                        "prj_alpha",
                        "corrected memory",
                        actor_id="agent_operator",
                    )["results"]
                ],
                ["mem-corrected"],
            )
            with self.assertRaisesRegex(ValueError, "does not own"):
                search_memory(
                    workspace, "prj_alpha", "evidence", actor_id="agent_spoofed"
                )
            denied = activate_project(workspace, "prj_beta")
            self.assertFalse(denied["valid"])
            switched = activate_project(
                workspace, "prj_beta", context_reset_confirmed=True
            )
            self.assertTrue(switched["activated"])
            self.assertTrue(switched["switch"]["decision"] == "active")
            with self.assertRaisesRegex(
                ValueError, "outside the active project session"
            ):
                search_memory(
                    workspace, "prj_alpha", "evidence", actor_id="agent_operator"
                )
            transfer_request = Path(directory) / "transfer.json"
            transfer_request.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "workflow_id": "cross_project_transfer",
                        "project_id": "prj_beta",
                        "session_id": "session_operator",
                        "idempotency_key": "transfer_alpha_beta_001",
                        "approved_effects": ["read_local", "write_workspace"],
                        "payload": {
                            "source": "notes.md",
                            "destination": "imports/alpha-note.md",
                            "package": {
                                "transfer_id": "transfer_alpha_beta",
                                "source_project_id": "prj_alpha",
                                "destination_project_id": "prj_beta",
                                "content_kind": "sanitized_capability",
                                "provenance": ["projects/alpha/notes.md"],
                                "license": "internal-reference",
                                "assumptions": ["destination reviews imported content"],
                                "tests": ["hash equality"],
                                "sanitization_passed": True,
                                "human_approved": True,
                                "destination_owned": True,
                                "includes_private_memory": False,
                            },
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            transferred = run_workflow_request(
                workspace, transfer_request, source_root=ROOT, apply=True
            )
            self.assertTrue(transferred["valid"])
            self.assertEqual(
                (workspace / "projects/beta/imports/alpha-note.md").read_bytes(),
                (workspace / "projects/alpha/notes.md").read_bytes(),
            )
            self.assertEqual(
                current_project(workspace)["active"]["project_id"], "prj_beta"
            )
            released = release_project(workspace, context_reset_confirmed=True)
            self.assertTrue(released["released"])
            self.assertIsNone(current_project(workspace)["active"])
            paused = transition_project(
                workspace, "prj_beta", "pause", ("test-pause",), apply=True
            )
            self.assertEqual(paused["state"], "paused")
            with self.assertRaisesRegex(ValueError, "cannot be activated"):
                activate_project(workspace, "prj_beta")
            resumed = transition_project(
                workspace, "prj_beta", "resume", ("test-resume",), apply=True
            )
            self.assertEqual(resumed["state"], "registered")

    def test_canonical_browser_preserves_filters_and_reports_pageable_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            alpha = workspace / "projects/alpha"
            second = alpha / "operations.md"
            second.write_text(
                "# Operations\n\nAgent Studio and Workflow Studio retain immutable revisions.\n",
                encoding="utf-8",
            )
            ingested = ingest_memory(
                workspace,
                "prj_alpha",
                (alpha / "notes.md", second),
                source_root=ROOT,
                apply=True,
            )
            memory_ids = ingested["outputs"]["memory_ids"]
            self.assertGreater(len(memory_ids), 1)
            for memory_id in memory_ids:
                transition_memory(
                    workspace,
                    "prj_alpha",
                    memory_id,
                    "validated",
                    ("test-validation",),
                    apply=True,
                )
                transition_memory(
                    workspace,
                    "prj_alpha",
                    memory_id,
                    "certified",
                    ("test-certification",),
                    apply=True,
                )
            first_page = browse_canonical_memory(workspace, "", limit=1)
            self.assertEqual(first_page["filters"]["project_id"], "")
            self.assertEqual(first_page["matched_count"], len(memory_ids))
            self.assertEqual(first_page["returned_count"], 1)
            self.assertTrue(first_page["has_more"])
            absent = browse_canonical_memory(
                workspace, "", project_id="prj_beta", limit=1
            )
            self.assertEqual(absent["filters"]["project_id"], "prj_beta")
            self.assertEqual(absent["matched_count"], 0)

    def test_memory_maintenance_is_append_only_and_status_is_project_bound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            ingest_memory(
                workspace,
                "prj_alpha",
                (workspace / "projects/alpha/notes.md",),
                source_root=ROOT,
                apply=True,
            )
            maintained = maintain_memory(
                workspace, "prj_alpha", source_root=ROOT, apply=True
            )
            self.assertTrue(maintained["valid"])
            self.assertEqual(
                maintained["outputs"]["memory_health_report"], "index_published"
            )
            status = memory_status(workspace, "prj_alpha", actor_id="agent_operator")
            self.assertTrue(status["valid"])
            self.assertGreater(status["record_count"], 0)
            self.assertEqual(status["index"]["authoritative_generation"], "000001")
            self.assertFalse(status["index"]["hard_delete"])
            orphan = (
                Path(status["memory_root"]) / ".memory-control/index/generations/000002"
            )
            orphan.mkdir(parents=True)
            (orphan / "entries.json").write_text("[]\n", encoding="utf-8")
            preview = reconcile_memory(workspace, "prj_alpha", apply=False)
            self.assertEqual(preview["orphan_generations"], ["000002"])
            reconciled = reconcile_memory(workspace, "prj_alpha", apply=True)
            self.assertTrue(reconciled["valid"])
            self.assertFalse(reconciled["hard_delete"])
            self.assertFalse(orphan.exists())
            self.assertTrue(
                (Path(reconciled["quarantine"]) / "000002/entries.json").is_file()
            )
            self.assertTrue(
                (Path(reconciled["quarantine"]) / "QUARANTINE_MANIFEST.json").is_file()
            )

    def test_three_sessions_run_three_projects_without_cross_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            gamma = workspace / "projects/gamma"
            gamma.mkdir()
            (gamma / "README.md").write_text("# Gamma\n", encoding="utf-8")
            discover_projects(workspace, source_root=ROOT, apply=True)
            activate_project(
                workspace,
                "prj_alpha",
                agent_id="agent_alpha",
                session_id="session_alpha",
            )
            activate_project(
                workspace, "prj_beta", agent_id="agent_beta", session_id="session_beta"
            )
            activate_project(
                workspace,
                "prj_gamma",
                agent_id="agent_gamma",
                session_id="session_gamma",
            )
            status = workspace_status(workspace, source_root=ROOT)
            self.assertTrue(status["valid"])
            self.assertEqual(status["active_session_count"], 3)
            self.assertEqual(
                status["active_project_ids"], ["prj_alpha", "prj_beta", "prj_gamma"]
            )
            self.assertEqual(
                current_project(workspace, session_id="session_alpha")["active"][
                    "project_id"
                ],
                "prj_alpha",
            )
            self.assertEqual(
                current_project(workspace, session_id="session_beta")["active"][
                    "project_id"
                ],
                "prj_beta",
            )
            with self.assertRaisesRegex(
                ValueError, "outside the active project session"
            ):
                search_memory(
                    workspace,
                    "prj_beta",
                    "anything",
                    actor_id="agent_alpha",
                    session_id="session_alpha",
                )
            release_project(
                workspace, session_id="session_alpha", context_reset_confirmed=True
            )
            release_project(
                workspace, session_id="session_beta", context_reset_confirmed=True
            )
            release_project(
                workspace, session_id="session_gamma", context_reset_confirmed=True
            )
            self.assertEqual(
                workspace_status(workspace, source_root=ROOT)["active_session_count"], 0
            )

    def test_workspace_status_detects_project_record_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            record = (
                workspace / "projects/alpha/.engineering-bootstrap/project-record.json"
            )
            value = json.loads(record.read_text(encoding="utf-8"))
            value["cross_project_access"] = "explicit-only"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertTrue(
                any("project record hash drift" in error for error in status["errors"])
            )

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
            active["expires_utc"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
            active_path.write_text(
                json.dumps(active, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "session projection differs"):
                search_memory(
                    workspace, "prj_alpha", "anything", actor_id="agent_operator"
                )
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertTrue(
                any(
                    error.startswith("session_projection_invalid:")
                    for error in status["errors"]
                )
            )

    def test_lease_renewal_uses_a_sliding_idle_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            before = datetime.now(timezone.utc)
            renewed = renew_project(workspace, minutes=1440)
            expiry = datetime.fromisoformat(str(renewed["expires_utc"]))
            self.assertGreaterEqual(expiry, before + timedelta(minutes=1439))
            self.assertLessEqual(expiry, datetime.now(timezone.utc) + timedelta(minutes=1441))

    def test_registered_workflow_runs_from_json_with_idempotent_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            self.assertEqual(list_workflows(ROOT)["workflow_count"], 17)
            request = {
                "schema_version": "1.0",
                "workflow_id": "nightly_project_health",
                "project_id": "prj_alpha",
                "session_id": "session_operator",
                "idempotency_key": "health_alpha_001",
                "approved_effects": ["read_local"],
                "payload": {
                    "metrics": {
                        name: 1.0
                        for name in (
                            "tests",
                            "security",
                            "evidence",
                            "dependencies",
                            "memory",
                            "operations",
                        )
                    }
                },
            }
            request_path = temp / "request.json"
            request_path.write_text(
                json.dumps(request, indent=2) + "\n", encoding="utf-8"
            )
            preview = run_workflow_request(
                workspace, request_path, source_root=ROOT, apply=False
            )
            self.assertTrue(preview["approval_required"])
            executed = run_workflow_request(
                workspace, request_path, source_root=ROOT, apply=True
            )
            self.assertTrue(executed["valid"])
            self.assertEqual(executed["receipt"]["result"]["status"], "completed")
            replay = run_workflow_request(
                workspace, request_path, source_root=ROOT, apply=True
            )
            self.assertTrue(replay["replayed"])
            request["payload"]["metrics"]["tests"] = 0.5
            request_path.write_text(
                json.dumps(request, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "idempotency key"):
                run_workflow_request(
                    workspace, request_path, source_root=ROOT, apply=True
                )
            malformed = {
                **request,
                "idempotency_key": "health_alpha_bad",
                "payload": {},
            }
            request_path.write_text(
                json.dumps(malformed, indent=2) + "\n", encoding="utf-8"
            )
            checkpoint_count = len(
                tuple((workspace / "projects_tracking/checkpoints").rglob("*.json"))
            )
            with self.assertRaisesRegex(ValueError, "payload contract"):
                run_workflow_request(
                    workspace, request_path, source_root=ROOT, apply=True
                )
            self.assertEqual(
                len(
                    tuple((workspace / "projects_tracking/checkpoints").rglob("*.json"))
                ),
                checkpoint_count,
            )
            missing_effect = {
                **request,
                "idempotency_key": "health_alpha_effect",
                "approved_effects": [],
            }
            request_path.write_text(
                json.dumps(missing_effect, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "effects are not fully approved"):
                run_workflow_request(
                    workspace, request_path, source_root=ROOT, apply=True
                )
            denial_events = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (workspace / "projects_tracking/events").glob("*.json")
            ]
            self.assertTrue(
                any(item["kind"] == "workflow-policy-denied" for item in denial_events)
            )

    def test_workflow_paths_reject_parent_traversal_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            request_path = temp / "traversal.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "workflow_id": "continuous_improvement",
                        "project_id": "prj_alpha",
                        "session_id": "session_operator",
                        "idempotency_key": "traversal_denied_001",
                        "approved_effects": ["read_local"],
                        "payload": {"sources": ["../beta/README.md"]},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "parent traversal"):
                run_workflow_request(
                    workspace, request_path, source_root=ROOT, apply=True
                )

    def test_pending_workspace_intent_is_detected_and_explicitly_reconciled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            events = workspace / "projects_tracking/events"
            from runtime.project_control_plane import append_event

            append_event(
                events,
                "workspace-operation-intent",
                {
                    "operation_id": "interrupted-fixture",
                    "operation": "activate",
                    "project_id": "prj_alpha",
                    "session_id": "session_operator",
                },
            )
            status = workspace_status(workspace, source_root=ROOT)
            self.assertFalse(status["valid"])
            self.assertEqual(status["pending_operation_ids"], ["interrupted-fixture"])
            rebuilt = rebuild_workspace_projections(workspace, apply=True)
            self.assertIn("interrupted-fixture", rebuilt["pending_operation_ids"])
            self.assertTrue(workspace_status(workspace, source_root=ROOT)["valid"])

    def test_shared_capability_promotion_is_evidence_gated_and_not_auto_activated(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            workspace = self._workspace_with_projects(temp)
            activate_project(workspace, "prj_alpha")
            candidate = (
                workspace
                / "projects/alpha/.engineering-bootstrap/staging/candidate-tool.py"
            )
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text("def check():\n    return True\n", encoding="utf-8")
            request_path = temp / "promote.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "workflow_id": "shared_capability_promote",
                        "project_id": "prj_alpha",
                        "session_id": "session_operator",
                        "idempotency_key": "promote_candidate_001",
                        "approved_effects": ["read_local", "write_workspace"],
                        "payload": {
                            "candidate": ".engineering-bootstrap/staging/candidate-tool.py",
                            "expected_source_sha256": hashlib.sha256(
                                candidate.read_bytes()
                            ).hexdigest(),
                            "evidence": {
                                "capability_id": "candidate-tool",
                                "version": "1.0.0",
                                "provenance": ["projects/alpha/candidate-tool.py"],
                                "license": "internal-reference",
                                "tests": ["unit"],
                                "benchmark": ["golden"],
                                "approval_id": "approval-001",
                                "tests_passed": True,
                                "benchmark_passed": True,
                            },
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_workflow_request(
                workspace, request_path, source_root=ROOT, apply=True
            )
            release = result["receipt"]["result"]["outputs"][
                "shared_capability_release"
            ]
            self.assertEqual(release["decision"], "released")
            self.assertFalse(release["automatic_activation"])
            target = Path(release["target"])
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), candidate.read_bytes())

    def test_extended_session_file_without_renewal_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            session = workspace / "projects_tracking/sessions/session_operator.json"
            value = json.loads(session.read_text())
            value["expires_utc"] = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat()
            session.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "projection differs"):
                current_project(workspace)

    def test_expired_lease_fails_closed_for_current_status_browse_and_renewal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")

            class FutureClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    value = datetime.now(timezone.utc) + timedelta(hours=2)
                    return value if tz is not None else value.replace(tzinfo=None)

            with patch.object(workspace_runtime, "datetime", FutureClock):
                current = current_project(workspace)
                self.assertIsNone(current["active"])
                self.assertEqual(current["lease_state"], "expired")
                self.assertIsNotNone(current["expired"])
                self.assertEqual(
                    browse_canonical_memory(workspace, "project memory")["records"],
                    [],
                )
                status = workspace_status(workspace, source_root=ROOT)
                self.assertFalse(status["valid"])
                self.assertEqual(status["active_session_count"], 0)
                self.assertEqual(status["expired_session_ids"], ["session_operator"])
                with self.assertRaisesRegex(ValueError, "lease expired"):
                    renew_project(workspace, minutes=5)

    def test_activation_reacquires_an_expired_same_project_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            first = activate_project(workspace, "prj_alpha")

            class FutureClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    value = datetime.now(timezone.utc) + timedelta(hours=2)
                    return value if tz is not None else value.replace(tzinfo=None)

            with patch.object(workspace_runtime, "datetime", FutureClock):
                second = activate_project(workspace, "prj_alpha")
                self.assertTrue(second["activated"])
                self.assertNotEqual(
                    first["session"]["scope"]["lease_id"],
                    second["session"]["scope"]["lease_id"],
                )
                self.assertEqual(current_project(workspace)["lease_state"], "current")
            events = validate_event_ledger(
                workspace / "projects_tracking/events"
            )["events"]
            self.assertIn("session-expired", [item["kind"] for item in events])

    def test_released_session_cannot_be_reactivated_by_projection_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            release_project(workspace, context_reset_confirmed=True)
            session = workspace / "projects_tracking/sessions/session_operator.json"
            value = json.loads(session.read_text())
            value["status"] = "active"
            session.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "projection differs"):
                current_project(workspace)

    def test_session_permission_expansion_requires_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            session = workspace / "projects_tracking/sessions/session_operator.json"
            value = json.loads(session.read_text())
            value["writable_roots"].append("projects/beta")
            session.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "projection differs"):
                current_project(workspace)

    def test_session_renewal_preserves_creation_identity_across_heartbeats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            session = workspace / "projects_tracking/sessions/session_operator.json"
            created = json.loads(session.read_text(encoding="utf-8"))["created_utc"]
            first = renew_project(workspace, minutes=1440)
            second = renew_project(workspace, minutes=1440)
            active = json.loads(session.read_text(encoding="utf-8"))
            self.assertEqual(active["created_utc"], created)
            self.assertEqual(active["expires_utc"], second["expires_utc"])
            self.assertGreaterEqual(
                datetime.fromisoformat(str(second["expires_utc"])),
                datetime.fromisoformat(str(first["expires_utc"])),
            )

    def test_session_projection_rebuild_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            renew_project(workspace, minutes=10)
            first = rebuild_workspace_projections(workspace)
            second = rebuild_workspace_projections(workspace)
            self.assertEqual(first["registry_sha256"], second["registry_sha256"])
            self.assertEqual(first["active_project_ids"], second["active_project_ids"])

    def test_workspace_mutation_loads_config_inside_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            original = workspace_runtime._load_config
            observed = {"locked": False}

            def checked(paths):
                try:
                    with FileLock(
                        paths.tracking / ".workspace-control.lock", timeout_seconds=0.02
                    ):
                        pass
                except FileLockTimeout:
                    observed["locked"] = True
                return original(paths)

            with patch.object(workspace_runtime, "_load_config", side_effect=checked):
                renew_project(workspace, minutes=5)
            self.assertTrue(observed["locked"])

    def test_config_change_during_mutation_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            original = workspace_runtime._snapshot_and_replace
            changed = {"done": False}

            def mutate(paths, path, value):
                result = original(paths, path, value)
                if not changed["done"]:
                    config = workspace / "engineering-workspace.toml"
                    config.write_text(
                        config.read_text() + "\n# concurrent drift\n", encoding="utf-8"
                    )
                    changed["done"] = True
                return result

            with patch.object(
                workspace_runtime, "_snapshot_and_replace", side_effect=mutate
            ):
                with self.assertRaisesRegex(
                    ValueError, "configuration changed during mutation"
                ):
                    renew_project(workspace, minutes=5)

    def test_event_records_configuration_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha")
            expected = hashlib.sha256(
                (workspace / "engineering-workspace.toml").read_bytes()
            ).hexdigest()
            events = [
                json.loads(path.read_text())
                for path in (workspace / "projects_tracking/events").glob("*.json")
            ]
            self.assertTrue(events)
            self.assertTrue(
                all(
                    event["payload"].get("workspace_config_sha256") == expected
                    for event in events
                )
            )

    def test_read_only_config_snapshot_detects_mid_read_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            config = workspace / "engineering-workspace.toml"
            original = Path.read_bytes
            calls = {"count": 0}

            def changing(path):
                data = original(path)
                if path.resolve() == config.resolve():
                    calls["count"] += 1
                    if calls["count"] > 1:
                        return data + b"\n# drift"
                return data

            with patch.object(Path, "read_bytes", changing):
                with self.assertRaisesRegex(ValueError, "changed during verified read"):
                    current_project(workspace)

    def test_projection_rebuild_interruption_preserves_current_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            registry = workspace / "projects_tracking/project-registry.json"
            before = registry.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "injected"):
                rebuild_workspace_projections(
                    workspace,
                    apply=True,
                    fault_injector=lambda stage: (_ for _ in ()).throw(
                        RuntimeError("injected")
                    )
                    if stage == "after_registry_switch"
                    else None,
                )
            self.assertEqual(registry.read_bytes(), before)

    def test_projection_rebuild_resumes_from_matching_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            with self.assertRaises(RuntimeError):
                rebuild_workspace_projections(
                    workspace,
                    apply=True,
                    fault_injector=lambda stage: (_ for _ in ()).throw(
                        RuntimeError("stop")
                    )
                    if stage == "after_registry_switch"
                    else None,
                )
            resumed = rebuild_workspace_projections(workspace, apply=True)
            self.assertTrue(resumed["applied"])
            self.assertTrue(
                (Path(resumed["transaction"]) / "0002-committed.json").is_file()
            )

    def test_projection_rebuild_rejects_stale_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            events = workspace / "projects_tracking/events"
            head = validate_event_ledger(events)["head_sha256"]
            checkpoint = (
                workspace
                / "projects_tracking/rebuild-transactions"
                / head
                / "0001-prepared.json"
            )
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(
                json.dumps({"source_event_head": "0" * 64}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "different event head"):
                rebuild_workspace_projections(workspace, apply=True)

    def test_projection_rebuild_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            first = rebuild_workspace_projections(workspace)
            second = rebuild_workspace_projections(workspace)
            self.assertEqual(first["registry_sha256"], second["registry_sha256"])

    def test_projection_switch_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace_with_projects(Path(directory))
            activate_project(workspace, "prj_alpha", session_id="session_alpha")
            activate_project(workspace, "prj_beta", session_id="session_beta")
            tracked = [
                workspace / "projects_tracking/project-registry.json",
                workspace / "projects_tracking/project-registry.sha256",
                *(workspace / "projects_tracking/sessions").glob("*.json"),
            ]
            before = {path: path.read_bytes() for path in tracked}
            with self.assertRaises(RuntimeError):
                rebuild_workspace_projections(
                    workspace,
                    apply=True,
                    fault_injector=lambda stage: (_ for _ in ()).throw(
                        RuntimeError("stop")
                    )
                    if stage == "after_session_switch_1"
                    else None,
                )
            self.assertTrue(
                all(path.read_bytes() == content for path, content in before.items())
            )


if __name__ == "__main__":
    unittest.main()
