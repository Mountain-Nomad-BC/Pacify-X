"""Project-scoped, bounded materialization of trusted memory context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Iterable, Mapping

from .memory_fabric import MemoryRecord
from .memory_intelligence import MemoryCaller, can_access, resolve_loadout


SCHEMA_VERSION = "px.memory-query-plan/1.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryQueryPlan:
    schema_version: str
    plan_id: str
    project_id: str
    subject_id: str
    actor_id: str
    agent_id: str
    binding_ids: tuple[str, ...]
    memory_classes: tuple[str, ...]
    tiers: tuple[str, ...]
    max_items: int
    max_bytes: int
    max_tokens: int
    trust_floor: float
    max_age_seconds: int
    conflict_policy: str
    provenance_required: bool
    writeback_policy: str
    source_revision: str
    dependency_revisions: tuple[tuple[str, str], ...]
    plan_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "subject_id": self.subject_id,
            "actor_id": self.actor_id,
            "agent_id": self.agent_id,
            "binding_ids": list(self.binding_ids),
            "memory_classes": list(self.memory_classes),
            "tiers": list(self.tiers),
            "max_items": self.max_items,
            "max_bytes": self.max_bytes,
            "max_tokens": self.max_tokens,
            "trust_floor": self.trust_floor,
            "max_age_seconds": self.max_age_seconds,
            "conflict_policy": self.conflict_policy,
            "provenance_required": self.provenance_required,
            "writeback_policy": self.writeback_policy,
            "source_revision": self.source_revision,
            "dependency_revisions": dict(self.dependency_revisions),
            "plan_sha256": self.plan_sha256,
        }


def build_memory_query_plan(
    *,
    project_id: str,
    subject_id: str,
    actor_id: str,
    agent_id: str,
    binding_ids: Iterable[str],
    memory_classes: Iterable[str],
    tiers: Iterable[str],
    max_items: int,
    max_bytes: int,
    max_tokens: int,
    trust_floor: float,
    max_age_seconds: int,
    conflict_policy: str,
    provenance_required: bool,
    writeback_policy: str,
    source_revision: str,
    dependency_revisions: Mapping[str, object],
) -> MemoryQueryPlan:
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "subject_id": subject_id,
        "actor_id": actor_id,
        "agent_id": agent_id,
        "binding_ids": sorted(set(map(str, binding_ids))),
        "memory_classes": sorted(set(map(str, memory_classes))),
        "tiers": sorted(set(map(str, tiers))),
        "max_items": max_items,
        "max_bytes": max_bytes,
        "max_tokens": max_tokens,
        "trust_floor": trust_floor,
        "max_age_seconds": max_age_seconds,
        "conflict_policy": conflict_policy,
        "provenance_required": provenance_required,
        "writeback_policy": writeback_policy,
        "source_revision": source_revision,
        "dependency_revisions": dict(
            sorted((str(key), str(value)) for key, value in dependency_revisions.items())
        ),
    }
    content = _hash(base)
    base["plan_id"] = f"memory-plan-{content[:24]}"
    base["plan_sha256"] = _hash(base)
    plan = MemoryQueryPlan(
        SCHEMA_VERSION,
        str(base["plan_id"]),
        project_id,
        subject_id,
        actor_id,
        agent_id,
        tuple(base["binding_ids"]),  # type: ignore[arg-type]
        tuple(base["memory_classes"]),  # type: ignore[arg-type]
        tuple(base["tiers"]),  # type: ignore[arg-type]
        max_items,
        max_bytes,
        max_tokens,
        trust_floor,
        max_age_seconds,
        conflict_policy,
        provenance_required,
        writeback_policy,
        source_revision,
        tuple(base["dependency_revisions"].items()),  # type: ignore[union-attr]
        str(base["plan_sha256"]),
    )
    report = validate_memory_query_plan(plan)
    if not report["valid"]:
        raise ValueError("invalid memory query plan: " + "; ".join(report["errors"]))
    return plan


def validate_memory_query_plan(
    plan: MemoryQueryPlan,
    *,
    current_source_revision: str | None = None,
    current_dependency_revisions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    for field in ("project_id", "subject_id", "actor_id", "agent_id", "source_revision"):
        if not getattr(plan, field):
            errors.append(f"{field} is required")
    if not plan.binding_ids or not plan.memory_classes or not plan.tiers:
        errors.append("binding IDs, memory classes, and tiers are required")
    if plan.max_items < 1 or plan.max_bytes < 1 or plan.max_tokens < 1:
        errors.append("memory budgets must be positive")
    if not 0 <= plan.trust_floor <= 1:
        errors.append("trust floor must be between zero and one")
    if plan.max_age_seconds < 1:
        errors.append("freshness budget must be positive")
    if plan.conflict_policy not in {"reject", "quarantine"}:
        errors.append("conflict policy must reject or quarantine")
    if plan.writeback_policy not in {"deny", "proposal_only"}:
        errors.append("writeback policy must deny or be proposal_only")
    payload = plan.as_dict()
    unsigned = dict(payload)
    unsigned.pop("plan_sha256")
    expected_id = f"memory-plan-{_hash({key: value for key, value in unsigned.items() if key != 'plan_id'})[:24]}"
    if plan.plan_id != expected_id or plan.plan_sha256 != _hash(unsigned):
        errors.append("memory query plan identity is invalid")
    if current_source_revision is not None and plan.source_revision != current_source_revision:
        errors.append("memory query plan source revision is stale")
    if current_dependency_revisions is not None and plan.dependency_revisions != tuple(
        sorted((str(key), str(value)) for key, value in current_dependency_revisions.items())
    ):
        errors.append("memory query plan dependency revisions are stale")
    return {"schema_version": SCHEMA_VERSION, "valid": not errors, "errors": errors}


def materialize_memory_context(
    plan: MemoryQueryPlan,
    records: Iterable[MemoryRecord],
    *,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    """Materialize an immutable context receipt or fail closed with quarantines."""
    report = validate_memory_query_plan(plan)
    if not report["valid"]:
        raise ValueError("invalid memory query plan: " + "; ".join(report["errors"]))
    now = now_utc or datetime.now(timezone.utc)
    caller = MemoryCaller(plan.project_id, plan.actor_id, plan.agent_id, task_id=plan.subject_id)
    supplied = tuple(records)
    by_id = {record.memory_id: record for record in supplied}
    violations: list[str] = []
    eligible: list[MemoryRecord] = []
    for memory_id in plan.binding_ids:
        record = by_id.get(memory_id)
        if record is None:
            violations.append(f"missing_memory:{memory_id}")
            continue
        if record.project_id != plan.project_id or not can_access(caller, record):
            violations.append(f"foreign_or_unauthorized_memory:{memory_id}")
        elif record.memory_type not in plan.memory_classes or record.layer not in plan.tiers:
            violations.append(f"memory_class_or_tier_mismatch:{memory_id}")
        elif (
            record.confidence < plan.trust_floor
            or record.certification_status not in {"certified", "trusted"}
            or not record.retrieval_enabled
        ):
            violations.append(f"memory_below_trust_floor:{memory_id}")
        elif record.expires_at and record.expires_at <= now:
            violations.append(f"memory_stale:{memory_id}")
        elif (now - record.effective_at).total_seconds() > plan.max_age_seconds:
            violations.append(f"memory_stale:{memory_id}")
        elif plan.provenance_required and (
            not _SHA.fullmatch(record.source_sha256) or not record.evidence_locator
        ):
            violations.append(f"memory_provenance_missing:{memory_id}")
        else:
            eligible.append(record)
    selected_ids = {record.memory_id for record in eligible}
    conflicts = sorted(
        {
            tuple(sorted((record.memory_id, conflict)))
            for record in eligible
            for conflict in record.conflicts_with
            if conflict in selected_ids
        }
    )
    if conflicts:
        violations.extend(f"memory_conflict:{left}:{right}" for left, right in conflicts)
    bindings = resolve_loadout(caller, eligible, max_assets=plan.max_items)
    selected = [by_id[binding.memory_id] for binding in bindings]
    items = [
        {
            "memory_id": record.memory_id,
            "title": record.title,
            "summary": record.summary,
            "layer": record.layer,
            "memory_type": record.memory_type,
            "source_sha256": record.source_sha256,
            "evidence_locator": record.evidence_locator,
            "revision": record.revision,
        }
        for record in selected
    ]
    byte_count = len(json.dumps(items, sort_keys=True).encode("utf-8"))
    token_count = math.ceil(byte_count / 4)
    if len(selected) < len(eligible):
        violations.append("memory_item_budget_exceeded")
    if byte_count > plan.max_bytes:
        violations.append("memory_byte_budget_exceeded")
    if token_count > plan.max_tokens:
        violations.append("memory_token_budget_exceeded")
    if violations:
        items = []
        byte_count = 0
        token_count = 0
    body = {
        "schema_version": "px.memory-materialization/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "binding_ids": list(plan.binding_ids),
        "project_id": plan.project_id,
        "subject_id": plan.subject_id,
        "eligible": not violations,
        "items": items,
        "item_count": len(items),
        "byte_count": byte_count,
        "token_count": token_count,
        "quarantined": sorted(set(violations)),
        "writeback_policy": plan.writeback_policy,
    }
    return {**body, "receipt_sha256": _hash(body)}
