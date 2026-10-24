"""Reference-only ingress for canonical persisted prepared groups.

The browser selects an immutable plan identity, never placements, permissions,
approval, process custody or model branches. Inspection grants no execution.
"""
from pathlib import Path
import re

from .archive_io import reject_path_links
from .json_io import load_json_object
from .task_execution_plan import (
    PLAN_DIRECTORY, task_execution_plan_from_dict, validate_task_execution_plan,
)


def resolve_prepared_group(root: Path, request: dict):
    if type(request) is not dict or set(request) != {"schema_version", "plan_id", "plan_sha256"}:
        raise ValueError("exact prepared-group reference required")
    if request["schema_version"] != "px.prepared-group-reference/1.0":
        raise ValueError("unsupported prepared-group reference")
    identity, expected = request["plan_id"], request["plan_sha256"]
    if type(identity) is not str or re.fullmatch(r"task-plan-[0-9a-f]{24}", identity) is None:
        raise ValueError("canonical task-plan identity required")
    if type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("exact task-plan digest required")
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    path = root / PLAN_DIRECTORY / (identity + ".json")
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=4 * 1024 * 1024)
    plan = task_execution_plan_from_dict(payload)
    if plan.plan_id != identity or plan.plan_sha256 != expected:
        raise ValueError("persisted task-plan reference differs")
    if not validate_task_execution_plan(plan)["valid"]:
        raise ValueError("persisted task-plan integrity is invalid")
    if plan.model_execution_group is None or plan.model_group_preparation is None or plan.context_generation is None:
        raise ValueError("persisted group requires preparation and generation binding")
    from .model_group_preparation import read_group_preparation
    read_group_preparation(plan.model_group_preparation.as_dict(), plan.model_execution_group, root=root)
    return plan


def inspect_prepared_group(root: Path, request: dict) -> dict:
    plan = resolve_prepared_group(root, request)
    return {"schema_version": "px.prepared-group-inspection/1.0",
            "plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256,
            "project_id": plan.project_id, "group_sha256": plan.model_execution_group.group_sha256,
            "members": [{"model_id": branch.model_id, "role": branch.role,
                         "agent_generation_id": branch.agent_generation_id}
                        for branch in plan.model_execution_group.branches],
            "status": "PREPARED_NOT_ADMITTED", "generation_currentness_checked": False,
            "execution_authorized": False, "authority_granted": False,
            "required_host_bindings": ["current-generation", "exact-placements", "host-consumed-approval",
                "commissioned-gremlin", "supervisor-pre-release-custody", "provider-policy-and-adapters",
                "trusted-evidence"]}
