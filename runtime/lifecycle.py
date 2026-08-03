"""Deterministic checkpoints and evidence-gated retry decisions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Iterable, Protocol


@dataclass(frozen=True, slots=True)
class Checkpoint:
    task_id: str
    sequence: int
    stage: str
    status: str
    capability_id: str | None
    evidence_ids: tuple[str, ...]
    created_at: datetime


class CheckpointSink(Protocol):
    def append(self, checkpoint: Checkpoint) -> None: ...


class MemoryCheckpointSink:
    """In-memory default: checkpoints do not silently create filesystem effects."""

    def __init__(self) -> None:
        self.records: list[Checkpoint] = []

    def append(self, checkpoint: Checkpoint) -> None:
        self.records.append(checkpoint)


@dataclass(frozen=True, slots=True)
class FailureRecord:
    task_id: str
    capability_id: str | None
    fingerprint: str
    attempt: int
    evidence_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class RetryDecision:
    allowed: bool
    reason: str


def failure_fingerprint(capability_id: str | None, error_type: str, message: str) -> str:
    normalized = "|".join((capability_id or "none", error_type.strip(), " ".join(message.split())))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def decide_retry(
    previous: FailureRecord,
    *,
    candidate_attempt: int,
    evidence_ids: Iterable[str],
    max_retries: int,
    require_new_evidence: bool,
) -> RetryDecision:
    if candidate_attempt != previous.attempt + 1:
        return RetryDecision(False, "retry attempt is not sequential")
    if candidate_attempt > max_retries + 1:
        return RetryDecision(False, "retry budget exhausted")
    new_evidence = set(evidence_ids) - set(previous.evidence_ids)
    if require_new_evidence and not new_evidence:
        return RetryDecision(False, "retry requires new evidence")
    return RetryDecision(True, "retry admitted")


def make_checkpoint(
    task_id: str,
    sequence: int,
    stage: str,
    status: str,
    capability_id: str | None,
    evidence_ids: Iterable[str] = (),
) -> Checkpoint:
    return Checkpoint(
        task_id=task_id,
        sequence=sequence,
        stage=stage,
        status=status,
        capability_id=capability_id,
        evidence_ids=tuple(sorted(set(evidence_ids))),
        created_at=datetime.now(timezone.utc),
    )
