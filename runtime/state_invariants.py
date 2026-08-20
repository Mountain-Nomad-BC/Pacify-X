"""Fail-closed invariants for durable coordination transitions and startup.

The coordination store is authoritative operational state.  This module does
not repair or normalize it: a mutation candidate either preserves every
cross-record invariant or is rejected before a WAL manifest is published.
Startup performs the same checks against the retained state, event ancestry,
and strict memory counters.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

from .wal_transaction import JsonTransition


SCHEMA_VERSION = "px.coordination-invariants/1.0"
MAX_EVENT_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 5_000
MAX_MEMORY_BYTES = 64 * 1024 * 1024
MAX_MEMORY_RECORDS = 100_000
_HEX_DIGEST_LENGTH = 64
_TASK_STATES = frozenset(
    {
        "planned",
        "ready",
        "claimed",
        "in_progress",
        "waiting",
        "blocked",
        "completed",
        "reconciled",
        "released",
    }
)
_TASK_TRANSITIONS = {
    "planned": frozenset({"planned", "ready", "claimed"}),
    "ready": frozenset({"ready", "claimed"}),
    "claimed": frozenset(
        {"claimed", "in_progress", "waiting", "blocked", "completed", "released"}
    ),
    "in_progress": frozenset(
        {"in_progress", "waiting", "blocked", "completed", "released"}
    ),
    "waiting": frozenset(
        {"waiting", "in_progress", "blocked", "completed", "released"}
    ),
    "blocked": frozenset(
        {"blocked", "in_progress", "waiting", "completed", "released"}
    ),
    "completed": frozenset({"completed", "reconciled"}),
    "reconciled": frozenset({"reconciled"}),
    "released": frozenset({"released", "claimed"}),
}
_PLAN_STATES = frozenset({"active", "superseded", "completed"})
_PLAN_TRANSITIONS = {
    "active": frozenset({"active", "superseded", "completed"}),
    "superseded": frozenset({"superseded"}),
    "completed": frozenset({"completed"}),
}
_CLAIM_STATES = frozenset({"active", "released", "expired"})
_CLAIM_TRANSITIONS = {
    "active": frozenset({"active", "released", "expired"}),
    "released": frozenset({"released"}),
    "expired": frozenset({"expired"}),
}
_MEMORY_COUNTERS = {
    "session": "session_records",
    "project": "project_records",
    "state": "state_records",
    "system_candidate": "system_candidates",
}


@dataclass(frozen=True, order=True)
class InvariantViolation:
    code: str
    path: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


class StateInvariantError(RuntimeError):
    """Raised before publication when authoritative invariants do not hold."""

    def __init__(self, report: Mapping[str, object]) -> None:
        self.report = dict(report)
        violations = self.report.get("violations", ())
        summary = "; ".join(
            f"{item.get('code')}@{item.get('path')}"
            for item in violations
            if isinstance(item, Mapping)
        )
        super().__init__(f"coordination state invariants failed: {summary}")


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _without_digest(value: Mapping[str, object], field: str) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != field}


def _identifier(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _object_index(
    records: object,
    path: str,
    violations: list[InvariantViolation],
) -> dict[str, Mapping[str, object]]:
    if not isinstance(records, list):
        violations.append(InvariantViolation("shape", path, "must be an array"))
        return {}
    index: dict[str, Mapping[str, object]] = {}
    for offset, record in enumerate(records):
        item_path = f"{path}[{offset}]"
        if not isinstance(record, Mapping):
            violations.append(
                InvariantViolation("shape", item_path, "must be an object")
            )
            continue
        identifier = _identifier(record.get("id"))
        if not identifier:
            violations.append(
                InvariantViolation("identifier", item_path, "id is required")
            )
        elif identifier in index:
            violations.append(
                InvariantViolation(
                    "duplicate_id", item_path, f"duplicate id {identifier}"
                )
            )
        else:
            index[identifier] = record
    return index


def _finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _actor_identity(actor: object) -> tuple[str, str] | None:
    if not isinstance(actor, Mapping):
        return None
    actor_id = _identifier(actor.get("actor_id"))
    session_id = _identifier(actor.get("session_id"))
    return (actor_id, session_id) if actor_id and session_id else None


def _normalize_target(value: object) -> str:
    return str(value).strip().replace("\\", "/").strip("/").casefold()


def _targets_overlap(left: object, right: object) -> bool:
    first = _normalize_target(left)
    second = _normalize_target(right)
    return bool(
        first
        and second
        and (
            first == second
            or first.startswith(second + "/")
            or second.startswith(first + "/")
        )
    )


def _valid_revision(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HEX_DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value.casefold())
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _check_dependencies(
    tasks: Mapping[str, Mapping[str, object]], violations: list[InvariantViolation]
) -> None:
    dependencies: dict[str, tuple[str, ...]] = {}
    for task_id, task in tasks.items():
        raw = task.get("depends_on", ())
        if not isinstance(raw, list) or any(not _identifier(item) for item in raw):
            violations.append(
                InvariantViolation(
                    "dag_shape", f"tasks.{task_id}.depends_on", "must contain task IDs"
                )
            )
            dependencies[task_id] = ()
            continue
        values = tuple(map(str, raw))
        if len(set(values)) != len(values):
            violations.append(
                InvariantViolation(
                    "dag_duplicate_edge",
                    f"tasks.{task_id}.depends_on",
                    "duplicate dependency",
                )
            )
        dependencies[task_id] = values
        for dependency in values:
            if dependency not in tasks:
                violations.append(
                    InvariantViolation(
                        "dag_missing_task",
                        f"tasks.{task_id}.depends_on",
                        f"unknown dependency {dependency}",
                    )
                )
            if dependency == task_id:
                violations.append(
                    InvariantViolation(
                        "dag_cycle", f"tasks.{task_id}.depends_on", "self dependency"
                    )
                )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, ancestry: tuple[str, ...]) -> None:
        if task_id in visiting:
            cycle = " -> ".join((*ancestry, task_id))
            violations.append(InvariantViolation("dag_cycle", "tasks", cycle))
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies.get(task_id, ()):
            if dependency in tasks:
                visit(dependency, (*ancestry, task_id))
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(tasks):
        visit(task_id, ())


def _check_budgets(
    tasks: Mapping[str, Mapping[str, object]], violations: list[InvariantViolation]
) -> None:
    for task_id, task in tasks.items():
        budget = task.get("budget", {})
        usage = task.get("usage", {})
        if not isinstance(budget, Mapping):
            violations.append(
                InvariantViolation(
                    "budget_shape", f"tasks.{task_id}.budget", "must be an object"
                )
            )
            budget = {}
        if not isinstance(usage, Mapping):
            violations.append(
                InvariantViolation(
                    "budget_shape", f"tasks.{task_id}.usage", "must be an object"
                )
            )
            usage = {}
        pairs = (
            ("minutes", "max_minutes"),
            ("tokens", "max_tokens"),
            ("cost_usd", "max_cost_usd"),
        )
        exceeded = False
        for used_name, maximum_name in pairs:
            used = usage.get(used_name, 0)
            maximum = budget.get(maximum_name)
            if not _finite_nonnegative(used):
                violations.append(
                    InvariantViolation(
                        "budget_invalid",
                        f"tasks.{task_id}.usage.{used_name}",
                        "must be finite and nonnegative",
                    )
                )
            if maximum is not None and not _finite_nonnegative(maximum):
                violations.append(
                    InvariantViolation(
                        "budget_invalid",
                        f"tasks.{task_id}.budget.{maximum_name}",
                        "must be null or finite and nonnegative",
                    )
                )
            if _finite_nonnegative(used) and _finite_nonnegative(maximum):
                exceeded = exceeded or float(used) > float(maximum)
        expected_status = (
            "hard_stop"
            if exceeded and budget.get("hard_stop") is True
            else "soft_limit"
            if exceeded
            else "healthy"
        )
        if usage.get("status") != expected_status:
            violations.append(
                InvariantViolation(
                    "budget_status",
                    f"tasks.{task_id}.usage.status",
                    f"expected {expected_status}",
                )
            )
        if expected_status == "hard_stop" and task.get("status") != "blocked":
            violations.append(
                InvariantViolation(
                    "budget_hard_stop",
                    f"tasks.{task_id}.status",
                    "hard-stop exhaustion requires blocked task",
                )
            )


def _check_transitions(
    previous: Mapping[str, object],
    candidate: Mapping[str, object],
    violations: list[InvariantViolation],
) -> None:
    prior_revision = previous.get("revision")
    next_revision = candidate.get("revision")
    if not _valid_revision(prior_revision) or next_revision != int(prior_revision) + 1:
        violations.append(
            InvariantViolation(
                "revision_monotonic",
                "revision",
                f"expected {prior_revision!r} + 1, observed {next_revision!r}",
            )
        )
    for collection, transitions in (
        ("tasks", _TASK_TRANSITIONS),
        ("plans", _PLAN_TRANSITIONS),
        ("claims", _CLAIM_TRANSITIONS),
    ):
        prior_records = {
            _identifier(item.get("id")): item
            for item in previous.get(collection, ())
            if isinstance(item, Mapping) and _identifier(item.get("id"))
        }
        next_records = {
            _identifier(item.get("id")): item
            for item in candidate.get(collection, ())
            if isinstance(item, Mapping) and _identifier(item.get("id"))
        }
        for identifier, before in prior_records.items():
            after = next_records.get(identifier)
            if after is None:
                violations.append(
                    InvariantViolation(
                        "append_only_history", collection, f"removed {identifier}"
                    )
                )
                continue
            before_status = str(before.get("status", ""))
            after_status = str(after.get("status", ""))
            if after_status not in transitions.get(before_status, frozenset()):
                violations.append(
                    InvariantViolation(
                        "illegal_transition",
                        f"{collection}.{identifier}.status",
                        f"{before_status} -> {after_status}",
                    )
                )
    prior_tasks = {
        _identifier(item.get("id")): item
        for item in previous.get("tasks", ())
        if isinstance(item, Mapping)
    }
    next_tasks = {
        _identifier(item.get("id")): item
        for item in candidate.get("tasks", ())
        if isinstance(item, Mapping)
    }
    for task_id, before in prior_tasks.items():
        after = next_tasks.get(task_id)
        if after is None:
            continue
        before_usage = before.get("usage", {})
        after_usage = after.get("usage", {})
        if isinstance(before_usage, Mapping) and isinstance(after_usage, Mapping):
            for field in ("minutes", "tokens", "cost_usd"):
                prior_value = before_usage.get(field, 0)
                next_value = after_usage.get(field, 0)
                if _finite_nonnegative(prior_value) and _finite_nonnegative(next_value):
                    if float(next_value) < float(prior_value):
                        violations.append(
                            InvariantViolation(
                                "usage_monotonic",
                                f"tasks.{task_id}.usage.{field}",
                                f"decreased from {prior_value} to {next_value}",
                            )
                        )
    before_fencing = previous.get("team_fabric", {})
    after_fencing = candidate.get("team_fabric", {})
    before_tokens = (
        before_fencing.get("fencing_by_target", {})
        if isinstance(before_fencing, Mapping)
        else {}
    )
    after_tokens = (
        after_fencing.get("fencing_by_target", {})
        if isinstance(after_fencing, Mapping)
        else {}
    )
    if isinstance(before_tokens, Mapping) and isinstance(after_tokens, Mapping):
        for target, prior_token in before_tokens.items():
            next_token = after_tokens.get(target)
            if (
                target not in after_tokens
                or not _valid_revision(prior_token)
                or not _valid_revision(next_token)
                or int(next_token) < int(prior_token)
            ):
                violations.append(
                    InvariantViolation(
                        "fencing_monotonic",
                        f"team_fabric.fencing_by_target.{target}",
                        f"cannot move from {prior_token!r} to {next_token!r}",
                    )
                )
    before_memory = previous.get("memory", {})
    after_memory = candidate.get("memory", {})
    if isinstance(before_memory, Mapping) and isinstance(after_memory, Mapping):
        for field in _MEMORY_COUNTERS.values():
            before_count = before_memory.get(field, 0)
            after_count = after_memory.get(field, 0)
            if (
                _valid_revision(before_count)
                and _valid_revision(after_count)
                and after_count < before_count
            ):
                violations.append(
                    InvariantViolation(
                        "memory_counter_monotonic",
                        f"memory.{field}",
                        f"decreased from {before_count} to {after_count}",
                    )
                )


def validate_coordination_state(
    state: object,
    *,
    previous_state: Mapping[str, object] | None = None,
    event: Mapping[str, object] | None = None,
    observed_memory_counts: Mapping[str, int] | None = None,
    now_utc: datetime | None = None,
    phase: str = "precommit",
) -> dict[str, object]:
    """Validate one retained state or one proposed append-only transition."""
    violations: list[InvariantViolation] = []
    if not isinstance(state, Mapping):
        violations.append(InvariantViolation("shape", "$", "state must be an object"))
        candidate: Mapping[str, object] = {}
    else:
        candidate = state
    project = candidate.get("project")
    if (
        not isinstance(project, Mapping)
        or not _identifier(project.get("id"))
        or not _identifier(project.get("root"))
    ):
        violations.append(
            InvariantViolation(
                "project_identity", "project", "id and bounded root are required"
            )
        )
    revision = candidate.get("revision")
    if not _valid_revision(revision):
        violations.append(
            InvariantViolation(
                "revision_invalid", "revision", "must be a nonnegative integer"
            )
        )
    state_hash = candidate.get("state_hash")
    if not _is_digest(state_hash):
        violations.append(
            InvariantViolation("state_hash", "state_hash", "must be a SHA-256 digest")
        )
    else:
        hash_candidate = dict(candidate)
        hash_candidate["state_hash"] = None
        try:
            expected_state_hash = _stable_hash(hash_candidate)
        except (TypeError, ValueError):
            expected_state_hash = None
        if state_hash != expected_state_hash:
            violations.append(
                InvariantViolation(
                    "state_hash",
                    "state_hash",
                    "digest does not seal authoritative state",
                )
            )
    tasks = _object_index(candidate.get("tasks"), "tasks", violations)
    plans = _object_index(candidate.get("plans"), "plans", violations)
    claims = _object_index(candidate.get("claims"), "claims", violations)
    _check_dependencies(tasks, violations)
    _check_budgets(tasks, violations)

    active_plan = candidate.get("active_plan")
    if active_plan is not None:
        plan = plans.get(str(active_plan))
        if plan is None:
            violations.append(
                InvariantViolation(
                    "active_plan_missing", "active_plan", str(active_plan)
                )
            )
        elif plan.get("status") != "active":
            violations.append(
                InvariantViolation(
                    "active_plan_status", "active_plan", "must reference an active plan"
                )
            )
    for plan_id, plan in plans.items():
        if plan.get("status") not in _PLAN_STATES:
            violations.append(
                InvariantViolation(
                    "plan_status", f"plans.{plan_id}.status", "unsupported status"
                )
            )
        task_ids = plan.get("task_ids")
        if not isinstance(task_ids, list) or len(set(map(str, task_ids))) != len(
            task_ids
        ):
            violations.append(
                InvariantViolation(
                    "plan_tasks",
                    f"plans.{plan_id}.task_ids",
                    "must be a unique task ID array",
                )
            )
            continue
        for task_id in map(str, task_ids):
            if task_id not in tasks:
                violations.append(
                    InvariantViolation(
                        "plan_task_missing", f"plans.{plan_id}.task_ids", task_id
                    )
                )

    active_claims: list[tuple[str, Mapping[str, object]]] = []
    stamp = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for task_id, task in tasks.items():
        status = task.get("status")
        if status not in _TASK_STATES:
            violations.append(
                InvariantViolation(
                    "task_status", f"tasks.{task_id}.status", "unsupported status"
                )
            )
    fabric = candidate.get("team_fabric")
    fencing = fabric.get("fencing_by_target", {}) if isinstance(fabric, Mapping) else {}
    if not isinstance(fencing, Mapping):
        violations.append(
            InvariantViolation(
                "fencing_shape", "team_fabric.fencing_by_target", "must be an object"
            )
        )
        fencing = {}
    for target, token in fencing.items():
        if (
            not _normalize_target(target)
            or not _valid_revision(token)
            or int(token) < 1
        ):
            violations.append(
                InvariantViolation(
                    "fencing_token",
                    f"team_fabric.fencing_by_target.{target}",
                    "must be a positive integer",
                )
            )
    for claim_id, claim in claims.items():
        status = claim.get("status")
        if status not in _CLAIM_STATES:
            violations.append(
                InvariantViolation(
                    "claim_status", f"claims.{claim_id}.status", "unsupported status"
                )
            )
            continue
        if status != "active":
            continue
        active_claims.append((claim_id, claim))
        task_id = _identifier(claim.get("task_id"))
        task = tasks.get(task_id)
        if task is None:
            violations.append(
                InvariantViolation(
                    "claim_task_missing", f"claims.{claim_id}.task_id", task_id
                )
            )
            continue
        incomplete = [
            dependency
            for dependency in task.get("depends_on", ())
            if dependency in tasks
            and tasks[dependency].get("status") not in {"completed", "reconciled"}
        ]
        if incomplete:
            violations.append(
                InvariantViolation(
                    "claim_dependencies",
                    f"claims.{claim_id}.task_id",
                    f"incomplete dependencies {sorted(incomplete)}",
                )
            )
        claim_actor = _actor_identity(claim.get("actor"))
        if claim_actor is None or claim_actor != _actor_identity(task.get("owner")):
            violations.append(
                InvariantViolation(
                    "claim_owner_mismatch", f"claims.{claim_id}.actor", task_id
                )
            )
        expires = _parse_timestamp(claim.get("expires_utc"))
        if expires is None or expires <= stamp:
            violations.append(
                InvariantViolation(
                    "claim_expired",
                    f"claims.{claim_id}.expires_utc",
                    "active claim is not live",
                )
            )
        targets = claim.get("targets")
        declared = task.get("claim_targets")
        if not isinstance(targets, list) or not targets:
            violations.append(
                InvariantViolation(
                    "claim_targets",
                    f"claims.{claim_id}.targets",
                    "active claim requires targets",
                )
            )
            targets = []
        if not isinstance(declared, list):
            declared = []
        claim_tokens = claim.get("fencing_tokens", {})
        if not isinstance(claim_tokens, Mapping):
            claim_tokens = {}
            violations.append(
                InvariantViolation(
                    "fencing_shape",
                    f"claims.{claim_id}.fencing_tokens",
                    "must be an object",
                )
            )
        for target in targets:
            normalized = _normalize_target(target)
            if not any(
                normalized == _normalize_target(scope)
                or normalized.startswith(_normalize_target(scope) + "/")
                for scope in declared
                if _normalize_target(scope)
            ):
                violations.append(
                    InvariantViolation(
                        "claim_scope", f"claims.{claim_id}.targets", normalized
                    )
                )
            token = claim_tokens.get(normalized)
            if not _valid_revision(token) or token != fencing.get(normalized):
                violations.append(
                    InvariantViolation(
                        "stale_fencing_token",
                        f"claims.{claim_id}.fencing_tokens.{normalized}",
                        f"claim={token!r}, current={fencing.get(normalized)!r}",
                    )
                )
    by_task: dict[str, list[str]] = defaultdict(list)
    for claim_id, claim in active_claims:
        if claim.get("mode") != "informational":
            by_task[str(claim.get("task_id"))].append(claim_id)
    for task_id, claim_ids in sorted(by_task.items()):
        if len(claim_ids) > 1:
            violations.append(
                InvariantViolation(
                    "exclusive_owner", f"tasks.{task_id}", ",".join(claim_ids)
                )
            )
    for index, (left_id, left) in enumerate(active_claims):
        for right_id, right in active_claims[index + 1 :]:
            if left.get("task_id") == right.get("task_id"):
                continue
            if (
                left.get("mode") == "informational"
                or right.get("mode") == "informational"
            ):
                continue
            if left.get("mode") == right.get("mode") == "shared":
                continue
            if any(
                _targets_overlap(left_target, right_target)
                for left_target in left.get("targets", ())
                for right_target in right.get("targets", ())
            ):
                violations.append(
                    InvariantViolation(
                        "claim_overlap",
                        "claims",
                        f"{left_id} conflicts with {right_id}",
                    )
                )
    active_by_task = {str(claim.get("task_id")) for _, claim in active_claims}
    for task_id, task in tasks.items():
        status = task.get("status")
        if (
            status in {"claimed", "in_progress", "waiting", "blocked", "completed"}
            and task_id not in active_by_task
        ):
            violations.append(
                InvariantViolation(
                    "task_claim_missing", f"tasks.{task_id}.status", str(status)
                )
            )
        if (
            status in {"planned", "ready", "released", "reconciled"}
            and task_id in active_by_task
        ):
            violations.append(
                InvariantViolation(
                    "task_claim_illegal", f"tasks.{task_id}.status", str(status)
                )
            )

    memory = candidate.get("memory")
    if not isinstance(memory, Mapping):
        violations.append(
            InvariantViolation("memory_shape", "memory", "must be an object")
        )
        memory = {}
    for field in _MEMORY_COUNTERS.values():
        if not _valid_revision(memory.get(field)):
            violations.append(
                InvariantViolation(
                    "memory_counter", f"memory.{field}", "must be a nonnegative integer"
                )
            )
    if observed_memory_counts is not None:
        for layer, field in _MEMORY_COUNTERS.items():
            observed = observed_memory_counts.get(layer)
            if observed is None or memory.get(field) != observed:
                violations.append(
                    InvariantViolation(
                        "memory_counter_drift",
                        f"memory.{field}",
                        f"declared={memory.get(field)!r}, observed={observed!r}",
                    )
                )

    if previous_state is not None:
        _check_transitions(previous_state, candidate, violations)
    if event is not None:
        before_hash = (
            previous_state.get("state_hash") if previous_state is not None else None
        )
        if event.get("before_hash") != before_hash:
            violations.append(
                InvariantViolation(
                    "event_before_hash",
                    "event.before_hash",
                    f"expected {before_hash!r}",
                )
            )
        if event.get("after_hash") != candidate.get("state_hash"):
            violations.append(
                InvariantViolation(
                    "event_after_hash",
                    "event.after_hash",
                    "must equal candidate state hash",
                )
            )
        event_digest = event.get("event_sha256")
        try:
            expected_event_digest = _stable_hash(_without_digest(event, "event_sha256"))
        except (TypeError, ValueError):
            expected_event_digest = None
        if not _is_digest(event_digest) or event_digest != expected_event_digest:
            violations.append(
                InvariantViolation(
                    "event_digest", "event.event_sha256", "digest does not seal event"
                )
            )
    ordered = sorted(set(violations))
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "valid": not ordered,
        "state_revision": revision,
        "checks": [
            "coordination",
            "claims",
            "fencing",
            "dag",
            "budget",
            "revision",
            "event_ancestry",
            "memory",
        ],
        "violations": [item.as_dict() for item in ordered],
    }


def assert_coordination_state(
    state: object,
    **kwargs: object,
) -> dict[str, object]:
    report = validate_coordination_state(state, **kwargs)
    if not report["valid"]:
        raise StateInvariantError(report)
    return report


def _read_jsonl(
    path: Path, *, maximum_bytes: int, maximum_records: int
) -> list[dict[str, object]]:
    if not path.exists():
        return []
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError(f"bounded JSONL input rejected: {path}")
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        if len(records) >= maximum_records:
            raise ValueError(f"JSONL record limit exceeded: {path}")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed JSONL at {path}:{line_number}") from error
        if not isinstance(record, dict):
            raise ValueError(f"JSONL record is not an object at {path}:{line_number}")
        records.append(record)
    return records


def _event_chain_violations(
    events: Sequence[Mapping[str, object]], state: Mapping[str, object]
) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    previous_digest: str | None = None
    previous_after: object = None
    for index, event in enumerate(events):
        path = f"events[{index}]"
        digest = event.get("event_sha256")
        try:
            expected_digest = _stable_hash(_without_digest(event, "event_sha256"))
        except (TypeError, ValueError):
            expected_digest = None
        if not _is_digest(digest) or digest != expected_digest:
            violations.append(
                InvariantViolation(
                    "event_digest", f"{path}.event_sha256", "invalid seal"
                )
            )
        if event.get("previous_event_sha256") != previous_digest:
            violations.append(
                InvariantViolation(
                    "event_ancestry",
                    f"{path}.previous_event_sha256",
                    f"expected {previous_digest!r}",
                )
            )
        if index and event.get("before_hash") != previous_after:
            violations.append(
                InvariantViolation(
                    "event_state_chain",
                    f"{path}.before_hash",
                    f"expected {previous_after!r}",
                )
            )
        previous_digest = str(digest) if _is_digest(digest) else None
        previous_after = event.get("after_hash")
    if events and events[-1].get("after_hash") != state.get("state_hash"):
        violations.append(
            InvariantViolation(
                "event_state_head", "events[-1].after_hash", "does not equal state hash"
            )
        )
    if state.get("revision") != len(events):
        violations.append(
            InvariantViolation(
                "event_revision_count",
                "events",
                f"state revision={state.get('revision')!r}, events={len(events)}",
            )
        )
    project = state.get("project", {})
    project_id = project.get("id") if isinstance(project, Mapping) else None
    for index, event in enumerate(events):
        if event.get("project_id") != project_id:
            violations.append(
                InvariantViolation(
                    "event_project",
                    f"events[{index}].project_id",
                    f"expected {project_id!r}",
                )
            )
    return violations


def _read_memory_records(
    coordination_root: Path, project_id: str
) -> tuple[dict[str, int], list[InvariantViolation]]:
    memory_root = coordination_root / "memory"
    specifications = [
        ("project", memory_root / "project.jsonl"),
        ("state", memory_root / "state.jsonl"),
        ("system_candidate", memory_root / "system-candidates.jsonl"),
    ]
    sessions = memory_root / "sessions"
    if sessions.is_dir():
        specifications.extend(
            ("session", path) for path in sorted(sessions.glob("*.jsonl"))
        )
    total_bytes = sum(
        path.stat().st_size for _, path in specifications if path.is_file()
    )
    if total_bytes > MAX_MEMORY_BYTES:
        raise ValueError("coordination memory exceeds startup byte budget")
    counts = {layer: 0 for layer in _MEMORY_COUNTERS}
    violations: list[InvariantViolation] = []
    revisions: dict[str, list[int]] = defaultdict(list)
    for layer, path in specifications:
        for index, record in enumerate(
            _read_jsonl(
                path, maximum_bytes=MAX_MEMORY_BYTES, maximum_records=MAX_MEMORY_RECORDS
            )
        ):
            counts[layer] += 1
            locator = f"memory.{layer}[{index}]"
            if record.get("project_id") != project_id:
                violations.append(
                    InvariantViolation(
                        "memory_project", locator, "cross-project record"
                    )
                )
            if record.get("layer") != layer:
                violations.append(
                    InvariantViolation("memory_layer", locator, "record/file mismatch")
                )
            memory_id = _identifier(record.get("memory_id"))
            revision = record.get("revision")
            if (
                not memory_id
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 1
            ):
                violations.append(
                    InvariantViolation(
                        "memory_revision",
                        locator,
                        "identity and positive revision required",
                    )
                )
            else:
                revisions[memory_id].append(revision)
            digest = record.get("record_sha256")
            try:
                expected_digest = _stable_hash(_without_digest(record, "record_sha256"))
            except (TypeError, ValueError):
                expected_digest = None
            if digest is not None and (
                not _is_digest(digest) or digest != expected_digest
            ):
                violations.append(
                    InvariantViolation("memory_digest", locator, "invalid record seal")
                )
    for memory_id, observed in revisions.items():
        ordered = sorted(observed)
        if ordered != list(range(1, len(ordered) + 1)):
            violations.append(
                InvariantViolation(
                    "memory_revision_chain", f"memory.{memory_id}", repr(ordered)
                )
            )
    return counts, violations


def validate_coordination_startup(project_root: Path) -> dict[str, object]:
    """Audit retained coordination authority without repairing or rewriting it."""
    project = project_root.resolve()
    coordination_root = project / ".engineering-bootstrap" / "coordination"
    state_path = coordination_root / "state.json"
    if not state_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": "startup",
            "valid": True,
            "configured": False,
            "state_revision": None,
            "checks": [],
            "violations": [],
        }
    if not state_path.is_file() or state_path.stat().st_size > 8 * 1024 * 1024:
        raise StateInvariantError(
            {
                "schema_version": SCHEMA_VERSION,
                "phase": "startup",
                "valid": False,
                "violations": [
                    InvariantViolation(
                        "state_input", "state.json", "unreadable or oversized"
                    ).as_dict()
                ],
            }
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state is not an object")
        state_project = state.get("project")
        if (
            not isinstance(state_project, Mapping)
            or Path(str(state_project.get("root", ""))).resolve() != project
        ):
            raise ValueError("coordination state project root mismatch")
        project_id = str(state.get("project", {}).get("id", ""))
        memory_counts, memory_violations = _read_memory_records(
            coordination_root, project_id
        )
        events = _read_jsonl(
            coordination_root / "events.jsonl",
            maximum_bytes=MAX_EVENT_BYTES,
            maximum_records=MAX_EVENTS,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise StateInvariantError(
            {
                "schema_version": SCHEMA_VERSION,
                "phase": "startup",
                "valid": False,
                "violations": [
                    InvariantViolation(
                        "startup_input", "coordination", str(error)
                    ).as_dict()
                ],
            }
        ) from error
    report = validate_coordination_state(
        state,
        observed_memory_counts=memory_counts,
        phase="startup",
    )
    extra = _event_chain_violations(events, state) + memory_violations
    violations = sorted(
        {
            InvariantViolation(
                str(item["code"]), str(item["path"]), str(item["detail"])
            )
            for item in report["violations"]
            if isinstance(item, Mapping)
        }
        | set(extra)
    )
    report["valid"] = not violations
    report["configured"] = True
    report["event_count"] = len(events)
    report["observed_memory_counts"] = memory_counts
    report["violations"] = [item.as_dict() for item in violations]
    return report


def assert_coordination_startup(project_root: Path) -> dict[str, object]:
    report = validate_coordination_startup(project_root)
    if not report["valid"]:
        raise StateInvariantError(report)
    return report


class CoordinationPreCommitGuard:
    """JsonWal validator that prevents an invalid coordination publication."""

    def __init__(self, coordination_root: Path) -> None:
        self.coordination_root = coordination_root.resolve()

    def __call__(self, transitions: tuple[JsonTransition, ...]) -> None:
        state_path = self.coordination_root / "state.json"
        state_transitions = [item for item in transitions if item.path == state_path]
        events = [item.after for item in transitions if item.role == "event"]
        roles = {item.role for item in transitions}
        if len(state_transitions) != 1 or len(events) != 1:
            raise StateInvariantError(
                {
                    "schema_version": SCHEMA_VERSION,
                    "phase": "precommit",
                    "valid": False,
                    "violations": [
                        InvariantViolation(
                            "transaction_shape",
                            "artifacts",
                            "exactly one coordination state and event are required",
                        ).as_dict()
                    ],
                }
            )
        missing_roles = {"state", "event", "receipt", "handoff"} - roles
        if missing_roles:
            raise StateInvariantError(
                {
                    "schema_version": SCHEMA_VERSION,
                    "phase": "precommit",
                    "valid": False,
                    "violations": [
                        InvariantViolation(
                            "transaction_roles",
                            "artifacts",
                            f"missing {sorted(missing_roles)}",
                        ).as_dict()
                    ],
                }
            )
        transition = state_transitions[0]
        if (
            not isinstance(transition.before, Mapping)
            or not isinstance(transition.after, Mapping)
            or not isinstance(events[0], Mapping)
        ):
            raise StateInvariantError(
                {
                    "schema_version": SCHEMA_VERSION,
                    "phase": "precommit",
                    "valid": False,
                    "violations": [
                        InvariantViolation(
                            "transaction_shape",
                            "artifacts",
                            "state and event must be objects",
                        ).as_dict()
                    ],
                }
            )
        assert_coordination_state(
            transition.after,
            previous_state=transition.before,
            event=events[0],
            phase="precommit",
        )
