from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from runtime.knowledge_foundry import SourceArtifact
from runtime.memory_vault import MemoryVault
from runtime.project_stream_orchestrator import (
    ProjectStreamContext,
    execute_project_stream,
    validate_checkpoint_resume,
    workspace_bootstrap,
)


ROOT = Path(__file__).parents[1]
PREFLIGHT = {
    name: True
    for name in (
        "constitution_resolved",
        "lease_valid",
        "scope_resolved",
        "side_effect_budget_set",
    )
}


def source() -> SourceArtifact:
    text = "# Memory rule\n- Preserve evidence and validate current memory."
    return SourceArtifact(
        "source",
        "engineering_note",
        "source.md",
        hashlib.sha256(text.encode()).hexdigest(),
        text,
        "internal-reference",
    )


def context(
    workflow_id: str,
    payload: dict,
    *,
    effects=("read_local",),
    approval=False,
    lease_expires_utc=None,
    timeout_seconds=120,
) -> ProjectStreamContext:
    return ProjectStreamContext(
        workflow_id,
        "wsp_test",
        "prj_test",
        "agent",
        "session",
        "intent",
        f"corr-{workflow_id}",
        PREFLIGHT,
        effects,
        approval,
        payload,
        lease_expires_utc,
        timeout_seconds,
    )


class ProjectStreamOrchestratorTests(unittest.TestCase):
    def test_every_workflow_has_exactly_one_honest_runtime_state(self) -> None:
        source_registry = json.loads(
            (ROOT / "registry/project_stream_orchestrations.json").read_text(
                encoding="utf-8"
            )
        )
        handlers = json.loads(
            (ROOT / "registry/project_stream_handlers.json").read_text(encoding="utf-8")
        )
        source_ids = {
            item["orchestration_id"] for item in source_registry["orchestrations"]
        }
        handler_ids = {item["orchestration_id"] for item in handlers["workflows"]}
        self.assertEqual(source_ids, handler_ids)
        self.assertEqual(handlers["executable_count"], 17)
        self.assertEqual(handlers["plan_only_count"], 0)
        self.assertEqual(
            sum(item["status"] == "executable" for item in handlers["workflows"]), 17
        )

    def test_memory_ingest_and_maintenance_execute_with_approval_and_append_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            vault = MemoryVault(
                temp / "vault", workspace_id="wsp_test", project_id="prj_test"
            )
            checkpoints = temp / "checkpoints"
            ingest = execute_project_stream(
                ROOT,
                context(
                    "memory_ingest_distill",
                    {"vault": vault, "sources": (source(),)},
                    effects=("read_local", "write_workspace"),
                    approval=True,
                ),
                checkpoint_root=checkpoints,
            )
            self.assertEqual(ingest.status, "completed")
            self.assertGreater(ingest.outputs["memory_notes_updated"], 0)
            maintenance = execute_project_stream(
                ROOT,
                context(
                    "memory_maintenance",
                    {"vault": vault},
                    effects=("read_local", "write_workspace"),
                    approval=True,
                ),
                checkpoint_root=checkpoints,
            )
            self.assertEqual(maintenance.status, "completed")
            self.assertEqual(
                maintenance.outputs["memory_health_report"], "index_published"
            )

    def test_malformed_workflow_and_missing_approval_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            malformed = execute_project_stream(
                ROOT, context("chaos_resilience_cycle", {}), checkpoint_root=temp
            )
            self.assertEqual(malformed.status, "failed")
            vault = MemoryVault(
                temp / "vault", workspace_id="wsp_test", project_id="prj_test"
            )
            denied = execute_project_stream(
                ROOT,
                context(
                    "memory_ingest_distill",
                    {"vault": vault, "sources": (source(),)},
                    effects=("read_local", "write_workspace"),
                ),
                checkpoint_root=temp,
            )
            self.assertEqual(denied.status, "blocked")
            self.assertIn("explicit_approval_missing", denied.reasons)

    def test_continuous_improvement_returns_candidates_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = execute_project_stream(
                ROOT,
                context("continuous_improvement", {"sources": (source(),)}),
                checkpoint_root=Path(directory),
            )
            self.assertEqual(result.status, "completed")
            self.assertFalse(result.outputs["automatic_activation"])
            self.assertTrue(result.outputs["candidate_skill_ids"])

    def test_expired_lease_and_elapsed_timeout_fail_closed_at_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expired = context(
                "continuous_improvement",
                {"sources": (source(),)},
                lease_expires_utc=(
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(),
            )
            blocked = execute_project_stream(ROOT, expired, checkpoint_root=root)
            self.assertEqual(blocked.status, "blocked")
            self.assertIn("project_lease_expired", blocked.reasons)

            short = context(
                "continuous_improvement", {"sources": (source(),)}, timeout_seconds=1
            )
            result = execute_project_stream(
                ROOT,
                short,
                checkpoint_root=root,
                handlers={
                    "continuous_improvement": lambda _: (
                        time.sleep(1.02)
                        or {
                            "candidate_skill_ids": (),
                            "recommendations": (),
                            "automatic_activation": False,
                        }
                    )
                },
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("workflow_timeout_exceeded", result.reasons)

    def test_workspace_layout_and_checkpoint_resume_are_explicit_and_drift_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project = workspace / "projects" / "demo"
            bootstrap_context = context(
                "workspace_bootstrap",
                {
                    "project": project,
                    "workspace_root": workspace,
                    "source_root": ROOT,
                },
                effects=("read_local", "write_workspace"),
                approval=True,
            )
            output = workspace_bootstrap(bootstrap_context)["workspace_ready"]
            self.assertTrue(output["applied"])
            for name in (
                "projects",
                "projects_tracking",
                "repo_quarantine",
                "shared_capabilities",
            ):
                self.assertTrue((workspace / name).is_dir())

            repository = {
                "root": project.as_posix(),
                "branch": "main",
                "commit": "abc",
                "working_tree_sha256": "def",
            }
            run_context = context(
                "continuous_improvement",
                {
                    "sources": (source(),),
                    "repository_state": repository,
                    "next_safe_action": "resume improvement",
                },
            )
            result = execute_project_stream(
                ROOT, run_context, checkpoint_root=workspace / "checkpoints"
            )
            checkpoint = Path(result.checkpoints[0])
            self.assertTrue(
                validate_checkpoint_resume(checkpoint, run_context, repository)["valid"]
            )
            drifted = {**repository, "commit": "changed"}
            self.assertEqual(
                validate_checkpoint_resume(checkpoint, run_context, drifted)["status"],
                "stale",
            )


if __name__ == "__main__":
    unittest.main()
