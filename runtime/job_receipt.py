"""Immutable durable queued-job receipt shape for PX schedulers/workflows."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
from typing import Any, Mapping

_SHA = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_STATES = frozenset({"completed", "completed_degraded", "failed", "cancelled"})
RETRYABLE_STATES = frozenset({"failed", "queue_unavailable", "worker_lost"})
_ALLOWED_STATES = TERMINAL_STATES | RETRYABLE_STATES | {"queued", "running", "cancellation_requested"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _id(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or len(value.encode()) > 512:
        raise ValueError(f"{label} must be bounded nonempty text")
    return value.strip()


def _hash(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class JobReceipt:
    job_id: str
    operation_id: str
    status: str
    request_signature: str
    permission_snapshot_hash: str
    authority_revision: str
    fabric_generation: str | None = None
    retrieval_generation: str | None = None
    dry_run: bool = False
    retry_count: int = 0
    max_retries: int = 0
    current_stage: str = "queued"
    stage_progress: Mapping[str, int] = field(default_factory=dict)
    cancellation_requested: bool = False
    result_hash: str | None = None
    error_code: str | None = None
    previous_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _id(self.job_id, "job_id"); _id(self.operation_id, "operation_id"); _id(self.authority_revision, "authority_revision")
        if self.status not in _ALLOWED_STATES:
            raise ValueError("unknown job status")
        _hash(self.request_signature, "request_signature")
        _hash(self.permission_snapshot_hash, "permission_snapshot_hash")
        _hash(self.fabric_generation, "fabric_generation", optional=True)
        _hash(self.retrieval_generation, "retrieval_generation", optional=True)
        _hash(self.result_hash, "result_hash", optional=True)
        _hash(self.previous_receipt_sha256, "previous_receipt_sha256", optional=True)
        if type(self.dry_run) is not bool or type(self.cancellation_requested) is not bool:
            raise ValueError("job flags must be literal booleans")
        if type(self.retry_count) is not int or type(self.max_retries) is not int or self.retry_count < 0 or self.max_retries < 0 or self.retry_count > self.max_retries:
            raise ValueError("invalid retry counters")
        _id(self.current_stage, "current_stage")
        if not isinstance(self.stage_progress, Mapping) or len(self.stage_progress) > 256:
            raise ValueError("stage_progress must be a bounded mapping")
        for stage, progress in self.stage_progress.items():
            _id(stage, "stage_progress key")
            if type(progress) is not int or type(progress) is bool or not 0 <= progress <= 100:
                raise ValueError("stage progress must be integer percent in 0..100")
        if self.error_code is not None:
            _id(self.error_code, "error_code")

    @property
    def receipt_sha256(self) -> str:
        return _sha({**asdict(self), "stage_progress": dict(sorted(self.stage_progress.items()))})

    @property
    def receipt_hash(self) -> str:
        return self.receipt_sha256

    @classmethod
    def create(cls, *, job_id: str, operation_id: str, request: Any, permission_snapshot: Any, authority_revision: str, fabric_generation: str | None = None, retrieval_generation: str | None = None, dry_run: bool = False, max_retries: int = 0) -> "JobReceipt":
        if type(max_retries) is not int or type(max_retries) is bool or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a literal boolean")
        return cls(
            job_id=_id(job_id, "job_id"), operation_id=_id(operation_id, "operation_id"), status="queued",
            request_signature=_sha(request), permission_snapshot_hash=_sha(permission_snapshot), authority_revision=_id(authority_revision, "authority_revision"),
            fabric_generation=fabric_generation, retrieval_generation=retrieval_generation, dry_run=dry_run, max_retries=max_retries,
        )

    def _transition(self, **changes: Any) -> "JobReceipt":
        return replace(self, previous_receipt_sha256=self.receipt_sha256, **changes)

    def advance_stage(self, stage: str, progress: int) -> "JobReceipt":
        if self.status in TERMINAL_STATES:
            raise ValueError("cannot advance a terminal job")
        stage = _id(stage, "stage")
        if type(progress) is not int or type(progress) is bool or not 0 <= progress <= 100:
            raise ValueError("progress must be an integer percent in 0..100")
        current = self.stage_progress.get(stage, -1)
        if progress < current:
            raise ValueError("stage progress cannot move backwards")
        values = dict(self.stage_progress); values[stage] = progress
        return self._transition(status="running", current_stage=stage, stage_progress=values)

    def request_cancel(self) -> "JobReceipt":
        if self.status in TERMINAL_STATES:
            return self
        return self._transition(status="cancellation_requested", cancellation_requested=True)

    def retry(self) -> "JobReceipt":
        if self.status not in RETRYABLE_STATES:
            raise ValueError("job is not retryable from its current state")
        if self.retry_count >= self.max_retries:
            raise ValueError("retry limit reached")
        return self._transition(status="queued", current_stage="queued", retry_count=self.retry_count + 1, cancellation_requested=False, error_code=None, result_hash=None)

    def finish(self, status: str, *, result: Any = None, error_code: str | None = None) -> "JobReceipt":
        if status not in TERMINAL_STATES:
            raise ValueError("finish requires a terminal status")
        if self.status in TERMINAL_STATES:
            raise ValueError("job is already terminal")
        if self.cancellation_requested and status in {"completed", "completed_degraded"}:
            raise ValueError("cancellation-requested job cannot finish as successful")
        if status in {"completed", "completed_degraded"} and result is None:
            raise ValueError("successful terminal state requires a result")
        if status == "failed" and not error_code:
            raise ValueError("failed terminal state requires an error_code")
        return self._transition(status=status, current_stage=status, cancellation_requested=(status == "cancelled" or self.cancellation_requested), result_hash=_sha(result) if result is not None else None, error_code=error_code)
