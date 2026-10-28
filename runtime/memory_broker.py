"""Project-scoped, bounded materialization of trusted memory context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Iterable, Mapping

from .memory_fabric import MemoryRecord
from .memory_intelligence import MemoryCaller, can_access, resolve_loadout


SCHEMA_VERSION = "px.memory-query-plan/1.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")

#: Bounded skew tolerated when comparing memory timestamps to the trusted clock.
#: Anything stamped further in the future than this is quarantined, never used.
MEMORY_TIME_SKEW = timedelta(minutes=5)


def _aware_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC; aware values are normalized to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


from runtime.hash_utils import json_ascii_string_hash as _hash


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


def _validate_plan_quantities(max_items, max_bytes, max_tokens,
                              trust_floor, max_age_seconds):
    errors = []
    for name, value in (('max_items', max_items), ('max_bytes', max_bytes),
                        ('max_tokens', max_tokens), ('max_age_seconds', max_age_seconds)):
        if type(value) is not int or value < 1:
            errors.append(f'{name} must be a positive integer')
    if (isinstance(trust_floor, bool) or not isinstance(trust_floor, (int, float))
            or not math.isfinite(trust_floor) or not 0 <= trust_floor <= 1):
        errors.append('trust_floor must be a finite number between zero and one')
    return errors


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
    quantity_errors = _validate_plan_quantities(max_items, max_bytes, max_tokens,
                                                 trust_floor, max_age_seconds)
    if quantity_errors:
        raise ValueError('invalid memory query plan: ' + '; '.join(quantity_errors))
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
    errors.extend(_validate_plan_quantities(plan.max_items, plan.max_bytes,
                                            plan.max_tokens, plan.trust_floor,
                                            plan.max_age_seconds))
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
    current_source_revision: str | None = None,
    current_dependency_revisions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Materialize an immutable context receipt or fail closed with quarantines.

    ``current_source_revision`` / ``current_dependency_revisions`` are the
    trusted, live revision inputs (M03). When supplied, a stale plan is rejected
    outright instead of materializing old bindings.
    """
    report = validate_memory_query_plan(
        plan,
        current_source_revision=current_source_revision,
        current_dependency_revisions=current_dependency_revisions,
    )
    if not report["valid"]:
        raise ValueError("invalid memory query plan: " + "; ".join(report["errors"]))
    now = _aware_utc(now_utc or datetime.now(timezone.utc))
    caller = MemoryCaller(plan.project_id, plan.actor_id, plan.agent_id, task_id=plan.subject_id)
    supplied = tuple(records)
    # M01: duplicate memory ids must never make the resulting context depend on
    # input order. Conflicting duplicates are quarantined deterministically.
    grouped: dict[str, list[MemoryRecord]] = {}
    for record in supplied:
        grouped.setdefault(record.memory_id, []).append(record)
    duplicate_ids = {
        memory_id for memory_id, group in grouped.items() if len(group) > 1
    }
    by_id = {memory_id: group[0] for memory_id, group in grouped.items() if len(group) == 1}
    violations: list[str] = []
    eligible: list[MemoryRecord] = []
    for memory_id in plan.binding_ids:
        if memory_id in duplicate_ids:
            violations.append(f"duplicate_memory_id:{memory_id}")
            continue
        record = by_id.get(memory_id)
        if record is None:
            violations.append(f"missing_memory:{memory_id}")
            continue
        if (isinstance(record.confidence, bool)
                or not isinstance(record.confidence, (int, float))
                or not math.isfinite(record.confidence)
                or not 0 <= record.confidence <= 1):
            violations.append(f"memory_invalid_confidence:{memory_id}")
        elif record.project_id != plan.project_id or not can_access(caller, record):
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
        elif record.effective_at - now > MEMORY_TIME_SKEW:
            violations.append(f"memory_future_effective:{memory_id}")
        elif record.observed_at - now > MEMORY_TIME_SKEW:
            violations.append(f"memory_future_observed:{memory_id}")
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


def materialize_shared_contribution_context(
    contributions: Iterable[Mapping[str, object]], verifications: Iterable[Mapping[str, object]],
    *, project_id: str, max_items: int = 8, max_bytes: int = 16384,
) -> dict[str, object]:
    """Materialize independently verified contribution context through project bounds."""
    from .shared_contributions import validate_contribution, validate_verification, verification_summary
    if type(max_items) is not int or isinstance(max_items, bool) or not 1 <= max_items <= 256:
        raise ValueError("shared contribution item budget is invalid")
    if type(max_bytes) is not int or isinstance(max_bytes, bool) or not 256 <= max_bytes <= 8 * 1024 * 1024:
        raise ValueError("shared contribution byte budget is invalid")
    verification_rows = []
    for row in verifications:
        validate_verification(row)
        verification_rows.append(row)
    contribution_rows = []
    for raw in contributions:
        validate_contribution(raw)
        contribution_rows.append(raw)
    selected = []; used = 0
    for raw in sorted(contribution_rows, key=lambda row: str(row["record_sha256"])):
        if raw.get("project_id") != project_id: continue
        digest = str(raw["record_sha256"])
        summary = verification_summary(raw, verification_rows)
        if summary.get("passed") is not True: continue
        row = {"record_sha256":digest, "contribution_type":raw["contribution_type"], "description":raw["description"], "memory_refs":list(raw["memory_refs"]), "evidence_sha256":list(raw["evidence_sha256"]), "verification_sha256":list(summary.get("verification_sha256") or ()), "negative_result":raw["contribution_type"] == "negative_result"}
        size = len(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        if size > max_bytes: continue
        if used + size > max_bytes or len(selected) >= max_items: break
        selected.append(row); used += size
    body = {"schema_version":"px.shared-contribution-context/1.0", "project_id":project_id, "items":selected, "item_count":len(selected), "serialized_bytes":used, "max_items":max_items, "max_bytes":max_bytes, "authority_granted":False}
    return {**body, "context_sha256": _hash(body)}
