from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from runtime.resource_lifecycle import (
    ResourceClassification,
    ResourceManager,
    ResourceStatus,
    RunState,
    StorageBudget,
)


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0 and f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class ResourceLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manager = ResourceManager(self.root / "state" / "ledger.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _workspace(self, run_id: str = "run-1"):
        return self.manager.create_workspace(
            self.root,
            project_id="project",
            run_id=run_id,
            lane_id="lane",
            creator="test",
        )

    def test_normal_completion_reclaims_owned_workspace_and_receipts_are_exact(self) -> None:
        record = self._workspace()
        target = Path(record.path or "")
        (target / "data.bin").write_bytes(b"12345")
        self.manager.mark_run_ended("run-1", RunState.COMPLETED)

        receipt = self.manager.reclaim(record.resource_id, reason="test", apply=True)

        self.assertFalse(target.exists())
        self.assertEqual(receipt.resources_reclaimed, 1)
        self.assertEqual(receipt.files_removed, 1)
        self.assertEqual(receipt.bytes_reclaimed, 5)
        self.assertEqual(receipt.workers, 1)
        self.assertTrue(
            (self.manager.receipt_dir / f"{receipt.cleanup_id}.json").is_file()
        )

    def test_failed_scope_cleans_unless_debug_retention_is_governed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with self.manager.workspace(
                self.root,
                project_id="project",
                run_id="failed-clean",
                lane_id="lane",
                creator="test",
            ) as path:
                failed_path = path
                raise RuntimeError("boom")
        self.assertFalse(failed_path.exists())

        with self.assertRaisesRegex(RuntimeError, "retain"):
            with self.manager.workspace(
                self.root,
                project_id="project",
                run_id="failed-retained",
                lane_id="lane",
                creator="test",
                retain_on_failure=True,
            ) as path:
                retained_path = path
                raise RuntimeError("retain")
        retained = next(
            item
            for item in self.manager.ledger.load()
            if item.run_id == "failed-retained"
        )
        self.assertTrue(retained_path.is_dir())
        self.assertEqual(retained.status, ResourceStatus.RETAINED.value)
        self.assertEqual(retained.retained_reason, "governed_debug_retention")

        self.manager.update(
            retained.resource_id,
            status=ResourceStatus.RECLAIMABLE.value,
            retained_reason=None,
        )
        receipt = self.manager.reclaim(
            retained.resource_id, reason="debug disposition ended", apply=True
        )
        self.assertEqual(receipt.resources_reclaimed, 1)
        self.assertFalse(retained_path.exists())

    def test_unknown_protected_and_unreviewed_quarantine_fail_closed(self) -> None:
        for classification in (
            ResourceClassification.UNKNOWN,
            ResourceClassification.PROTECTED,
            ResourceClassification.QUARANTINE,
        ):
            path = self.root / classification.value
            path.mkdir()
            record = self.manager.register_path(
                path,
                allowed_cleanup_root=self.root,
                project_id="project",
                run_id=f"run-{classification.value}",
                lane_id="lane",
                creator="test",
                classification=classification,
            )
            self.manager.mark_run_ended(record.run_id, RunState.COMPLETED)
            receipt = self.manager.reclaim(record.resource_id, reason="test", apply=True)
            self.assertEqual(receipt.resources_reclaimed, 0)
            self.assertTrue(path.exists())

    def test_approved_quarantine_can_be_dispositioned_explicitly(self) -> None:
        path = self.root / "reviewed-quarantine"
        path.mkdir()
        record = self.manager.register_path(
            path,
            allowed_cleanup_root=self.root,
            project_id="project",
            run_id="quarantine-run",
            lane_id="lane",
            creator="test",
            classification=ResourceClassification.QUARANTINE,
        )
        self.manager.mark_run_ended(record.run_id, RunState.COMPLETED)
        self.manager.approve_quarantine_reclamation(record.resource_id)
        self.manager.update(record.resource_id, status=ResourceStatus.RECLAIMABLE.value)
        receipt = self.manager.reclaim(record.resource_id, reason="approved", apply=True)
        self.assertEqual(receipt.resources_reclaimed, 1)
        self.assertFalse(path.exists())

    def test_evidence_and_active_child_block_until_resolved(self) -> None:
        record = self.manager.create_workspace(
            self.root,
            project_id="project",
            run_id="evidence-run",
            lane_id="lane",
            creator="test",
            retention_required=True,
        )
        target = Path(record.path or "")
        child = self.manager.register_path(
            target / "child",
            allowed_cleanup_root=self.root,
            project_id="project",
            run_id="child-run",
            lane_id="lane",
            creator="test",
            parent_resource_id=record.resource_id,
        )
        self.manager.mark_run_ended("evidence-run", RunState.COMPLETED)
        allowed, reasons = self.manager.reclamation_gate(
            self.manager.ledger.get(record.resource_id)
        )
        self.assertFalse(allowed)
        self.assertTrue(any("evidence" in item for item in reasons))
        self.assertTrue(any("child" in item for item in reasons))

        evidence = self.root / "promoted.json"
        evidence.write_text(json.dumps({"valid": True}), encoding="utf-8")
        self.manager.promote_outputs(record.resource_id, [evidence], validated=True)
        self.manager.mark_run_ended("child-run", RunState.COMPLETED)
        self.manager.update(child.resource_id, status=ResourceStatus.RECLAIMED.value)
        receipt = self.manager.reclaim(record.resource_id, reason="resolved", apply=True)
        self.assertEqual(receipt.resources_reclaimed, 1)
        self.assertTrue(evidence.is_file())

    def test_path_escape_root_and_link_escape_are_blocked(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed cleanup root"):
            self.manager.register_path(
                self.root.parent / "outside",
                allowed_cleanup_root=self.root,
                project_id="project",
                run_id="escape",
                lane_id="lane",
                creator="test",
            )

        outside = self.root.parent / f"{self.root.name}-outside-target"
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        link = self.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "allowed cleanup root"):
            self.manager.register_path(
                link,
                allowed_cleanup_root=self.root,
                project_id="project",
                run_id="link",
                lane_id="lane",
                creator="test",
            )

    def test_nested_link_blocks_recursive_cleanup(self) -> None:
        record = self._workspace("link-run")
        target = Path(record.path or "")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        try:
            (target / "escape").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        self.manager.mark_run_ended("link-run", RunState.COMPLETED)
        receipt = self.manager.reclaim(record.resource_id, reason="test", apply=True)
        self.assertEqual(receipt.resources_reclaimed, 0)
        self.assertGreaterEqual(receipt.links_encountered, 1)
        self.assertTrue((outside / "keep.txt").is_file())

    def test_cleanup_failure_is_ledgered_and_reconciliation_fails(self) -> None:
        record = self._workspace("failure-run")
        self.manager.mark_run_ended("failure-run", RunState.COMPLETED)
        with mock.patch("runtime.resource_lifecycle.shutil.rmtree", side_effect=OSError("busy")):
            receipt = self.manager.reclaim(record.resource_id, reason="test", apply=True)
        self.assertEqual(receipt.resources_failed, 1)
        self.assertEqual(
            self.manager.ledger.get(record.resource_id).status,
            ResourceStatus.CLEANUP_FAILED.value,
        )
        self.assertFalse(self.manager.reconcile(apply=False)["valid"])

    def test_storage_pressure_alerts_without_deleting_anything(self) -> None:
        record = self._workspace("budget-run")
        self.manager.update(record.resource_id, bytes=100, files=20)
        result = self.manager.storage_status(
            self.root,
            StorageBudget(
                minimum_free_bytes=0,
                max_owned_ephemeral_bytes=50,
                max_workspace_count=0,
                max_file_count=10,
            ),
        )
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["alerts"]), 3)
        self.assertTrue(Path(record.path or "").exists())

    def test_cancellation_terminates_registered_process_tree(self) -> None:
        child_pid_file = self.root / "child.pid"
        child_code = "import time; time.sleep(120)"
        parent_code = (
            "import pathlib,subprocess,sys,time; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); "
            "time.sleep(120)"
        )
        record, process = self.manager.spawn_owned_process(
            [sys.executable, "-c", parent_code],
            cwd=self.root,
            project_id="project",
            run_id="process-run",
            lane_id="inventory",
            creator="test",
        )
        deadline = time.monotonic() + 10
        while not child_pid_file.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(child_pid_file.is_file())
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))

        receipt = self.manager.terminate_owned_process(
            record.resource_id, graceful_timeout_seconds=0.5
        )

        self.assertEqual(receipt.orphan_processes_reaped, 1)
        self.assertIsNotNone(process.poll())
        deadline = time.monotonic() + 5
        while _pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(_pid_exists(child_pid))
        self.assertEqual(
            self.manager.ledger.get(record.resource_id).status,
            ResourceStatus.RECLAIMED.value,
        )


if __name__ == "__main__":
    unittest.main()
