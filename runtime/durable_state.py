"""Acceptance-backed durable goals and specification-lifecycle closure."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


GOAL_STATES = frozenset({"planned", "in_progress", "paused", "blocked", "complete"})
SPECIFICATION_STAGES = (
    "principles",
    "specification",
    "clarification",
    "design",
    "tasks",
    "implementation_evidence",
    "acceptance",
)


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def transition_durable_goal(
    state: Mapping[str, object],
    event: str,
    *,
    project_id: str,
    session_id: str,
    evidence_ids: Sequence[str] = (),
    acceptance_results: Mapping[str, bool] | None = None,
    blocker: str | None = None,
    continuation_cost: int = 0,
) -> dict[str, object]:
    """Apply one deterministic goal transition with strict completion semantics."""
    current = str(state.get("status", "planned"))
    if current not in GOAL_STATES:
        raise ValueError("unknown goal state")
    if state.get("project_id") not in {None, project_id}:
        raise ValueError("goal transition crosses project boundary")
    if continuation_cost < 0:
        raise ValueError("continuation cost cannot be negative")
    budget = int(state.get("continuation_budget", 0))
    remaining = budget - continuation_cost
    errors: list[str] = []
    target = current
    history = [
        dict(item) for item in state.get("history", ()) if isinstance(item, Mapping)
    ]
    acceptance = dict(acceptance_results or {})
    evidence = tuple(sorted(set(map(str, evidence_ids))))

    if event == "start":
        if current not in {"planned", "paused", "blocked"}:
            errors.append("goal cannot start from current state")
        elif current == "paused" and state.get("paused_session_id") not in {
            None,
            session_id,
        }:
            errors.append("paused goal belongs to another session")
        else:
            target = "in_progress"
    elif event == "pause":
        if current != "in_progress":
            errors.append("only an in-progress goal may pause")
        else:
            target = "paused"
    elif event == "block":
        blocker_text = str(blocker or "").strip()
        repeated = 1
        for item in reversed(history):
            if item.get("event") == "block" and item.get("blocker") == blocker_text:
                repeated += 1
            else:
                break
        if not blocker_text:
            errors.append("blocked transition requires a blocker")
        elif repeated < 3:
            errors.append(
                "blocked semantics require three consecutive matching observations"
            )
        else:
            target = "blocked"
    elif event == "complete":
        if not acceptance or not all(acceptance.values()):
            errors.append("all acceptance criteria must pass")
        if not evidence:
            errors.append("completion evidence is required")
        if not errors:
            target = "complete"
    elif event == "continue":
        if current != "in_progress":
            errors.append("only an in-progress goal may continue")
        if continuation_cost < 1:
            errors.append("continuation must spend a positive bounded unit")
        if remaining < 0:
            errors.append("continuation budget exhausted")
    else:
        raise ValueError("unsupported goal event")

    applied = not errors
    if applied:
        history.append(
            {
                "event": event,
                "from": current,
                "to": target,
                "session_id": session_id,
                "blocker": blocker,
                "evidence_ids": list(evidence),
                "acceptance": acceptance,
            }
        )
    result = {
        "schema_version": "1.0",
        "goal_id": str(state.get("goal_id", "")),
        "project_id": project_id,
        "status": target if applied else current,
        "continuation_budget": remaining if applied else budget,
        "paused_session_id": session_id
        if applied and event == "pause"
        else state.get("paused_session_id"),
        "history": history,
        "event_applied": applied,
        "errors": errors,
        "authority_granted": False,
    }
    result["state_sha256"] = _stable(result)
    return result


def close_specification_lifecycle(
    artifacts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Verify stage continuity, task coverage, evidence, and acceptance."""
    by_id: dict[str, Mapping[str, object]] = {}
    stage_records = {stage: [] for stage in SPECIFICATION_STAGES}
    errors: list[str] = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("id", "")).strip()
        stage = str(artifact.get("stage", "")).strip()
        if not artifact_id or artifact_id in by_id:
            raise ValueError("artifact IDs must be non-empty and unique")
        if stage not in stage_records:
            raise ValueError(f"unsupported specification stage: {stage}")
        by_id[artifact_id] = artifact
        stage_records[stage].append(artifact)

    missing_stages = [stage for stage, records in stage_records.items() if not records]
    if missing_stages:
        errors.append(f"missing stages: {missing_stages}")
    stage_index = {stage: index for index, stage in enumerate(SPECIFICATION_STAGES)}
    referenced: set[str] = set()
    for artifact_id, artifact in by_id.items():
        current_stage = str(artifact["stage"])
        dependencies = tuple(map(str, artifact.get("depends_on", ())))
        if current_stage != "principles" and not dependencies:
            errors.append(f"{artifact_id}: non-principle artifact is orphaned")
        for dependency in dependencies:
            referenced.add(dependency)
            target = by_id.get(dependency)
            if target is None:
                errors.append(f"{artifact_id}: unresolved dependency {dependency}")
            elif stage_index[str(target["stage"])] >= stage_index[current_stage]:
                errors.append(f"{artifact_id}: dependency is not from an earlier stage")
        if current_stage == "implementation_evidence" and not artifact.get(
            "evidence_sha256"
        ):
            errors.append(f"{artifact_id}: implementation evidence hash missing")
        if current_stage == "acceptance" and artifact.get("passed") is not True:
            errors.append(f"{artifact_id}: acceptance did not pass")
    task_ids = {
        identifier
        for identifier, artifact in by_id.items()
        if artifact["stage"] == "tasks"
    }
    evidenced_tasks = {
        dependency
        for artifact in stage_records["implementation_evidence"]
        for dependency in map(str, artifact.get("depends_on", ()))
    }
    orphan_tasks = sorted(task_ids - evidenced_tasks)
    if orphan_tasks:
        errors.append(f"tasks without implementation evidence: {orphan_tasks}")
    result = {
        "valid": not errors,
        "closed": not errors,
        "stage_counts": {
            stage: len(records) for stage, records in stage_records.items()
        },
        "missing_stages": missing_stages,
        "orphan_tasks": orphan_tasks,
        "errors": errors,
        "artifact_count": len(artifacts),
        "authority_granted": False,
    }
    result["closure_sha256"] = _stable(result)
    return result
