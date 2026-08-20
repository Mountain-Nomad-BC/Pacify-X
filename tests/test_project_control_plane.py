from __future__ import annotations

from pathlib import Path
import hashlib
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
    validate_agent_specification,
    register_existing_project,
    recover_incident,
    switch_project,
)
from runtime.project_stream_controls import (
    ScopeEnvelope,
    SwitchEvidence,
    TransferPackage,
)


def scope(project: str) -> ScopeEnvelope:
    return ScopeEnvelope(
        "workspace",
        project,
        "agent",
        "session",
        "stream",
        f"lease-{project}",
        "intent",
        "correlation",
    )


class ProjectControlPlaneTests(unittest.TestCase):
    def test_concurrent_event_appends_keep_a_contiguous_unique_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger"
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = tuple(
                    pool.map(
                        lambda value: append_event(
                            ledger, "concurrent", {"value": value}
                        ),
                        range(12),
                    )
                )
            self.assertEqual(len(set(paths)), 12)
            records = [
                __import__("json").loads(path.read_text(encoding="utf-8"))
                for path in sorted(paths)
            ]
            self.assertEqual(
                sorted(item["sequence"] for item in records), list(range(1, 13))
            )

    def test_project_agent_health_and_dispatch_are_evidence_driven(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text(
                "[project]\nname='demo'\n", encoding="utf-8"
            )
            (project / "test_demo.py").write_text(
                "def test_demo(): pass\n", encoding="utf-8"
            )
            registered = register_existing_project(
                project, root / "ledger", project_id="prj_project"
            )
            self.assertEqual(registered["state"], "registered")
            agent = validate_agent_specification(
                root / "ledger",
                {
                    "agent_id": "agent",
                    "template_id": "template",
                    "project_id": "project",
                    "permissions": ["read"],
                    "tests": {"identity": True, "sandbox": True},
                    "sandbox_validated": True,
                    "evidence": ["test-run"],
                },
            )
            self.assertEqual(agent["decision"], "validated_candidate")
            self.assertEqual(agent["admission_state"], "unadmitted")
            self.assertEqual(agent["runtime_state"], "stopped")
            self.assertEqual(agent["authority_state"], "none")
            self.assertFalse(agent["assertions_trusted"])
            health = project_health(
                {
                    name: 1
                    for name in (
                        "tests",
                        "security",
                        "evidence",
                        "dependencies",
                        "memory",
                        "operations",
                    )
                }
            )
            self.assertTrue(health["certifying"])
            dispatched = dispatch_workstreams(
                [
                    {
                        "work_id": "one",
                        "worker_id": "a",
                        "lane": "light",
                        "owned_paths": ["src/a"],
                    },
                    {
                        "work_id": "two",
                        "worker_id": "b",
                        "lane": "light",
                        "owned_paths": ["src/a/file"],
                    },
                ],
                {"agents": 0},
            )
            self.assertEqual(len(dispatched["assignments"]), 1)
            self.assertEqual(len(dispatched["blocked"]), 1)

    def test_switch_transition_transfer_and_promotion_append_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger"
            evidence = SwitchEvidence(True, True, True, True, True, True, True, True)
            switched = switch_project(ledger, scope("old"), scope("new"), evidence)
            self.assertEqual(switched["decision"], "active")
            transition = record_project_transition(
                ledger, project_id="new", action="pause", evidence=["checkpoint"]
            )
            self.assertEqual(transition["decision"], "accepted")

            source = root / "source" / "capability.txt"
            source.parent.mkdir()
            source.write_text("bounded capability", encoding="utf-8")
            package = TransferPackage(
                "transfer-one",
                "old",
                "new",
                "sanitized_capability",
                ("source-ref",),
                "internal-reference",
                (),
                ("test-pass",),
                True,
                True,
                True,
            )
            imported = import_transfer(
                root, source, root / "destination" / "capability.txt", package, ledger
            )
            self.assertEqual(imported["decision"], "imported")

            staging = root / "staging"
            staging.mkdir()
            candidate = staging / "candidate.json"
            candidate.write_text("{}\n", encoding="utf-8")
            promoted = promote_capability(
                candidate,
                root / "shared",
                ledger,
                {
                    "capability_id": "candidate",
                    "version": "1.0.0",
                    "provenance": ["source-ref"],
                    "license": "internal-reference",
                    "tests": ["unit"],
                    "benchmark": ["golden"],
                    "approval_id": "approval",
                    "tests_passed": True,
                    "benchmark_passed": True,
                },
                staging_root=staging,
                expected_source_sha256=hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(promoted["decision"], "released")
            self.assertFalse(promoted["automatic_activation"])

    def test_cleanup_moves_exact_files_to_sibling_quarantine_without_deletion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            candidate = active / "cache.bin"
            candidate.write_bytes(b"recoverable")
            result = quarantine_candidates(
                active,
                [candidate],
                workspace / "quarantine" / "operation",
                workspace / "ledger",
            )
            self.assertEqual(result["decision"], "quarantined")
            self.assertFalse(result["hard_delete"])
            self.assertFalse(candidate.exists())
            self.assertEqual(
                (workspace / "quarantine" / "operation" / "cache.bin").read_bytes(),
                b"recoverable",
            )

    def test_guarded_change_and_incident_recovery_preserve_every_prior_artifact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            staging = workspace / "staging"
            staging.mkdir()
            staged = staging / "staged.py"
            staged.write_text("value = 2\n", encoding="utf-8")
            evidence = {
                "intent": "bounded fix",
                "tests": ["unit"],
                "outcome_contract": "value updated",
                "rollback": "restore quarantine",
                "approval_id": "approval",
                "idempotency_key": "change-one",
                "tests_passed": True,
                "outcome_passed": True,
            }
            changed = guarded_change(
                active,
                staged,
                active / "app.py",
                workspace / "quarantine" / "rejected-change",
                workspace / "ledger",
                evidence,
                staging_root=staging,
                expected_source_sha256=hashlib.sha256(staged.read_bytes()).hexdigest(),
            )
            self.assertEqual(changed["decision"], "accepted")
            self.assertTrue(staged.exists())

            recovery = staging / "recovery.py"
            recovery.write_text("value = 1\n", encoding="utf-8")
            recovered = recover_incident(
                active,
                recovery,
                active / "app.py",
                workspace / "quarantine" / "incident-one",
                workspace / "ledger",
                {
                    "incident_id": "incident-one",
                    "root_cause": "regression",
                    "recovery_tests": ["unit"],
                    "rollback_rehearsal": "verified",
                    "approval_id": "approval",
                    "recovery_tests_passed": True,
                    "rollback_rehearsed": True,
                },
                staging_root=staging,
                transaction_root=workspace / "transactions",
                expected_source_sha256=hashlib.sha256(
                    recovery.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(recovered["decision"], "recovered")
            self.assertEqual(
                (active / "app.py").read_text(encoding="utf-8"), "value = 1\n"
            )
            self.assertEqual(
                (workspace / "quarantine" / "incident-one" / "app.py").read_text(
                    encoding="utf-8"
                ),
                "value = 2\n",
            )

    def test_resilience_is_digital_twin_only_and_evidence_bounded(self) -> None:
        report = evaluate_resilience(
            [
                {
                    "experiment_id": "dependency-down",
                    "fault": "dependency_failure",
                    "digital_twin": True,
                    "approved": True,
                    "baseline_evidence": "baseline",
                    "observed_evidence": "trace",
                    "rollback_verified": True,
                    "outcome_met": True,
                }
            ]
        )
        self.assertTrue(report["passed"])
        self.assertFalse(report["live_fault_injection"])

    def test_guarded_change_rejects_source_outside_staging_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            staging = workspace / "staging"
            staging.mkdir()
            external = workspace / "external.py"
            external.write_text("value = 1\n", encoding="utf-8")
            result = guarded_change(
                active,
                external,
                active / "app.py",
                workspace / "quarantine",
                workspace / "ledger",
                {
                    "intent": "x",
                    "tests": ["x"],
                    "outcome_contract": "x",
                    "rollback": "x",
                    "approval_id": "x",
                    "idempotency_key": "x",
                    "tests_passed": True,
                    "outcome_passed": True,
                },
                staging_root=staging,
                expected_source_sha256=hashlib.sha256(
                    external.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(result["decision"], "rejected")
            self.assertIn("source_outside_owned_staging_root", result["reasons"])

    def test_guarded_change_cannot_move_external_file_on_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            staging = workspace / "staging"
            staging.mkdir()
            external = workspace / "external.py"
            external.write_text("untouched\n", encoding="utf-8")
            before = external.read_bytes()
            guarded_change(
                active,
                external,
                active / "app.py",
                workspace / "quarantine",
                workspace / "ledger",
                {},
                staging_root=staging,
                expected_source_sha256=hashlib.sha256(before).hexdigest(),
            )
            self.assertEqual(external.read_bytes(), before)
            self.assertFalse((workspace / "quarantine").exists())

    def test_recovery_rejects_unapproved_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            active = workspace / "active"
            active.mkdir()
            staging = workspace / "staging"
            staging.mkdir()
            candidate = workspace / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            result = recover_incident(
                active,
                candidate,
                active / "app.py",
                workspace / "quarantine",
                workspace / "ledger",
                {
                    "incident_id": "i",
                    "root_cause": "x",
                    "recovery_tests": ["x"],
                    "rollback_rehearsal": "x",
                    "approval_id": "x",
                    "recovery_tests_passed": True,
                    "rollback_rehearsed": True,
                },
                staging_root=staging,
                transaction_root=workspace / "transactions",
                expected_source_sha256=hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(result["decision"], "escalated")
            self.assertIn("source_outside_owned_staging_root", result["reasons"])

    def test_capability_promotion_requires_owned_staging_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            staging.mkdir()
            candidate = root / "candidate.json"
            candidate.write_text("{}\n", encoding="utf-8")
            result = promote_capability(
                candidate,
                root / "shared",
                root / "ledger",
                {},
                staging_root=staging,
                expected_source_sha256=hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(result["decision"], "rejected")
            self.assertIn("source_outside_owned_staging_root", result["reasons"])

    def test_source_digest_change_before_commit_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            candidate = staging / "candidate.py"
            candidate.write_text("new\n", encoding="utf-8")
            result = guarded_change(
                active,
                candidate,
                active / "app.py",
                root / "quarantine",
                root / "ledger",
                {},
                staging_root=staging,
                expected_source_sha256="0" * 64,
            )
            self.assertEqual(result["decision"], "rejected")
            self.assertIn("source_digest_mismatch", result["reasons"])

    def test_recovery_copy_failure_restores_previous_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            destination = active / "app.py"
            destination.write_text("original\n", encoding="utf-8")
            candidate = staging / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            evidence = {
                "incident_id": "i",
                "root_cause": "x",
                "recovery_tests": ["x"],
                "rollback_rehearsal": "x",
                "approval_id": "x",
                "recovery_tests_passed": True,
                "rollback_rehearsed": True,
            }

            def fail(stage: str) -> None:
                if stage == "after_preserve":
                    raise RuntimeError("injected")

            with self.assertRaisesRegex(RuntimeError, "injected"):
                recover_incident(
                    active,
                    candidate,
                    destination,
                    root / "quarantine",
                    root / "ledger",
                    evidence,
                    staging_root=staging,
                    transaction_root=root / "transactions",
                    expected_source_sha256=hashlib.sha256(
                        candidate.read_bytes()
                    ).hexdigest(),
                    fault_injector=fail,
                )
            self.assertEqual(destination.read_text(encoding="utf-8"), "original\n")

    def test_recovery_hash_failure_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            destination = active / "app.py"
            destination.write_text("original\n", encoding="utf-8")
            candidate = staging / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            result = recover_incident(
                active,
                candidate,
                destination,
                root / "quarantine",
                root / "ledger",
                {},
                staging_root=staging,
                transaction_root=root / "transactions",
                expected_source_sha256="0" * 64,
            )
            self.assertEqual(result["decision"], "escalated")
            self.assertEqual(destination.read_text(encoding="utf-8"), "original\n")

    def test_quarantine_batch_failure_rolls_back_prior_moves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            first = active / "a.txt"
            second = active / "b.txt"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")

            def fail(stage: str) -> None:
                if stage == "before_move_2":
                    raise RuntimeError("injected")

            with self.assertRaisesRegex(RuntimeError, "injected"):
                quarantine_candidates(
                    active,
                    [first, second],
                    root / "quarantine",
                    root / "ledger",
                    transaction_root=root / "transactions",
                    fault_injector=fail,
                )
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

    def test_quarantine_rejects_overlapping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            child = active / "dir"
            child.mkdir(parents=True)
            item = child / "a.txt"
            item.write_text("a", encoding="utf-8")
            result = quarantine_candidates(
                active,
                [child, item],
                root / "quarantine",
                root / "ledger",
                transaction_root=root / "transactions",
            )
            self.assertEqual(result["decision"], "rejected")
            self.assertTrue(
                any(
                    reason.startswith("overlapping_candidate")
                    for reason in result["reasons"]
                )
            )

    def test_recovery_interruption_replays_or_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            destination = active / "app.py"
            destination.write_text("original\n", encoding="utf-8")
            candidate = staging / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            evidence = {
                "incident_id": "i",
                "root_cause": "x",
                "recovery_tests": ["x"],
                "rollback_rehearsal": "x",
                "approval_id": "x",
                "recovery_tests_passed": True,
                "rollback_rehearsed": True,
            }
            with self.assertRaises(RuntimeError):
                recover_incident(
                    active,
                    candidate,
                    destination,
                    root / "quarantine",
                    root / "ledger",
                    evidence,
                    staging_root=staging,
                    transaction_root=root / "transactions",
                    expected_source_sha256=digest,
                    fault_injector=lambda stage: (_ for _ in ()).throw(
                        RuntimeError("stop")
                    )
                    if stage == "after_preserve"
                    else None,
                )
            replay = recover_incident(
                active,
                candidate,
                destination,
                root / "quarantine",
                root / "ledger",
                evidence,
                staging_root=staging,
                transaction_root=root / "transactions",
                expected_source_sha256=digest,
            )
            self.assertEqual(replay["decision"], "escalated")
            self.assertEqual(destination.read_text(encoding="utf-8"), "original\n")

    def test_recovery_commit_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            candidate = staging / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            evidence = {
                "incident_id": "i",
                "root_cause": "x",
                "recovery_tests": ["x"],
                "rollback_rehearsal": "x",
                "approval_id": "x",
                "recovery_tests_passed": True,
                "rollback_rehearsed": True,
            }
            first = recover_incident(
                active,
                candidate,
                active / "app.py",
                root / "quarantine",
                root / "ledger",
                evidence,
                staging_root=staging,
                transaction_root=root / "transactions",
                expected_source_sha256=digest,
            )
            second = recover_incident(
                active,
                candidate,
                active / "app.py",
                root / "quarantine",
                root / "ledger",
                evidence,
                staging_root=staging,
                transaction_root=root / "transactions",
                expected_source_sha256=digest,
            )
            self.assertEqual(first["transaction_id"], second["transaction_id"])
            self.assertTrue(second["idempotent_replay"])

    def test_recovery_journal_cannot_escape_transaction_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            staging = root / "staging"
            staging.mkdir()
            candidate = staging / "candidate.py"
            candidate.write_text("replacement\n", encoding="utf-8")
            result = recover_incident(
                active,
                candidate,
                active / "app.py",
                root / "quarantine",
                root / "ledger",
                {},
                staging_root=staging,
                transaction_root=root.parent / "outside",
                expected_source_sha256=hashlib.sha256(
                    candidate.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(result["decision"], "escalated")
            self.assertIn(
                "transaction_root_must_be_sibling_bounded_tree", result["reasons"]
            )

    def test_quarantine_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            item = active / "a.txt"
            item.write_text("a", encoding="utf-8")
            first = quarantine_candidates(
                active,
                [item],
                root / "quarantine",
                root / "ledger",
                transaction_root=root / "transactions",
            )
            second = quarantine_candidates(
                active,
                [item],
                root / "quarantine",
                root / "ledger",
                transaction_root=root / "transactions",
            )
            self.assertEqual(first["decision"], "quarantined")
            self.assertTrue(second["idempotent_replay"])

    def test_quarantine_manifest_matches_committed_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            item = active / "a.txt"
            item.write_text("a", encoding="utf-8")
            result = quarantine_candidates(
                active,
                [item],
                root / "quarantine",
                root / "ledger",
                transaction_root=root / "transactions",
            )
            record = result["inventory"][0]
            target = root / "quarantine" / str(record["path"])
            self.assertEqual(
                hashlib.sha256(target.read_bytes()).hexdigest(), record["sha256"]
            )

    def test_quarantine_interruption_recovers_from_journal(self) -> None:
        self.test_quarantine_batch_failure_rolls_back_prior_moves()


if __name__ == "__main__":
    unittest.main()
