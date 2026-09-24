"""Plan identity-preserving physical memory relocation metadata.

``MemoryRecord.layer`` remains semantic/governance classification.  Physical storage
location is deliberately separate, so moving a record between hot/warm/cold/archive
storage cannot silently alter meaning, ACL, certification, or logical identity.

This module only plans and validates metadata transitions.  Persisting a returned
``MemoryLocation`` still belongs to the canonical PX memory/storage owner.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .memory_fabric import MemoryRecord
from .semantic_code_types import stable_sha256
from .semantic_memory_refs import MemoryReference

STORAGE_TIERS = frozenset({"hot", "warm", "cold", "archive"})
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _digest(value: str, field: str) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a SHA-256 hex digest")


def _locator(value: str, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    if len(value.encode("utf-8")) > 8192:
        raise ValueError(f"{field} exceeds 8192 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class MemoryLocation:
    memory_id: str
    project_id: str
    storage_tier: str
    storage_locator: str
    location_revision: int
    record_revision: int
    content_sha256: str

    def __post_init__(self) -> None:
        MemoryReference(self.project_id, self.memory_id)
        if self.storage_tier not in STORAGE_TIERS:
            raise ValueError("invalid physical memory storage tier")
        _locator(self.storage_locator, "memory storage locator")
        if type(self.location_revision) is not int or self.location_revision < 1:
            raise ValueError("location_revision must be a positive integer")
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("record_revision must be a positive integer")
        _digest(self.content_sha256, "content_sha256")


@dataclass(frozen=True, slots=True)
class MemoryRelocationPlan:
    memory_id: str
    project_id: str
    from_tier: str
    to_tier: str
    from_locator: str
    to_locator: str
    expected_location_revision: int
    expected_record_revision: int
    expected_source_sha256: str
    plan_sha256: str

    def __post_init__(self) -> None:
        MemoryReference(self.project_id, self.memory_id)
        if self.from_tier not in STORAGE_TIERS or self.to_tier not in STORAGE_TIERS:
            raise ValueError("relocation plan contains an invalid storage tier")
        _locator(self.from_locator, "from_locator")
        _locator(self.to_locator, "to_locator")
        if type(self.expected_location_revision) is not int or self.expected_location_revision < 1:
            raise ValueError("expected_location_revision must be a positive integer")
        if type(self.expected_record_revision) is not int or self.expected_record_revision < 1:
            raise ValueError("expected_record_revision must be a positive integer")
        _digest(self.expected_source_sha256, "expected_source_sha256")
        _digest(self.plan_sha256, "plan_sha256")


def _plan_identity(plan: MemoryRelocationPlan) -> dict[str, object]:
    return {
        "memory_id": plan.memory_id,
        "project_id": plan.project_id,
        "from_tier": plan.from_tier,
        "to_tier": plan.to_tier,
        "from_locator": plan.from_locator,
        "to_locator": plan.to_locator,
        "expected_location_revision": plan.expected_location_revision,
        "expected_record_revision": plan.expected_record_revision,
        "expected_source_sha256": plan.expected_source_sha256,
    }


def plan_memory_relocation(
    record: MemoryRecord,
    current: MemoryLocation,
    *,
    to_tier: str,
    to_locator: str,
) -> MemoryRelocationPlan:
    if current.memory_id != record.memory_id or current.project_id != record.project_id:
        raise ValueError("memory location identity mismatch")
    if current.record_revision != record.revision or current.content_sha256 != record.source_sha256:
        raise RuntimeError("memory location is stale relative to record identity")
    if to_tier not in STORAGE_TIERS:
        raise ValueError("invalid target storage tier")
    _locator(to_locator, "target storage locator")
    if to_tier == current.storage_tier and to_locator == current.storage_locator:
        raise ValueError("memory relocation target is already current")
    body = {
        "memory_id": record.memory_id,
        "project_id": record.project_id,
        "from_tier": current.storage_tier,
        "to_tier": to_tier,
        "from_locator": current.storage_locator,
        "to_locator": to_locator,
        "expected_location_revision": current.location_revision,
        "expected_record_revision": record.revision,
        "expected_source_sha256": record.source_sha256,
    }
    return MemoryRelocationPlan(**body, plan_sha256=stable_sha256(body))


def apply_memory_relocation(
    record: MemoryRecord,
    current: MemoryLocation,
    plan: MemoryRelocationPlan,
    *,
    write: bool = False,
) -> tuple[MemoryRecord, MemoryLocation]:
    if type(write) is not bool:
        raise TypeError("write must be a boolean")
    if stable_sha256(_plan_identity(plan)) != plan.plan_sha256:
        raise RuntimeError("memory relocation plan digest mismatch")
    if record.memory_id != plan.memory_id or record.project_id != plan.project_id:
        raise ValueError("relocation plan identity mismatch")
    if current.memory_id != plan.memory_id or current.project_id != plan.project_id:
        raise ValueError("current location identity mismatch")
    if record.revision != plan.expected_record_revision or record.source_sha256 != plan.expected_source_sha256:
        raise RuntimeError("stale memory record relocation plan")
    if (
        current.location_revision != plan.expected_location_revision
        or current.storage_tier != plan.from_tier
        or current.storage_locator != plan.from_locator
    ):
        raise RuntimeError("memory location changed since planning")
    if current.record_revision != record.revision or current.content_sha256 != record.source_sha256:
        raise RuntimeError("current location no longer matches memory record")
    next_location = MemoryLocation(
        record.memory_id,
        record.project_id,
        plan.to_tier,
        plan.to_locator,
        current.location_revision + (1 if write else 0),
        record.revision,
        record.source_sha256,
    )
    # The MemoryRecord itself is deliberately unchanged by physical relocation.
    return record, next_location
