"""Executable, checkpointed routing for admitted project-stream composite workflows."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping

from .knowledge_foundry import SourceArtifact, compile_foundry_bundle, evolution_recommendations
from .memory_fabric import MemoryRecord
from .memory_vault import MemoryVault
from .project_control_plane import (
    dispatch_workstreams,
    evaluate_resilience,
    guarded_change as apply_guarded_change,
    import_transfer,
    project_health,
    promote_capability,
    quarantine_candidates,
    record_project_transition,
    register_agent,
    register_existing_project,
    recover_incident,
    switch_project,
)
from .project_stream_controls import ScopeEnvelope, SwitchEvidence, TransferPackage


@dataclass(frozen=True, slots=True)
class ProjectStreamContext:
    workflow_id: str
    workspace_id: str
    project_id: str
    agent_id: str
    session_id: str
    intent_id: str
    correlation_id: str
    preflight: Mapping[str, bool]
    approved_effects: tuple[str, ...]
    approval: bool
    payload: Mapping[str, object]
    lease_expires_utc: str | None = None
    timeout_seconds: int = 120


@dataclass(frozen=True, slots=True)
class ProjectStreamResult:
    workflow_id: str
    status: str
    reasons: tuple[str, ...]
    outputs: Mapping[str, object]
    checkpoints: tuple[str, ...]
    handler: str | None


Handler = Callable[[ProjectStreamContext], Mapping[str, object]]


def _authorization_expired(context: ProjectStreamContext) -> bool:
    if context.lease_expires_utc is None:
        return False
    try:
        expiry = datetime.fromisoformat(context.lease_expires_utc)
    except ValueError:
        return True
    return expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _append_checkpoint(root: Path, context: ProjectStreamContext, stage: str, status: str, payload: Mapping[str, object]) -> str:
    directory = root / context.correlation_id
    existing = tuple(sorted(directory.glob("*.json"))) if directory.is_dir() else ()
    sequence = len(existing) + 1
    record = {
        "schema_version": "1.0", "sequence": sequence, "workflow_id": context.workflow_id,
        "identity": {
            "workspace_id": context.workspace_id, "project_id": context.project_id,
            "agent_id": context.agent_id, "session_id": context.session_id,
            "intent_id": context.intent_id, "correlation_id": context.correlation_id,
        },
        "stage": stage, "status": status, "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest(),
        "approved_effects": list(context.approved_effects),
        "approval": context.approval,
        "lease_expires_utc": context.lease_expires_utc,
        "timeout_seconds": context.timeout_seconds,
        "repository": dict(context.payload.get("repository_state", {})),
        "active_skills": list(context.payload.get("active_skills", ())),
        "tool_versions": dict(context.payload.get("tool_versions", {})),
        "budgets": dict(context.payload.get("budgets", {})),
        "failures": list(context.payload.get("failures", ())),
        "open_circuits": list(context.payload.get("open_circuits", ())),
        "next_safe_action": str(context.payload.get("next_safe_action", "reconcile checkpoint before resume")),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = directory / f"{sequence:06d}-{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return path.as_posix()


def validate_checkpoint_resume(checkpoint: Path, context: ProjectStreamContext, current_repository: Mapping[str, object]) -> dict[str, object]:
    """Fail closed when identity, repository state, or approval scope changed."""
    record = _load(checkpoint)
    reasons: list[str] = []
    expected_identity = {
        "workspace_id": context.workspace_id, "project_id": context.project_id,
        "agent_id": context.agent_id, "session_id": context.session_id,
        "intent_id": context.intent_id, "correlation_id": context.correlation_id,
    }
    if record.get("identity") != expected_identity:
        reasons.append("checkpoint_identity_drift")
    recorded_repository = record.get("repository", {})
    for field in ("root", "branch", "commit", "working_tree_sha256"):
        if recorded_repository.get(field) != current_repository.get(field):
            reasons.append(f"repository_{field}_drift")
    if set(record.get("approved_effects", ())) != set(context.approved_effects):
        reasons.append("approved_effect_scope_drift")
    if record.get("approval") is True and context.approval is not True:
        reasons.append("approval_no_longer_valid")
    return {
        "valid": not reasons, "status": "resumable" if not reasons else "stale",
        "reasons": tuple(reasons), "next_safe_action": record.get("next_safe_action"),
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
    }


def _sources(payload: Mapping[str, object]) -> tuple[SourceArtifact, ...]:
    values = payload.get("sources", ())
    if not isinstance(values, (tuple, list)) or not all(isinstance(item, SourceArtifact) for item in values):
        raise ValueError("workflow payload requires SourceArtifact records")
    return tuple(values)


def memory_ingest_distill(context: ProjectStreamContext) -> Mapping[str, object]:
    vault = context.payload.get("vault")
    if not isinstance(vault, MemoryVault):
        raise ValueError("memory ingest requires a MemoryVault")
    sources = _sources(context.payload)
    bundle = compile_foundry_bundle(sources)
    source_lookup = {str(item["source_id"]): item for item in bundle.sources}
    existing = {record.memory_id for record in vault.latest_records()}
    created = []
    now = datetime.now(timezone.utc)
    for item in bundle.knowledge:
        memory_id = "mem-" + item.object_id
        if memory_id in existing:
            continue
        evidence_id = item.evidence_refs[0]
        source = source_lookup[evidence_id]
        record = MemoryRecord(
            memory_id, context.workspace_id, context.project_id, context.agent_id,
            context.session_id, str(context.payload.get("lease_id", context.intent_id)), item.statement[:120],
            "procedure" if item.kind == "procedure" else "fact", item.statement,
            str(source["locator"]), str(source["sha256"]), evidence_id,
            "observation", item.confidence, "source_normalization", "internal",
            (context.project_id,), now, now, relationships=item.relationships,
        )
        created.append(vault.append(record).memory_id)
    return {
        "memory_notes_updated": len(created), "memory_ids": tuple(created),
        "knowledge_bundle_id": bundle.bundle_id, "candidate_skill_ids": tuple(skill.skill_id for skill in bundle.skills),
        "retrieval_activation": "disabled_until_memory_certification",
    }


def memory_maintenance(context: ProjectStreamContext) -> Mapping[str, object]:
    vault = context.payload.get("vault")
    if not isinstance(vault, MemoryVault):
        raise ValueError("memory maintenance requires a MemoryVault")
    before = vault.reconcile_indexes()
    if before["orphan_generations"]:
        return {
            "memory_health_report": "review_required", "index": before,
            "action": "quarantine_orphans_after_human_review", "hard_delete": False,
        }
    generation = vault.build_index()
    return {
        "memory_health_report": "index_published", "generation": asdict(generation),
        "previous_generations_preserved": True, "hard_delete": False,
    }


def continuous_improvement(context: ProjectStreamContext) -> Mapping[str, object]:
    bundle = compile_foundry_bundle(_sources(context.payload))
    usage = dict(context.payload.get("usage", {}))
    failure_rates = dict(context.payload.get("failure_rates", {}))
    recommendations = evolution_recommendations(bundle.skills, usage=usage, failure_rates=failure_rates)
    return {
        "improvement_backlog": tuple(recommendations),
        "candidate_skill_ids": tuple(skill.skill_id for skill in bundle.skills),
        "bundle_id": bundle.bundle_id, "automatic_activation": False,
    }


def _path(context: ProjectStreamContext, name: str) -> Path:
    value = context.payload.get(name)
    if not isinstance(value, Path):
        raise ValueError(f"workflow payload requires Path: {name}")
    return value


def agent_create_validate(context: ProjectStreamContext) -> Mapping[str, object]:
    specification = context.payload.get("specification")
    if not isinstance(specification, Mapping):
        raise ValueError("agent workflow requires specification mapping")
    return {"agent_active_or_rejected": register_agent(_path(context, "ledger"), specification)}


def chaos_resilience_cycle(context: ProjectStreamContext) -> Mapping[str, object]:
    experiments = context.payload.get("experiments")
    if not isinstance(experiments, (list, tuple)) or not all(isinstance(item, Mapping) for item in experiments):
        raise ValueError("resilience workflow requires experiment mappings")
    return {"resilience_report": evaluate_resilience(experiments)}


def cross_project_transfer(context: ProjectStreamContext) -> Mapping[str, object]:
    package = context.payload.get("package")
    if not isinstance(package, TransferPackage):
        raise ValueError("transfer workflow requires TransferPackage")
    result = import_transfer(
        _path(context, "workspace_root"), _path(context, "source"),
        _path(context, "destination"), package, _path(context, "ledger"),
    )
    return {"destination_owned_import": result}


def guarded_change(context: ProjectStreamContext) -> Mapping[str, object]:
    evidence = context.payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("guarded change requires evidence mapping")
    result = apply_guarded_change(
        _path(context, "active_root"), _path(context, "staged_file"), _path(context, "destination"),
        _path(context, "quarantine_root"), _path(context, "ledger"), evidence,
    )
    return {"change_accepted_or_quarantined": result}


def incident_diagnose_recover(context: ProjectStreamContext) -> Mapping[str, object]:
    evidence = context.payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("incident recovery requires evidence mapping")
    result = recover_incident(
        _path(context, "active_root"), _path(context, "recovery_candidate"), _path(context, "destination"),
        _path(context, "quarantine_root"), _path(context, "ledger"), evidence,
    )
    return {"incident_recovered_or_escalated": result}


def nightly_project_health(context: ProjectStreamContext) -> Mapping[str, object]:
    metrics = context.payload.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("health workflow requires metrics mapping")
    return {"health_scorecards": project_health(metrics)}


def project_close(context: ProjectStreamContext) -> Mapping[str, object]:
    result = record_project_transition(
        _path(context, "ledger"), project_id=context.project_id, action="archive",
        evidence=tuple(map(str, context.payload.get("evidence", ()))),
    )
    return {"project_archived": result}


def project_onboard(context: ProjectStreamContext) -> Mapping[str, object]:
    result = register_existing_project(
        _path(context, "project"), _path(context, "ledger"), project_id=context.project_id,
        max_files=int(context.payload.get("max_files", 10_000)),
    )
    return {"project_registered": result}


def project_pause_resume(context: ProjectStreamContext) -> Mapping[str, object]:
    action = str(context.payload.get("action", ""))
    result = record_project_transition(
        _path(context, "ledger"), project_id=context.project_id, action=action,
        evidence=tuple(map(str, context.payload.get("evidence", ()))),
    )
    return {"project_paused_or_resumed": result}


def project_switch(context: ProjectStreamContext) -> Mapping[str, object]:
    old = context.payload.get("old_scope")
    new = context.payload.get("new_scope")
    evidence = context.payload.get("switch_evidence")
    if not isinstance(old, ScopeEnvelope) or not isinstance(new, ScopeEnvelope) or not isinstance(evidence, SwitchEvidence):
        raise ValueError("switch workflow requires old/new ScopeEnvelope and SwitchEvidence")
    return {"new_project_session_active": switch_project(_path(context, "ledger"), old, new, evidence)}


def safe_cleanup(context: ProjectStreamContext) -> Mapping[str, object]:
    candidates = context.payload.get("candidates")
    if not isinstance(candidates, (list, tuple)) or not all(isinstance(item, Path) for item in candidates):
        raise ValueError("cleanup workflow requires Path candidates")
    result = quarantine_candidates(
        _path(context, "active_root"), candidates, _path(context, "quarantine_root"), _path(context, "ledger"),
    )
    return {"quarantine_review_queue": result}


def shared_capability_promote(context: ProjectStreamContext) -> Mapping[str, object]:
    evidence = context.payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("promotion workflow requires evidence mapping")
    result = promote_capability(
        _path(context, "candidate"), _path(context, "shared_root"), _path(context, "ledger"), evidence,
    )
    return {"shared_capability_release": result}


def workspace_bootstrap(context: ProjectStreamContext) -> Mapping[str, object]:
    from .workspace_manager import discover_projects, initialize_workspace

    project = _path(context, "project").resolve()
    workspace_value = context.payload.get("workspace_root", project.parent)
    if not isinstance(workspace_value, Path):
        raise ValueError("workspace_root must be a Path")
    workspace = workspace_value.resolve()
    if project == workspace or workspace not in project.parents:
        raise ValueError("project must be a descendant of the workspace root")
    drop_root = workspace / "projects"
    if project.parent.resolve() != drop_root.resolve():
        raise ValueError("project must be a direct child of the workspace projects drop root")
    source_root = context.payload.get("source_root")
    if not isinstance(source_root, Path):
        raise ValueError("workspace bootstrap requires the installed framework source root")
    initialized = initialize_workspace(workspace, workspace_id=context.workspace_id, apply=True)
    project.mkdir(parents=False, exist_ok=True)
    discovered = discover_projects(workspace, source_root=source_root, apply=True)
    return {
        "workspace_ready": {
            "valid": initialized["valid"] and discovered["valid"],
            "applied": True,
            "workspace_id": context.workspace_id,
            "drop_location": drop_root.as_posix(),
            "tracking": (workspace / "projects_tracking").as_posix(),
            "registered_count": discovered["registered_count"],
        }
    }


def workstream_plan_dispatch(context: ProjectStreamContext) -> Mapping[str, object]:
    items = context.payload.get("workstreams")
    snapshot = context.payload.get("resource_snapshot")
    if not isinstance(items, (list, tuple)) or not all(isinstance(item, Mapping) for item in items) or not isinstance(snapshot, Mapping):
        raise ValueError("dispatch workflow requires workstream list and resource snapshot")
    return {"workstreams_assigned": dispatch_workstreams(items, snapshot)}


BUILTIN_HANDLERS: dict[str, Handler] = {
    "agent_create_validate": agent_create_validate,
    "chaos_resilience_cycle": chaos_resilience_cycle,
    "cross_project_transfer": cross_project_transfer,
    "guarded_change": guarded_change,
    "incident_diagnose_recover": incident_diagnose_recover,
    "memory_ingest_distill": memory_ingest_distill,
    "memory_maintenance": memory_maintenance,
    "continuous_improvement": continuous_improvement,
    "nightly_project_health": nightly_project_health,
    "project_close": project_close,
    "project_onboard": project_onboard,
    "project_pause_resume": project_pause_resume,
    "project_switch": project_switch,
    "safe_cleanup": safe_cleanup,
    "shared_capability_promote": shared_capability_promote,
    "workspace_bootstrap": workspace_bootstrap,
    "workstream_plan_dispatch": workstream_plan_dispatch,
}


def execute_project_stream(
    root: Path,
    context: ProjectStreamContext,
    *,
    checkpoint_root: Path,
    handlers: Mapping[str, Handler] | None = None,
) -> ProjectStreamResult:
    registry = _load(root / "registry" / "project_stream_orchestrations.json")
    workflows = {str(item["orchestration_id"]): item for item in registry["orchestrations"]}
    workflow = workflows.get(context.workflow_id)
    if workflow is None:
        return ProjectStreamResult(context.workflow_id, "blocked", ("unknown_workflow",), {}, (), None)
    checkpoints = []
    required_values = (context.workspace_id, context.agent_id, context.session_id, context.intent_id, context.correlation_id)
    if not all(value.strip() for value in required_values):
        return ProjectStreamResult(context.workflow_id, "blocked", ("required_context_missing",), {}, (), None)
    if context.workflow_id != "workspace_bootstrap" and not context.project_id.strip():
        return ProjectStreamResult(context.workflow_id, "blocked", ("project_binding_missing",), {}, (), None)
    if context.timeout_seconds < 1 or context.timeout_seconds > 3600:
        return ProjectStreamResult(context.workflow_id, "blocked", ("workflow_timeout_outside_budget",), {}, (), None)
    if _authorization_expired(context):
        return ProjectStreamResult(context.workflow_id, "blocked", ("project_lease_expired",), {}, (), None)
    missing_preflight = tuple(name for name in workflow["preflight"] if context.preflight.get(name) is not True)
    if missing_preflight:
        return ProjectStreamResult(context.workflow_id, "blocked", tuple(f"preflight_failed:{name}" for name in missing_preflight), {}, (), None)
    checkpoints.append(_append_checkpoint(checkpoint_root, context, "preflight", "passed", context.preflight))
    registry_handlers = _load(root / "registry" / "project_stream_handlers.json")
    binding = next(item for item in registry_handlers["workflows"] if item["orchestration_id"] == context.workflow_id)
    if binding["status"] != "executable":
        checkpoints.append(_append_checkpoint(checkpoint_root, context, "activation", "blocked", binding))
        return ProjectStreamResult(
            context.workflow_id, "plan_only", ("workflow_implementation_not_admitted",),
            {"skills": tuple(workflow["skills"]), "outcomes": tuple(workflow["outcomes"])},
            tuple(checkpoints), None,
        )
    effects = set(map(str, binding["effects"]))
    if not effects <= set(context.approved_effects):
        return ProjectStreamResult(context.workflow_id, "blocked", ("effects_not_approved",), {}, tuple(checkpoints), str(binding["handler"]))
    if effects - {"read_local"} and not context.approval:
        return ProjectStreamResult(context.workflow_id, "blocked", ("explicit_approval_missing",), {}, tuple(checkpoints), str(binding["handler"]))
    active_handlers = dict(BUILTIN_HANDLERS if handlers is None else handlers)
    handler = active_handlers.get(context.workflow_id)
    if handler is None:
        return ProjectStreamResult(context.workflow_id, "blocked", ("runtime_handler_missing",), {}, tuple(checkpoints), str(binding["handler"]))
    if _authorization_expired(context):
        checkpoints.append(_append_checkpoint(checkpoint_root, context, "authorization", "blocked", {"reason": "project_lease_expired"}))
        return ProjectStreamResult(context.workflow_id, "blocked", ("project_lease_expired",), {}, tuple(checkpoints), str(binding["handler"]))
    started = datetime.now(timezone.utc)
    try:
        outputs = dict(handler(context))
    except Exception as error:
        checkpoints.append(_append_checkpoint(checkpoint_root, context, "execution", "failed", {"error": type(error).__name__}))
        return ProjectStreamResult(context.workflow_id, "failed", (f"{type(error).__name__}:{error}",), {}, tuple(checkpoints), str(binding["handler"]))
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if _authorization_expired(context) or elapsed > context.timeout_seconds:
        reason = "project_lease_expired" if _authorization_expired(context) else "workflow_timeout_exceeded"
        checkpoints.append(_append_checkpoint(checkpoint_root, context, "verification", "failed", {"reason": reason, "elapsed_seconds": elapsed}))
        return ProjectStreamResult(context.workflow_id, "failed", (reason,), {}, tuple(checkpoints), str(binding["handler"]))
    missing_outcomes = tuple(name for name in workflow["outcomes"] if name not in outputs)
    status = "completed" if not missing_outcomes else "incomplete"
    checkpoints.append(_append_checkpoint(checkpoint_root, context, "verification", status, outputs))
    return ProjectStreamResult(
        context.workflow_id, status, tuple(f"outcome_missing:{name}" for name in missing_outcomes),
        outputs, tuple(checkpoints), str(binding["handler"]),
    )
