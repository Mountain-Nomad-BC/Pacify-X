from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from runtime.project_control_plane import (
    append_event,
    dispatch_workstreams,
    evaluate_resilience,
    guarded_change,
    import_transfer,
    project_health,
    promote_capability,
    quarantine_candidates,
    record_project_transition,
    register_agent,
    register_existing_project,
    recover_incident,
    switch_project,
)
from runtime.project_stream_controls import ScopeEnvelope, SwitchEvidence, TransferPackage


def scope(project: str) -> ScopeEnvelope:
    return ScopeEnvelope("workspace", project, "agent", "session", "stream", f"lease-{project}", "intent", "correlation")


class ProjectControlPlaneTests(unittest.TestCase):
    def test_concurrent_event_appends_keep_a_contiguous_unique_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger"
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = tuple(pool.map(lambda value: append_event(ledger, "concurrent", {"value": value}), range(12)))
            self.assertEqual(len(set(paths)), 12)
            records = [__import__("json").loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
            self.assertEqual(sorted(item["sequence"] for item in records), list(range(1, 13)))

    def test_project_agent_health_and_dispatch_are_evidence_driven(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (project / "test_demo.py").write_text("def test_demo(): pass\n", encoding="utf-8")
            registered = register_existing_project(project, root / "ledger", project_id="prj_project")
            self.assertEqual(registered["state"], "registered")
            agent = register_agent(root / "ledger", {
                "agent_id": "agent", "template_id": "template", "project_id": "project",
                "permissions": ["read"], "tests": {"identity": True, "sandbox": True},
                "sandbox_validated": True, "evidence": ["test-run"],
            })
            self.assertEqual(agent["decision"], "active")
            health = project_health({name: 1 for name in ("tests", "security", "evidence", "dependencies", "memory", "operations")})
            self.assertTrue(health["certifying"])
            dispatched = dispatch_workstreams([
                {"work_id": "one", "worker_id": "a", "lane": "light", "owned_paths": ["src/a"]},
                {"work_id": "two", "worker_id": "b", "lane": "light", "owned_paths": ["src/a/file"]},
            ], {"agents": 0})
            self.assertEqual(len(dispatched["assignments"]), 1)
            self.assertEqual(len(dispatched["blocked"]), 1)

    def test_switch_transition_transfer_and_promotion_append_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger"
            evidence = SwitchEvidence(True, True, True, True, True, True, True, True)
            switched = switch_project(ledger, scope("old"), scope("new"), evidence)
            self.assertEqual(switched["decision"], "active")
            transition = record_project_transition(ledger, project_id="new", action="pause", evidence=["checkpoint"])
            self.assertEqual(transition["decision"], "accepted")

            source = root / "source" / "capability.txt"
            source.parent.mkdir()
            source.write_text("bounded capability", encoding="utf-8")
            package = TransferPackage(
                "transfer-one", "old", "new", "sanitized_capability", ("source-ref",),
                "internal-reference", (), ("test-pass",), True, True, True,
            )
            imported = import_transfer(root, source, root / "destination" / "capability.txt", package, ledger)
            self.assertEqual(imported["decision"], "imported")

            candidate = root / "candidate.json"
            candidate.write_text("{}\n", encoding="utf-8")
            promoted = promote_capability(candidate, root / "shared", ledger, {
                "capability_id": "candidate", "version": "1.0.0", "provenance": ["source-ref"],
                "license": "internal-reference", "tests": ["unit"], "benchmark": ["golden"],
                "approval_id": "approval", "tests_passed": True, "benchmark_passed": True,
            })
            self.assertEqual(promoted["decision"], "released")
            self.assertFalse(promoted["automatic_activation"])

    def test_cleanup_moves_exact_files_to_sibling_quarantine_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            candidate = active / "cache.bin"
            candidate.write_bytes(b"recoverable")
            result = quarantine_candidates(active, [candidate], workspace / "quarantine" / "operation", workspace / "ledger")
            self.assertEqual(result["decision"], "quarantined")
            self.assertFalse(result["hard_delete"])
            self.assertFalse(candidate.exists())
            self.assertEqual((workspace / "quarantine" / "operation" / "cache.bin").read_bytes(), b"recoverable")

    def test_guarded_change_and_incident_recovery_preserve_every_prior_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            staged = workspace / "staged.py"
            staged.write_text("value = 2\n", encoding="utf-8")
            evidence = {
                "intent": "bounded fix", "tests": ["unit"], "outcome_contract": "value updated",
                "rollback": "restore quarantine", "approval_id": "approval", "idempotency_key": "change-one",
                "tests_passed": True, "outcome_passed": True,
            }
            changed = guarded_change(
                active, staged, active / "app.py", workspace / "quarantine" / "rejected-change",
                workspace / "ledger", evidence,
            )
            self.assertEqual(changed["decision"], "accepted")
            self.assertTrue(staged.exists())

            recovery = workspace / "recovery.py"
            recovery.write_text("value = 1\n", encoding="utf-8")
            recovered = recover_incident(
                active, recovery, active / "app.py", workspace / "quarantine" / "incident-one",
                workspace / "ledger", {
                    "incident_id": "incident-one", "root_cause": "regression", "recovery_tests": ["unit"],
                    "rollback_rehearsal": "verified", "approval_id": "approval", "recovery_tests_passed": True,
                    "rollback_rehearsed": True,
                },
            )
            self.assertEqual(recovered["decision"], "recovered")
            self.assertEqual((active / "app.py").read_text(encoding="utf-8"), "value = 1\n")
            self.assertEqual((workspace / "quarantine" / "incident-one" / "app.py").read_text(encoding="utf-8"), "value = 2\n")

    def test_resilience_is_digital_twin_only_and_evidence_bounded(self) -> None:
        report = evaluate_resilience([{
            "experiment_id": "dependency-down", "fault": "dependency_failure", "digital_twin": True,
            "approved": True, "baseline_evidence": "baseline", "observed_evidence": "trace",
            "rollback_verified": True, "outcome_met": True,
        }])
        self.assertTrue(report["passed"])
        self.assertFalse(report["live_fault_injection"])


if __name__ == "__main__":
    unittest.main()
