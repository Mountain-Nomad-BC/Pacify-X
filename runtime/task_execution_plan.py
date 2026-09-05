"""Immutable, descriptive execution plans compiled from canonical routing.

This module may compile, validate, and persist plans. It deliberately contains
no task, provider, agent, process, or effect execution path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = "px.task-execution-plan/1.0"
PLAN_DIRECTORY = Path(".engineering-bootstrap/task-plans")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _pairs(value: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


def _utc(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


@dataclass(frozen=True, slots=True)
class TaskExecutionPlan:
    schema_version: str
    plan_id: str
    project_id: str
    source_revision: str
    created_utc: str
    task_envelope_sha256: str
    route_receipt_sha256: str
    package_id: str
    package_receipt_sha256: str
    projection_revisions: tuple[tuple[str, str], ...]
    selected_capabilities: tuple[str, ...]
    effect_budget: tuple[str, ...]
    authority_bindings: tuple[str, ...]
    attachments: tuple[tuple[str, str], ...]
    model_attachment: Mapping[str, object] | None
    model_ranking_receipt: Mapping[str, object] | None
    plan_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "source_revision": self.source_revision,
            "created_utc": self.created_utc,
            "task_envelope_sha256": self.task_envelope_sha256,
            "route_receipt_sha256": self.route_receipt_sha256,
            "package_id": self.package_id,
            "package_receipt_sha256": self.package_receipt_sha256,
            "projection_revisions": dict(self.projection_revisions),
            "selected_capabilities": list(self.selected_capabilities),
            "effect_budget": list(self.effect_budget),
            "authority_bindings": list(self.authority_bindings),
            "attachments": dict(self.attachments),
            "model_attachment": dict(self.model_attachment) if self.model_attachment else None,
            "model_ranking_receipt": dict(self.model_ranking_receipt) if self.model_ranking_receipt else None,
            "plan_sha256": self.plan_sha256,
        }


def _unsigned(plan: TaskExecutionPlan | Mapping[str, object]) -> dict[str, object]:
    payload = plan.as_dict() if isinstance(plan, TaskExecutionPlan) else dict(plan)
    payload.pop("plan_sha256", None)
    return payload


def compile_task_execution_plan(
    route: object,
    *,
    project_id: str,
    source_revision: str,
    projection_revisions: Mapping[str, object],
    effect_budget: Sequence[str],
    authority_bindings: Sequence[str],
    attachments: Mapping[str, object] | None = None,
    model_attachment: Mapping[str, object] | None = None,
    model_ranking_receipt: Mapping[str, object] | None = None,
    created_utc: str | None = None,
) -> TaskExecutionPlan:
    """Compile router output into a hash-bound description without executing it."""
    envelope = getattr(route, "envelope", None)
    package = getattr(route, "package", None)
    if envelope is None or package is None:
        raise TypeError("route must provide canonical envelope and package objects")
    timestamp = created_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(project_id),
        "source_revision": str(source_revision),
        "created_utc": timestamp,
        "task_envelope_sha256": str(envelope.task_envelope_sha256),
        "route_receipt_sha256": str(getattr(route, "receipt_sha256", "")),
        "package_id": str(package.package_id),
        "package_receipt_sha256": str(package.receipt_sha256),
        "projection_revisions": dict(_pairs(projection_revisions)),
        "selected_capabilities": sorted(set(map(str, package.selected))),
        "effect_budget": sorted(set(map(str, effect_budget))),
        "authority_bindings": sorted(set(map(str, authority_bindings))),
        "attachments": dict(_pairs(attachments)),
        "model_attachment": dict(model_attachment) if model_attachment else None,
        "model_ranking_receipt": dict(model_ranking_receipt) if model_ranking_receipt else None,
    }
    content_sha256 = _digest(base)
    base["plan_id"] = f"task-plan-{content_sha256[:24]}"
    base["plan_sha256"] = _digest(base)
    plan = task_execution_plan_from_dict(base)
    report = validate_task_execution_plan(plan)
    if not report["valid"]:
        raise ValueError("invalid task execution plan: " + "; ".join(report["errors"]))
    return plan


def task_execution_plan_from_dict(payload: Mapping[str, object]) -> TaskExecutionPlan:
    def strings(key: str) -> tuple[str, ...]:
        value = payload.get(key, ())
        return tuple(map(str, value)) if isinstance(value, (list, tuple)) else ()

    def pairs(key: str) -> tuple[tuple[str, str], ...]:
        value = payload.get(key, {})
        return _pairs(value if isinstance(value, Mapping) else None)

    return TaskExecutionPlan(
        schema_version=str(payload.get("schema_version", "")),
        plan_id=str(payload.get("plan_id", "")),
        project_id=str(payload.get("project_id", "")),
        source_revision=str(payload.get("source_revision", "")),
        created_utc=str(payload.get("created_utc", "")),
        task_envelope_sha256=str(payload.get("task_envelope_sha256", "")),
        route_receipt_sha256=str(payload.get("route_receipt_sha256", "")),
        package_id=str(payload.get("package_id", "")),
        package_receipt_sha256=str(payload.get("package_receipt_sha256", "")),
        projection_revisions=pairs("projection_revisions"),
        selected_capabilities=strings("selected_capabilities"),
        effect_budget=strings("effect_budget"),
        authority_bindings=strings("authority_bindings"),
        attachments=pairs("attachments"),
        model_attachment=(
            dict(payload["model_attachment"])
            if isinstance(payload.get("model_attachment"), Mapping)
            else None
        ),
        model_ranking_receipt=(
            dict(payload["model_ranking_receipt"])
            if isinstance(payload.get("model_ranking_receipt"), Mapping)
            else None
        ),
        plan_sha256=str(payload.get("plan_sha256", "")),
    )


def validate_task_execution_plan(
    plan: TaskExecutionPlan | Mapping[str, object],
    *,
    current_source_revision: str | None = None,
    current_projection_revisions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Validate identity, required authority/effect bindings, and freshness."""
    candidate = plan if isinstance(plan, TaskExecutionPlan) else task_execution_plan_from_dict(plan)
    payload = candidate.as_dict()
    errors: list[str] = []
    if candidate.schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("plan_id", "project_id", "source_revision", "package_id"):
        if not payload[field]:
            errors.append(f"{field} must be non-empty")
    for field in (
        "task_envelope_sha256",
        "route_receipt_sha256",
        "package_receipt_sha256",
        "plan_sha256",
    ):
        value = str(payload[field])
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            errors.append(f"{field} must be a lowercase sha256")
    if not _utc(candidate.created_utc):
        errors.append("created_utc must be an aware UTC timestamp")
    if not candidate.projection_revisions:
        errors.append("at least one projection revision is required")
    if not candidate.effect_budget:
        errors.append("effect budget is required")
    if not candidate.authority_bindings:
        errors.append("authority binding is required")
    if bool(candidate.model_attachment) != bool(candidate.model_ranking_receipt):
        errors.append("model attachment and ranking receipt must be bound together")
    if candidate.model_attachment and candidate.model_ranking_receipt:
        attachment_sha = str(candidate.model_attachment.get("attachment_sha256", ""))
        if candidate.model_ranking_receipt.get("selected_attachment_sha256") != attachment_sha:
            errors.append("model ranking receipt does not bind selected attachment")
    for field in (
        "projection_revisions",
        "selected_capabilities",
        "effect_budget",
        "authority_bindings",
        "attachments",
    ):
        value = getattr(candidate, field)
        if tuple(sorted(set(value))) != value:
            errors.append(f"{field} must be sorted and unique")
    expected_plan_id = f"task-plan-{_digest({key: value for key, value in _unsigned(candidate).items() if key != 'plan_id'})[:24]}"
    if candidate.plan_id != expected_plan_id:
        errors.append("plan_id does not match canonical plan content")
    if candidate.plan_sha256 != _digest(_unsigned(candidate)):
        errors.append("plan_sha256 does not match canonical plan content")
    if current_source_revision is not None and candidate.source_revision != current_source_revision:
        errors.append("task plan source revision is stale")
    if current_projection_revisions is not None:
        current = _pairs(current_projection_revisions)
        if candidate.projection_revisions != current:
            errors.append("task plan projection revision is stale")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "plan_id": candidate.plan_id,
        "plan_sha256": candidate.plan_sha256,
        "errors": errors,
    }


def persist_task_execution_plan(root: Path, plan: TaskExecutionPlan) -> Path:
    """Persist one immutable plan, refusing any identity collision."""
    report = validate_task_execution_plan(plan)
    if not report["valid"]:
        raise ValueError("invalid task execution plan: " + "; ".join(report["errors"]))
    directory = root.resolve() / PLAN_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{plan.plan_id}.json"
    encoded = json.dumps(plan.as_dict(), indent=2, sort_keys=True).encode("utf-8") + b"\n"
    try:
        with target.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        if target.read_bytes() != encoded:
            raise FileExistsError(f"immutable task plan collision: {target}") from None
    return target
