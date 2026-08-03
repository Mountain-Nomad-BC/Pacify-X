"""Auditable stage routing for the evidence-first engineering lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .project_management import validate_project_management
from .registry import validate_registry


def lifecycle_status(framework_root: Path, project: Path) -> dict[str, Any]:
    graph = json.loads((framework_root / "registry" / "engineering_lifecycle.json").read_text(encoding="utf-8"))
    project = project.resolve()
    registry = validate_registry(framework_root)
    checks: list[dict[str, Any]] = []
    checks.append({"stage": "environment-discovery", "complete": registry["valid"], "blockers": registry["errors"]})
    state_path = project / ".engineering-bootstrap" / "project-management" / "state.json"
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            state = {"_error": str(error)}
    pm_errors = validate_project_management(project) if project.is_dir() else ["project root does not exist"]
    checks.append({"stage": "project-commissioning", "complete": not pm_errors, "blockers": pm_errors})
    tool_records = state.get("evidence", {}).get("tool_intake_records", []) if state else []
    checks.append({
        "stage": "tool-and-package-admission", "complete": bool(tool_records),
        "blockers": [] if tool_records else ["no project-scoped tool/package admission record; stage may be skipped only by an explicit no-tools decision"],
    })
    work = state.get("work", {}) if state else {}
    governance = state.get("governance", {}) if state else {}
    planned = bool(work.get("objective")) and bool(work.get("milestones") or work.get("backlog")) and not governance.get("pending_approvals")
    checks.append({
        "stage": "architecture-and-planning", "complete": planned,
        "blockers": [] if planned else ["objective, bounded work plan, and approval disposition are not complete"],
    })
    checkpoint = state.get("checkpoint", {}) if state else {}
    implementation = bool(checkpoint.get("changed_file_sha256"))
    checks.append({
        "stage": "bounded-implementation", "complete": implementation,
        "blockers": [] if implementation else ["no checkpointed implementation change set"],
    })
    validation = checkpoint.get("validation", {}) if checkpoint else {}
    verified = validation.get("tests") not in (None, "not_run") and validation.get("verifier") not in (None, "not_run", "incomplete")
    checks.append({
        "stage": "verification-and-repair", "complete": verified,
        "blockers": [] if verified else ["current test and independent-verifier evidence are required"],
    })
    evidence = state.get("evidence", {}) if state else {}
    ready = bool(evidence.get("validation_receipt")) and verified
    checks.append({
        "stage": "deployment-readiness", "complete": ready,
        "blockers": [] if ready else ["installed-artifact, package, sanitation, rollback, and acceptance receipt is missing"],
    })
    process_records = evidence.get("process_records", []) if evidence else []
    checks.append({
        "stage": "process-capture-and-skill-candidate", "complete": bool(process_records),
        "blockers": [] if process_records else ["no verified engineering process record and candidate disposition"],
    })
    stage_by_id = {item["id"]: item for item in graph["stages"]}
    next_stage = next((item["stage"] for item in checks if not item["complete"]), None)
    return {
        "valid": registry["valid"] and not state.get("_error"),
        "lifecycle": graph["id"],
        "complete": next_stage is None,
        "next_stage": next_stage,
        "next_stage_contract": stage_by_id.get(next_stage),
        "checks": checks,
        "invariants": graph["invariants"],
        "metadata_only": True,
    }
