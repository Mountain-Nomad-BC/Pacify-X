from __future__ import annotations

import pytest

from runtime.capability_scheduler import Resources, Task, durable_job_receipt
from runtime.job_receipt import JobReceipt

H1 = "1" * 64
H2 = "2" * 64


def test_receipt_chain_preserves_request_identity() -> None:
    receipt = JobReceipt.create(job_id="j1", operation_id="cap.x", request={"x": 1}, permission_snapshot={"effects": ["read_local"]}, authority_revision="rev-1", fabric_generation=H1, retrieval_generation=H2, max_retries=1)
    running = receipt.advance_stage("retrieve", 25)
    done = running.advance_stage("retrieve", 100).finish("completed", result={"ok": True})
    assert running.previous_receipt_sha256 == receipt.receipt_sha256
    assert done.request_signature == receipt.request_signature
    assert done.permission_snapshot_hash == receipt.permission_snapshot_hash
    assert done.result_hash


def test_progress_cannot_move_backwards() -> None:
    receipt = JobReceipt.create(job_id="j1", operation_id="cap.x", request={}, permission_snapshot={}, authority_revision="rev")
    running = receipt.advance_stage("work", 80)
    with pytest.raises(ValueError, match="backwards"):
        running.advance_stage("work", 20)


def test_retry_preserves_signature_and_increments_only_within_budget() -> None:
    receipt = JobReceipt.create(job_id="j1", operation_id="cap.x", request={"a": 1}, permission_snapshot={}, authority_revision="rev", max_retries=1)
    failed = receipt.finish("failed", error_code="worker_lost")
    retried = failed.retry()
    assert retried.retry_count == 1
    assert retried.request_signature == receipt.request_signature
    with pytest.raises(ValueError, match="retryable"):
        retried.retry()


def test_scheduler_builds_standard_receipt_without_dispatching() -> None:
    task = Task(id="job-1", capability="cap.read", resources=Resources(cpu_cores=1))
    receipt = durable_job_receipt(task, permission_snapshot={"effects": ["read_local"]}, authority_revision="sched-1")
    assert receipt.job_id == "job-1"
    assert receipt.operation_id == "cap.read"
    assert receipt.status == "queued"


def test_cancel_requested_job_cannot_race_to_success() -> None:
    receipt = JobReceipt.create(job_id="j1", operation_id="cap.x", request={}, permission_snapshot={}, authority_revision="rev")
    cancelling = receipt.request_cancel()
    with pytest.raises(ValueError, match="cannot finish as successful"):
        cancelling.finish("completed", result={"late": True})
