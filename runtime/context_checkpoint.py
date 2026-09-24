"""Durable context-pressure checkpoint contract for PX model sessions.

Model context/KV state is treated as an execution cache. A caller may compact or
handoff only after a validated checkpoint has been persisted and its cognitive
publication receipt has succeeded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_ITEMS_PER_FIELD = 128


def _stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PressurePolicy:
    soft_fraction: float = 0.70
    checkpoint_fraction: float = 0.82
    hard_fraction: float = 0.90

    def __post_init__(self) -> None:
        if not (0.0 < self.soft_fraction < self.checkpoint_fraction < self.hard_fraction < 1.0):
            raise ValueError("pressure thresholds must be increasing fractions below 1")


def pressure_action(used_tokens: int, context_tokens: int, policy: PressurePolicy = PressurePolicy()) -> str:
    if not isinstance(used_tokens, int) or not isinstance(context_tokens, int) or used_tokens < 0 or context_tokens <= 0:
        raise ValueError("invalid token usage")
    fraction = min(1.0, used_tokens / context_tokens)
    if fraction >= policy.hard_fraction:
        return "hard-checkpoint-and-block-bulk-hydration"
    if fraction >= policy.checkpoint_fraction:
        return "checkpoint-required-before-bulk-hydration"
    if fraction >= policy.soft_fraction:
        return "soft-compaction-checkpoint-consideration"
    return "none"


def _items(values: Sequence[Mapping[str, Any]] | None, name: str) -> list[dict[str, Any]]:
    rows = list(values or ())
    if len(rows) > MAX_ITEMS_PER_FIELD:
        raise ValueError(f"checkpoint {name} exceeds item bound")
    result: list[dict[str, Any]] = []
    for value in rows:
        if not isinstance(value, Mapping):
            raise ValueError(f"checkpoint {name} entries must be mappings")
        result.append(dict(value))
    return result


def _refs(values: Sequence[str] | None, name: str) -> list[str]:
    rows = [str(item).strip() for item in (values or ()) if str(item).strip()]
    if len(rows) > MAX_ITEMS_PER_FIELD or any(len(item.encode("utf-8")) > 2048 for item in rows):
        raise ValueError(f"checkpoint {name} exceeds bound")
    return rows


def build_checkpoint(
    *,
    project_id: str,
    session_id: str,
    task_id: str | None,
    model_route: str,
    reason: str,
    decisions: Sequence[Mapping[str, Any]] | None = None,
    facts: Sequence[Mapping[str, Any]] | None = None,
    constraints: Sequence[Mapping[str, Any]] | None = None,
    goals: Sequence[Mapping[str, Any]] | None = None,
    open_actions: Sequence[Mapping[str, Any]] | None = None,
    open_loops: Sequence[Mapping[str, Any]] | None = None,
    skills_used_or_learned: Sequence[Mapping[str, Any]] | None = None,
    workflow_orchestration_state: Sequence[Mapping[str, Any]] | None = None,
    failures_and_recovery: Sequence[Mapping[str, Any]] | None = None,
    artifact_refs: Sequence[str] | None = None,
    evidence_refs: Sequence[str] | None = None,
    uncertainties: Sequence[Mapping[str, Any]] | None = None,
    exact_next_action: str = "",
    source_usage: Mapping[str, Any] | None = None,
    source_identity: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    required = {"project_id": project_id, "session_id": session_id, "model_route": model_route, "reason": reason}
    if any(not str(value).strip() for value in required.values()):
        raise ValueError("project/session/model/reason are required")
    if len(str(exact_next_action).encode("utf-8")) > 4000:
        raise ValueError("exact_next_action too large")
    created = datetime.now(timezone.utc).isoformat()
    content = {
        "project_id": str(project_id), "session_id": str(session_id), "task_id": str(task_id) if task_id else None,
        "model_route": str(model_route), "reason": str(reason),
        "decisions": _items(decisions, "decisions"), "facts": _items(facts, "facts"),
        "constraints": _items(constraints, "constraints"), "goals": _items(goals, "goals"),
        "open_actions": _items(open_actions, "open_actions"), "open_loops": _items(open_loops, "open_loops"),
        "skills_used_or_learned": _items(skills_used_or_learned, "skills"),
        "workflow_orchestration_state": _items(workflow_orchestration_state, "workflow state"),
        "failures_and_recovery": _items(failures_and_recovery, "failures"),
        "artifact_refs": _refs(artifact_refs, "artifact refs"), "evidence_refs": _refs(evidence_refs, "evidence refs"),
        "uncertainties": _items(uncertainties, "uncertainties"), "exact_next_action": str(exact_next_action),
        "source_usage": dict(source_usage or {}), "source_identity": dict(source_identity or {}), "created_utc": created,
    }
    checkpoint_id = f"ctx-{_stable(content)[:32]}"
    packet = {"schema_version": "px.context-checkpoint/1.0", "checkpoint_id": checkpoint_id, **content, "authority_granted": False}
    if len(json.dumps(packet, ensure_ascii=False, default=str).encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint exceeds 256 KiB bound")
    packet["checkpoint_sha256"] = _stable(packet)
    return packet


def persist_and_publish_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    persist: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    publish: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, object]:
    if checkpoint.get("schema_version") != "px.context-checkpoint/1.0":
        raise ValueError("unsupported checkpoint schema")
    expected = str(checkpoint.get("checkpoint_sha256") or "")
    base = dict(checkpoint)
    base.pop("checkpoint_sha256", None)
    if expected != _stable(base):
        raise ValueError("checkpoint seal mismatch")
    storage_receipt = dict(persist(checkpoint))
    if not storage_receipt:
        raise RuntimeError("checkpoint persistence returned no receipt")
    generation_receipt = dict(publish(checkpoint, storage_receipt))
    if not generation_receipt:
        raise RuntimeError("checkpoint publication returned no receipt")
    return {
        "schema_version": "px.context-checkpoint-publication/1.0",
        "checkpoint_id": checkpoint["checkpoint_id"],
        "storage_receipt": storage_receipt,
        "generation_receipt": generation_receipt,
        "compaction_permitted": True,
        "bulk_hydration_permitted": True,
        "receipt_sha256": _stable({"checkpoint": checkpoint["checkpoint_id"], "storage": storage_receipt, "generation": generation_receipt}),
    }
