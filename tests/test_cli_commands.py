from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime.admission_controller import AdmissionDecision
from runtime.cli import (
    _claim_test_orchestration_single_flight,
    _prepare_certification_hygiene,
    _release_test_orchestration_single_flight,
    _refresh_stale_groups_for_full_profile,
    _require_claimed_full_profile_campaign,
    _summarize_audit,
    main,
)
from runtime.test_orchestration_lock import (
    OWNER_ENV,
    SUPERVISED_CHILD_ENV,
    claim_orchestration_lock,
    release_orchestration_lock,
)


ROOT = Path(__file__).parents[1]


def invoke(*arguments: str) -> tuple[int, dict]:
    output = StringIO()
    with redirect_stdout(output):
        status = main(["--root", str(ROOT), *arguments])
    return status, json.loads(output.getvalue())


class CliCommandTests(unittest.TestCase):
    def test_claimed_full_profile_child_uses_structural_exact_claim(self) -> None:
        claim = {
            "stage": "full_profile",
            "claim_id": "release-stage:PX:full_profile:one",
        }
        release = {
            "valid": True,
            "state": "active",
            "active_claim": claim,
            "stages": {
                "full_profile": {"status": "claimed", "claim_id": claim["claim_id"]}
            },
        }
        with patch(
            "runtime.release_campaign.release_campaign_status",
            return_value=release,
        ) as status:
            self.assertEqual(_require_claimed_full_profile_campaign(ROOT), release)
        status.assert_called_once_with(ROOT, verify_source=False)

    def test_full_profile_orchestration_is_repository_single_flight(self) -> None:
        from argparse import Namespace
        from runtime.file_lock import FileLockTimeout

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(command="test-profile", action="run", name="full")
            first, previous = _claim_test_orchestration_single_flight(root, args)
            try:
                with self.assertRaisesRegex(FileLockTimeout, "another process"):
                    _claim_test_orchestration_single_flight(root, args)
            finally:
                _release_test_orchestration_single_flight(first, previous)

    def test_every_mutating_profile_and_group_uses_single_flight(self) -> None:
        from argparse import Namespace

        cases = (
            Namespace(command="test-profile", action="run", name="fast"),
            Namespace(command="test-group", action="run", name="core"),
            Namespace(command="test-group", action="run-stale", name=None),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for args in cases:
                with self.subTest(command=args.command, action=args.action):
                    lock, previous = _claim_test_orchestration_single_flight(
                        root, args
                    )
                    try:
                        self.assertIsNotNone(lock)
                    finally:
                        _release_test_orchestration_single_flight(lock, previous)

    def test_owned_stale_group_child_reuses_parent_orchestration_lease(self) -> None:
        from argparse import Namespace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = Namespace(command="test-profile", action="run", name="full")
            group = Namespace(command="test-group", action="run-stale", name=None)
            first, previous = _claim_test_orchestration_single_flight(root, profile)
            try:
                with patch.dict(
                    "os.environ",
                    {SUPERVISED_CHILD_ENV: os.environ[OWNER_ENV]},
                ):
                    inherited, inherited_previous = (
                        _claim_test_orchestration_single_flight(root, group)
                    )
                    self.assertNotIn(SUPERVISED_CHILD_ENV, os.environ)
                self.assertIsNone(inherited)
                self.assertIsNotNone(inherited_previous)
            finally:
                _release_test_orchestration_single_flight(first, previous)

    def test_profile_lock_blocks_projection_identity_mutation(self) -> None:
        from argparse import Namespace
        from runtime.file_lock import FileLockTimeout

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = Namespace(command="test-profile", action="run", name="full")
            lock, previous = _claim_test_orchestration_single_flight(root, profile)
            try:
                with self.assertRaisesRegex(FileLockTimeout, "another process"):
                    claim_orchestration_lock(
                        root, owner_kind="projection-reconciliation"
                    )
            finally:
                _release_test_orchestration_single_flight(lock, previous)

    def test_projection_lock_blocks_profile_and_releases_cleanly(self) -> None:
        from argparse import Namespace
        from runtime.file_lock import FileLockTimeout

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = Namespace(command="test-profile", action="run", name="full")
            projection, previous = claim_orchestration_lock(
                root, owner_kind="projection-reconciliation"
            )
            try:
                with self.assertRaisesRegex(FileLockTimeout, "another process"):
                    _claim_test_orchestration_single_flight(root, profile)
            finally:
                release_orchestration_lock(projection, previous)
            acquired, acquired_previous = _claim_test_orchestration_single_flight(
                root, profile
            )
            _release_test_orchestration_single_flight(
                acquired, acquired_previous
            )

    def test_canonical_projection_owner_cannot_bypass_profile_lock(self) -> None:
        from argparse import Namespace
        from runtime.file_lock import FileLockTimeout
        from scripts.clean_source_export import _rebuild_candidate_projections

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = Namespace(command="test-profile", action="run", name="full")
            lock, previous = _claim_test_orchestration_single_flight(root, profile)
            try:
                with (
                    patch(
                        "scripts.clean_source_export._rebuild_candidate_projections_unlocked"
                    ) as rebuild,
                    self.assertRaisesRegex(FileLockTimeout, "another process"),
                ):
                    _rebuild_candidate_projections(root)
                rebuild.assert_not_called()
            finally:
                _release_test_orchestration_single_flight(lock, previous)

    def test_full_profile_refreshes_only_stale_groups_through_owned_runner(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "current", "current": True, "fresh": True, "passed": True},
                {"group": "stale-a", "current": False, "fresh": False, "passed": False},
                {"group": "stale-b", "current": False, "fresh": False, "passed": False},
            ],
        }
        current = {
            "valid": True,
            "groups": [
                {"group": "current", "current": True, "fresh": True, "passed": True},
                {"group": "stale-a", "current": True, "fresh": True, "passed": True},
                {"group": "stale-b", "current": True, "fresh": True, "passed": True},
            ],
        }
        registered = [
            {"group": "stale-a", "timeout_seconds": 200},
            {"group": "stale-b", "timeout_seconds": 300},
        ]
        with (
            patch("runtime.test_profiles.group_status", side_effect=[stale, current]),
            patch("runtime.test_profiles.resolve_test_groups", return_value=registered),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": True,
                    "exit_code": 0,
                    "duration_seconds": 1.25,
                    "stdout": "child detail must not be embedded",
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ) as runner,
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
        ):
            manager_type.return_value.reconcile.return_value = {
                "valid": True,
                "owned_child_processes_active": 0,
                "owned_ephemeral_unexplained": 0,
                "cleanup_failures": 0,
            }
            result = _refresh_stale_groups_for_full_profile(
                ROOT, timeout_seconds=321
            )

        self.assertTrue(result["refreshed"])
        self.assertEqual(result["stale_groups"], ["stale-a", "stale-b"])
        command = runner.call_args.args[0]
        self.assertEqual(command[-4:], ["test-group", "run-stale", "--workers", "3"])
        environment = runner.call_args.kwargs["environment"]
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue(any(key.casefold() == "path" for key in environment))
        self.assertEqual(runner.call_args.kwargs["timeout_seconds"], 560)
        self.assertEqual(
            runner.call_args.kwargs["disk_consumption_limit_bytes"],
            16 * 1024 * 1024 * 1024,
        )
        self.assertIs(runner.call_args.kwargs["manage_process_temp"], True)
        self.assertEqual(result["requested_timeout_seconds"], 321)
        self.assertEqual(result["effective_timeout_seconds"], 560)
        self.assertTrue(result["nested_resource_reconciliation"]["valid"])
        manager_type.return_value.reconcile.assert_called_once_with(apply=True)
        self.assertNotIn("stdout", result["execution"])

    def test_full_profile_collects_all_fresh_failed_groups_before_repair(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "broken-a", "current": False, "fresh": False, "passed": False},
                {"group": "broken-b", "current": False, "fresh": False, "passed": False},
            ],
        }
        failed = {
            "valid": False,
            "groups": [
                {"group": "broken-a", "current": False, "fresh": True, "passed": False},
                {"group": "broken-b", "current": False, "fresh": True, "passed": False},
            ],
        }
        registered = [
            {"group": "broken-a", "timeout_seconds": 30},
            {"group": "broken-b", "timeout_seconds": 30},
        ]
        with (
            patch("runtime.test_profiles.group_status", side_effect=[stale, failed]),
            patch("runtime.test_profiles.resolve_test_groups", return_value=registered),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": False,
                    "exit_code": 1,
                    "timed_out": False,
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
        ):
            manager_type.return_value.reconcile.return_value = {
                "valid": True,
                "owned_child_processes_active": 0,
                "owned_ephemeral_unexplained": 0,
                "cleanup_failures": 0,
            }
            result = _refresh_stale_groups_for_full_profile(ROOT)
        self.assertFalse(result["valid"])
        self.assertEqual(result["failed_groups"], ["broken-a", "broken-b"])

    def test_full_profile_group_refresh_fails_if_nested_resources_remain(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "broken", "current": False, "fresh": False, "passed": False}
            ],
        }
        with (
            patch("runtime.test_profiles.group_status", return_value=stale),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "broken", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": False,
                    "exit_code": 1,
                    "timed_out": False,
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
            self.assertRaisesRegex(
                ValueError, "owned stale test-group resource reconciliation failed"
            ),
        ):
            manager_type.return_value.reconcile.return_value = {
                "valid": False,
                "owned_child_processes_active": 1,
                "owned_ephemeral_unexplained": 2,
                "cleanup_failures": 0,
            }
            _refresh_stale_groups_for_full_profile(ROOT)

    def test_full_profile_group_refresh_allows_preexisting_parent_owner(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "derived-integrity", "current": False, "fresh": False}
            ],
        }
        fresh = {
            "valid": True,
            "groups": [
                {
                    "group": "derived-integrity",
                    "current": True,
                    "fresh": True,
                    "passed": True,
                }
            ],
        }
        parent = SimpleNamespace(
            resource_id="process-parent-owner",
            resource_type="process",
            classification="ephemeral",
            status="active",
            active=True,
        )
        with (
            patch("runtime.test_profiles.group_status", side_effect=[stale, fresh]),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "derived-integrity", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
        ):
            manager = manager_type.return_value
            manager.ledger.load.side_effect = [[parent], [parent]]
            manager.reconcile.return_value = {
                "valid": False,
                "owned_child_processes_active": 1,
                "owned_ephemeral_unexplained": 1,
                "cleanup_failures": 0,
            }
            result = _refresh_stale_groups_for_full_profile(ROOT)
        self.assertTrue(result["valid"])
        self.assertEqual(result["failed_groups"], [])

    def test_full_profile_group_refresh_allows_late_registered_direct_parent(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "derived-integrity", "current": False, "fresh": False}
            ],
        }
        fresh = {
            "valid": True,
            "groups": [
                {
                    "group": "derived-integrity",
                    "current": True,
                    "fresh": True,
                    "passed": True,
                }
            ],
        }
        parent = SimpleNamespace(
            resource_id="process-late-parent-owner",
            resource_type="process",
            classification="ephemeral",
            status="active",
            active=True,
            pid=os.getppid(),
        )
        with (
            patch("runtime.test_profiles.group_status", side_effect=[stale, fresh]),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "derived-integrity", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
        ):
            manager = manager_type.return_value
            manager.ledger.load.side_effect = [[], [parent]]
            manager.reconcile.return_value = {
                "valid": False,
                "owned_child_processes_active": 1,
                "owned_ephemeral_unexplained": 1,
                "cleanup_failures": 0,
            }
            result = _refresh_stale_groups_for_full_profile(ROOT)
        self.assertTrue(result["valid"])
        self.assertEqual(result["failed_groups"], [])

    def test_full_profile_group_refresh_allows_exact_redirected_release_owner(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "derived-integrity", "current": False, "fresh": False}
            ],
        }
        fresh = {
            "valid": True,
            "groups": [
                {
                    "group": "derived-integrity",
                    "current": True,
                    "fresh": True,
                    "passed": True,
                }
            ],
        }
        owner = SimpleNamespace(
            resource_id="process-redirected-release-owner",
            resource_type="process",
            classification="ephemeral",
            status="active",
            active=True,
            pid=987654,
            creator="scripts.run_release_candidate",
            run_id="PX-CANDIDATE",
            lane_id="full_profile-01",
        )
        with (
            patch("runtime.test_profiles.group_status", side_effect=[stale, fresh]),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "derived-integrity", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "supervision_status": "exited",
                    "process_tree_terminated": True,
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
            patch.dict(
                os.environ,
                {
                    "PX_RELEASE_OWNER_RUN_ID": "PX-CANDIDATE",
                    "PX_RELEASE_OWNER_LANE_ID": "full_profile-01",
                },
            ),
        ):
            manager = manager_type.return_value
            manager.ledger.load.side_effect = [[], [owner]]
            manager.reconcile.return_value = {
                "valid": False,
                "owned_child_processes_active": 1,
                "owned_ephemeral_unexplained": 1,
                "cleanup_failures": 0,
            }
            result = _refresh_stale_groups_for_full_profile(ROOT)
        self.assertTrue(result["valid"])
        self.assertEqual(result["failed_groups"], [])

    def test_full_profile_reconciles_closed_tree_before_disk_budget_failure(self) -> None:
        stale = {
            "valid": False,
            "groups": [
                {"group": "derived-integrity", "current": False, "fresh": False}
            ],
        }
        with (
            patch("runtime.test_profiles.group_status", return_value=stale),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "derived-integrity", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={
                    "valid": False,
                    "exit_code": 3221225786,
                    "timed_out": False,
                    "supervision_status": "disk_budget_exceeded",
                    "process_tree_terminated": True,
                    "errors": ["test process exceeded disk consumption ceiling"],
                },
            ),
            patch("runtime.resource_lifecycle.ResourceManager") as manager_type,
            self.assertRaisesRegex(ValueError, "disk consumption ceiling"),
        ):
            manager_type.return_value.reconcile.return_value = {
                "valid": True,
                "owned_child_processes_active": 0,
                "owned_ephemeral_unexplained": 0,
                "cleanup_failures": 0,
            }
            _refresh_stale_groups_for_full_profile(ROOT)

        manager_type.return_value.reconcile.assert_called_once_with(apply=True)

    def test_full_profile_group_refresh_fails_closed(self) -> None:
        stale = {"valid": False, "groups": [{"group": "broken", "current": False}]}
        with (
            patch("runtime.test_profiles.group_status", return_value=stale),
            patch(
                "runtime.test_profiles.resolve_test_groups",
                return_value=[{"group": "broken", "timeout_seconds": 30}],
            ),
            patch(
                "runtime.test_runner.run_test_command",
                return_value={"valid": False, "exit_code": 1, "stderr": "failed"},
            ),
            patch("runtime.resource_lifecycle.ResourceManager"),
            self.assertRaisesRegex(ValueError, "owned stale test-group refresh failed"),
        ):
            _refresh_stale_groups_for_full_profile(ROOT)

    def test_full_profile_does_not_rerun_current_groups(self) -> None:
        current = {
            "valid": True,
            "groups": [{"group": "already-current", "current": True, "fresh": True, "passed": True}],
        }
        with (
            patch("runtime.test_profiles.group_status", return_value=current),
            patch("runtime.test_runner.run_test_command") as runner,
            patch("runtime.resource_lifecycle.ResourceManager"),
        ):
            result = _refresh_stale_groups_for_full_profile(ROOT)

        self.assertFalse(result["refreshed"])
        self.assertEqual(result["stale_groups"], [])
        runner.assert_not_called()

    def test_section_runner_reuses_current_chunks_and_parallelizes_only_missing(self) -> None:
        import threading
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [
                {
                    "chunk_id": f"chunk-{index:02d}",
                    "input_sha256": str(index) * 64,
                    "member_count": 1,
                    "members": [f"tests/test_{index}.py"],
                    "inputs": [f"tests/test_{index}.py"],
                    "command": ["python", "-c", f"chunk-{index:02d}"],
                    "timeout_seconds": 10,
                }
                for index in range(1, 4)
            ]
            section = {
                "schema_version": "px.test-section/1.0",
                "valid": True,
                "section": "studio-memory-graph",
                "description": "isolated scheduler fixture",
                "dependencies": [],
                "inputs": ["registry/test_profiles.json"],
                "input_sha256": "f" * 64,
                "command": ["python", "-c", "legacy-command-must-not-run"],
                "cwd": str(root),
                "cwd_relative": ".",
                "timeout_seconds": 30,
                "chunks": chunks,
                "max_parallel_chunks": 2,
                "environment": {},
            }
            barrier = threading.Barrier(2)
            lock = threading.Lock()
            active = 0
            maximum_active = 0
            executed: list[str] = []
            managed_temp_flags: list[bool] = []

            def run_chunk(command, **kwargs):
                nonlocal active, maximum_active
                chunk_id = command[-1]
                with lock:
                    executed.append(chunk_id)
                    managed_temp_flags.append(kwargs.get("manage_process_temp"))
                    active += 1
                    maximum_active = max(maximum_active, active)
                barrier.wait(timeout=2)
                time.sleep(0.02)
                with lock:
                    active -= 1
                return {
                    "valid": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_seconds": 0.02,
                    "stdout": chunk_id,
                    "stderr": "",
                }

            current = {
                "schema_version": "px.test-section-chunk-receipt/1.1",
                "section": "studio-memory-graph",
                "chunk_id": "chunk-01",
                "input_sha256": "1" * 64,
                "member_count": 1,
                "members": ["tests/test_1.py"],
                "passed": True,
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 0.01,
                "output_evidence": {
                    "stdout_sha256": "0" * 64,
                    "stdout_bytes": 0,
                    "stderr_sha256": "0" * 64,
                    "stderr_bytes": 0,
                    "failure_nodes": [],
                },
                "receipt_sha256": "a" * 64,
            }

            def read_receipt(_root, _section, chunk_id):
                return current if chunk_id == "chunk-01" else {}

            output = StringIO()
            with (
                patch("runtime.test_profiles.resolve_test_section", return_value=section),
                patch(
                    "runtime.test_profiles.section_status",
                    return_value={"sections": []},
                ),
                patch(
                    "runtime.test_profiles.read_section_chunk_receipt",
                    side_effect=read_receipt,
                ),
                patch(
                    "runtime.test_profiles.write_section_chunk_receipt",
                    side_effect=lambda _root, receipt: root
                    / f"{receipt['chunk_id']}.json",
                ),
                patch(
                    "runtime.test_profiles.write_section_receipt",
                    return_value=root / "section.json",
                ) as section_writer,
                patch("runtime.test_runner.run_test_command", side_effect=run_chunk),
                patch("runtime.resource_lifecycle.ResourceManager"),
                redirect_stdout(output),
            ):
                status = main(
                    [
                        "--root",
                        str(root),
                        "test-section",
                        "run",
                        "studio-memory-graph",
                    ]
                )
            result = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(sorted(executed), ["chunk-02", "chunk-03"])
            self.assertEqual(managed_temp_flags, [True, True])
            self.assertEqual(maximum_active, 2)
            self.assertEqual(section_writer.call_count, 2)
            in_progress = section_writer.call_args_list[0].args[1]
            self.assertFalse(in_progress["passed"])
            self.assertEqual(in_progress["input_sha256"], "f" * 64)
            self.assertTrue(result["chunk_results"][0]["reused"])
            self.assertTrue(result["section_receipt"]["passed"])
            self.assertEqual(
                result["section_receipt"]["chunks"][1]["members"],
                ["tests/test_2.py"],
            )
            self.assertEqual(
                result["section_receipt"]["chunks"][1]["output_evidence"][
                    "stdout_bytes"
                ],
                len("chunk-02"),
            )

    def test_audit_summary_bounds_large_detail_sets(self) -> None:
        report = {
            "valid": False,
            "release_open": True,
            "category_count": 15,
            "categories": {"one": {"valid": True}, "two": {"valid": False}},
            "errors": ["bounded failure"],
            "duplicate_file_groups": [{"large": "detail"}],
            "audit_hygiene": {"apply": False},
        }
        summary = _summarize_audit("structure", report)
        self.assertEqual(summary["schema_version"], "px.audit-summary/1.0")
        self.assertFalse(summary["valid"])
        self.assertEqual(summary["categories_count"], 2)
        self.assertEqual(summary["duplicate_file_groups_count"], 1)
        self.assertNotIn("categories", summary)

    def test_certification_hygiene_quarantines_startup_cache_recoverably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "runtime" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "cli.pyc").write_bytes(b"compiled")
            result = _prepare_certification_hygiene(root, apply=True)
            self.assertTrue(result["apply"])
            self.assertFalse(result["hard_delete"])
            self.assertEqual(result["inventoried_file_count"], 1)
            self.assertFalse(cache.exists())
            destination = root / str(result["quarantine_destination"])
            self.assertTrue((destination / "runtime/__pycache__/cli.pyc").is_file())

    def test_audit_hygiene_is_dry_run_without_explicit_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "runtime" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "cli.pyc").write_bytes(b"compiled")
            output = StringIO()
            with (
                patch(
                    "runtime.licensing.validate_licensing",
                    return_value={"valid": True},
                ),
                redirect_stdout(output),
            ):
                status = main(["--root", str(root), "audit", "licensing"])
            result = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertFalse(result["audit_hygiene"]["apply"])
            self.assertTrue((cache / "cli.pyc").is_file())

    def test_doctor_exit_status_follows_requested_readiness_contract(self) -> None:
        report = {
            "valid": True,
            "operable": False,
            "ready": False,
            "certification_ready": False,
            "overall_state": "blocked",
            "evaluated_at": "2026-01-01T00:00:00Z",
            "sections": {},
        }
        with patch("runtime.px_doctor.run_px_doctor", return_value=report):
            output = StringIO()
            with redirect_stdout(output):
                status = main(["--root", str(ROOT), "doctor"])
            default = json.loads(output.getvalue())
            self.assertEqual(status, 2)
            self.assertEqual(default["requested_contract"], "operable")
            self.assertFalse(default["contract_satisfied"])

            output = StringIO()
            with redirect_stdout(output):
                status = main(["--root", str(ROOT), "doctor", "--require", "syntax"])
            syntax = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertTrue(syntax["contract_satisfied"])

    def test_visibility_routes_exposes_machine_readable_gaps(self) -> None:
        status, output = invoke("visibility", "routes")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertTrue(output["certifiable"])
        self.assertEqual(output["route_count"], 14)
        self.assertEqual(output["tier_d_advertised"], [])
        self.assertEqual(output["tiers"], {"A": 2, "B": 4, "C": 6, "D": 2})

    def test_benchmark_and_assurance_commands_expose_governed_controls(self) -> None:
        profile = {
            "schema_version": "1.0",
            "run_id": "run-cli",
            "lane": "cold",
            "benchmark": {"name": "suite", "version": "1"},
            "agent": {"name": "agent", "version": "1"},
            "model": {"id": "model", "reasoning": "fixed"},
            "pacify_x": {
                "enabled": True,
                "version": "0.6.3",
                "sha": "a" * 40,
                "capabilities": [],
            },
            "limits": {"seconds": 60},
            "permissions": {"network": False},
            "retry_policy": {"max_retries": 0, "retryable_classes": []},
            "environment": {
                "container": "fixed",
                "memory": "disabled",
                "cache": "empty",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile_path = base / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            status, frozen = invoke(
                "benchmark", "freeze", "--profile", str(profile_path)
            )
            self.assertEqual(status, 0)
            self.assertTrue(frozen["profile"]["frozen"])
            axes_path = base / "axes.json"
            axes_path.write_text(
                json.dumps(
                    {
                        "behavior": 1,
                        "evaluator_calibration": 1,
                        "evidence_integrity": 1,
                        "coverage": 1,
                        "regression": 1,
                        "operations": 1,
                    }
                ),
                encoding="utf-8",
            )
            status, score = invoke("assurance", "score", "--axes", str(axes_path))
            self.assertEqual(status, 0)
            self.assertTrue(score["admissible"])

    def test_placement_cli_returns_advisory_content_addressed_decision(self) -> None:
        scores = {
            key: 0.9
            for key in (
                "correctness",
                "latency",
                "throughput",
                "operability",
                "portability",
                "cost",
                "maintainability",
                "reversibility",
            )
        }
        gates = {
            key: True
            for key in (
                "compatible",
                "correctness",
                "rollback_ready",
                "baseline_available",
            )
        }
        payload = {
            "mode": "language_runtime",
            "baseline_sha256": "a" * 64,
            "candidates": [
                {
                    "id": "current",
                    "class": "host_language",
                    "keep_current": True,
                    "scores": {key: 0.5 for key in scores},
                    "boundary_costs": {"transfer": 0},
                    "gates": gates,
                },
                {
                    "id": "worker",
                    "class": "compiled_worker",
                    "scores": scores,
                    "boundary_costs": {"transfer": 0.02},
                    "gates": gates,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "placement.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            status, decision = invoke("placement", "decide", "--input", str(source))
        self.assertEqual(status, 0)
        self.assertEqual(decision["selected_candidate"], "worker")
        self.assertFalse(decision["migration_authorized"])
        self.assertEqual(len(decision["decision_sha256"]), 64)

    def test_review_candidate_exit_codes_distinguish_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            evidence = Path(directory) / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            cases = {"admit": 0, "restrict": 2, "quarantine": 3, "reject": 4}
            for disposition, expected in cases.items():
                decision = AdmissionDecision(
                    True,
                    True,
                    disposition in {"admit", "restrict"},
                    True,
                    "test",
                    disposition,
                    (),
                    "test",
                    disposition,
                )
                with (
                    self.subTest(disposition=disposition),
                    patch(
                        "runtime.admission_controller.review_authoritative",
                        return_value=decision,
                    ),
                ):
                    status, output = invoke(
                        "review-candidate",
                        "--manifest",
                        str(manifest),
                        "--evidence",
                        str(evidence),
                    )
                    self.assertEqual(status, expected)
                    self.assertEqual(output["disposition"], disposition)

    def test_authoritative_verification_exit_codes_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "request.json"
            request.write_text("{}", encoding="utf-8")
            cases = {
                "verified": 0,
                "verification_failed": 5,
                "insufficient_trusted_evidence": 6,
                "invalid_request": 7,
                "evidence_integrity_failure": 8,
            }
            for decision, expected in cases.items():
                result = {
                    "verified": decision == "verified",
                    "authoritative": decision == "verified",
                    "decision": decision,
                    "reasons": [],
                }
                with (
                    self.subTest(decision=decision),
                    patch(
                        "runtime.outcome_verifier.verify_authoritative",
                        return_value=result,
                    ),
                ):
                    status, output = invoke("verify-outcome", "--request", str(request))
                    self.assertEqual(status, expected)
                    self.assertEqual(output["decision"], decision)

    def test_test_profile_timeout_fails_closed_without_traceback(self) -> None:
        timed_out = {
            "valid": False,
            "exit_code": 1,
            "timed_out": True,
            "duration_seconds": 1.0,
            "stdout": "",
            "stderr": "",
            "process_tree_terminated": True,
            "termination": {"method": "test-fixture", "errors": []},
            "errors": ["test profile exceeded 300 seconds"],
        }
        with (
            patch("runtime.test_runner.run_test_command", return_value=timed_out),
            patch(
                "runtime.cli._claim_test_orchestration_single_flight",
                return_value=(None, None),
            ),
        ):
            status, output = invoke("test-profile", "run", "fast")
        self.assertEqual(status, 1)
        self.assertFalse(output["valid"])
        self.assertTrue(output["timed_out"])

    def test_contract_corpus_is_exposed_as_an_auditable_boundary(self) -> None:
        status, output = invoke("contracts", "status")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertEqual(output["contract_count"], output["owned_count"])

    def test_startup_classification_and_working_set_commands_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, startup = invoke("startup", "--project", directory)
        self.assertEqual(status, 0)
        self.assertEqual(startup["hydrated_skill_bodies"], [])
        self.assertLessEqual(startup["capability_metadata_count"], 250)
        self.assertTrue(startup["tooling_assessment"]["deferred"])
        self.assertNotIn("inventory", startup["tooling_assessment"])
        status, classification = invoke(
            "classify", "--task", "validate a retrieval workflow"
        )
        self.assertEqual(status, 0)
        self.assertIn("retrieval", classification["domains"])
        status, selected = invoke("working-set", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(selected["capability_ids"]), 3)
        status, routed = invoke("route", "--task", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertTrue(routed["package"]["complete"])
        self.assertEqual(
            set(routed["discovery"]),
            {
                "skill_catalog",
                "semantic_capability_index",
                "cognitive_map_index",
                "agency_agent_registry",
            },
        )

    def test_specialties_exposes_metadata_states_without_skill_bodies(self) -> None:
        status, output = invoke("specialties", "--category", "security")
        self.assertEqual(status, 0)
        self.assertTrue(output["valid"])
        self.assertEqual(output["categories"][0]["id"], "security")
        self.assertTrue(
            all(
                "purpose" in item and "state" in item
                for item in output["categories"][0]["specialties"]
            )
        )

    def test_cognitive_cli_is_read_only_bounded_and_fresh(self) -> None:
        status, health = invoke("cognitive", "status")
        self.assertEqual(status, 0)
        self.assertTrue(health["valid"])
        self.assertEqual(health["index"]["unresolved_external_dependencies"], 0)
        status, result = invoke(
            "cognitive",
            "query",
            "--query",
            "finite domain constraint solver",
            "--limit",
            "2",
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            result["hits"][0]["identifier"], "finite-domain-constraint-solver"
        )
        status, plan = invoke(
            "cognitive",
            "hydrate-plan",
            "--key",
            "capability:finite-domain-constraint-solver",
            "--max-records",
            "4",
        )
        self.assertEqual(status, 0)
        self.assertLessEqual(len(plan["records"]), 4)

    def test_plan_is_bounded_and_includes_unload_plan(self) -> None:
        status, output = invoke("plan", "--goal", "verify outcome evidence")
        self.assertEqual(status, 0)
        self.assertLessEqual(len(output["candidate_bundle"]), 3)
        self.assertEqual(output["activation_limit"], 1)
        self.assertIn("release", output["unload_plan"])

    def test_caller_asserted_authorization_is_explicitly_simulated(self) -> None:
        denied_status, denied = invoke(
            "simulate-authorization", "--capability", "evidence-assembler"
        )
        allowed_status, allowed = invoke(
            "simulate-authorization",
            "--capability",
            "evidence-assembler",
            "--policy-allowed",
        )
        self.assertEqual(denied_status, 0)
        self.assertFalse(denied["approved"])
        self.assertFalse(denied["authoritative"])
        self.assertEqual(allowed_status, 0)
        self.assertTrue(allowed["approved"])
        self.assertFalse(allowed["authoritative"])

    def test_verify_and_retry_commands_consume_typed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            verification = location / "verification.json"
            verification.write_text(
                json.dumps(
                    {
                        "postconditions": {"tests": True},
                        "evidence": [{"id": "E-1", "status": "current", "valid": True}],
                        "policy_allowed": True,
                        "executor_claimed_complete": True,
                    }
                ),
                encoding="utf-8",
            )
            status, output = invoke(
                "evaluate-outcome-claims", "--request", str(verification)
            )
            self.assertEqual(status, 0)
            self.assertEqual(output["status"], "verified")
            self.assertFalse(output["authoritative"])

            failure = location / "failure.json"
            failure.write_text(
                json.dumps(
                    {
                        "task_id": "task-1",
                        "capability_id": "evidence-assembler",
                        "fingerprint": "abc",
                        "attempt": 1,
                        "evidence_ids": ["old"],
                        "message": "failed",
                    }
                ),
                encoding="utf-8",
            )
            denied_status, denied = invoke(
                "retry-decision",
                "--failure",
                str(failure),
                "--attempt",
                "2",
                "--evidence-id",
                "old",
            )
            allowed_status, allowed = invoke(
                "retry-decision",
                "--failure",
                str(failure),
                "--attempt",
                "2",
                "--evidence-id",
                "new",
            )
            self.assertEqual(denied_status, 1)
            self.assertIn("new evidence", denied["reason"])
            self.assertEqual(allowed_status, 0)
            self.assertTrue(allowed["allowed"])

    def test_release_preflight_claims_certify_once_and_defers_success_to_finalize(self):
        source = (ROOT / "runtime/cli.py").read_text(encoding="utf-8")
        start = source.index('elif args.release_action in {"preflight", "dry-run", "discover"}')
        finalizer_start = source.index(
            '            else:\n                from .release_campaign import (', start
        )
        branch = source[start:finalizer_start]
        self.assertNotIn('require_processing_stage(root, "package")', branch)
        self.assertNotIn('claim_release_stage(root, "package")', branch)
        self.assertIn('require_processing_stage(root, "certify")', branch)
        self.assertIn('release_stage_claim = claim_release_stage(root, "certify")', branch)
        self.assertIn(
            'release_stage_finish_deferred = output.get("valid") is True', branch
        )
        completion = source[
            source.index(
                "if release_stage_claim is not None and release_stage_finish_deferred:"
            ) :
        ]
        self.assertIn("finish_release_stage(", completion)
        self.assertIn('passed=output.get("valid") is True', completion)
        self.assertIn('"completion_deferred_to": "release finalize"', completion)

        finalizer = source[
            finalizer_start :
            source.index('elif args.command == "brief"', start)
        ]
        self.assertIn('active_claim.get("stage") == "certify"', finalizer)
        self.assertIn('release_stage_claim = active_claim', finalizer)
        self.assertIn('release_stage_claim = claim_release_stage(root, "certify")', finalizer)

    def test_release_finalize_participates_in_the_single_flight_lock(self):
        source = (ROOT / "runtime/cli.py").read_text(encoding="utf-8")
        lock_owner = source[source.index("def _claim_test_orchestration_single_flight") : source.index("def _release_test_orchestration_single_flight")]
        self.assertIn('in {"preflight", "dry-run", "finalize"}', lock_owner)
        self.assertIn('getattr(args, "command", None) == "test-section"', lock_owner)
        self.assertIn('"section-orchestration"', lock_owner)


if __name__ == "__main__":
    unittest.main()
