"""Operational multi-project workspace and isolated memory control plane.

The manager turns the project-stream primitives into a user-facing workspace:
repositories are dropped below ``projects/``; tracking, sessions, checkpoints,
and memory remain project-scoped below ``projects_tracking/``. Mutable control
files are snapshot before replacement, and project content is never deleted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tomllib
from typing import Iterable, Mapping
from functools import wraps

from .commissioning import commission, project_check
from .contracts import validate_instance
from .file_lock import FileLock
from .event_ledger import validate_event_ledger
from .intake import inspect_existing_project
from .integration_registry import validate_integrations
from .knowledge_foundry import SourceArtifact
from .memory_fabric import MemoryRecord
from .memory_vault import MemoryVault
from .project_control_plane import append_event, switch_project
from .project_stream_controls import (
    ContextObject,
    ScopeEnvelope,
    SwitchEvidence,
    TransferPackage,
    authorize_context,
)
from .paths import framework_root


def _project_stream_api():
    """Resolve the orchestration boundary lazily after workspace state is loaded.

    This dependency inversion prevents the workspace/bootstrap handler and the
    workspace manager from forming a Python import cycle at module load time.
    """
    from importlib import import_module

    module = import_module(".project_stream_orchestrator", package=__package__)
    return module.ProjectStreamContext, module.execute_project_stream


WORKSPACE_CONFIG = "engineering-workspace.toml"
REGISTRY_NAME = "project-registry.json"
CONFIG_SEAL_NAME = "workspace-config.sha256"
REGISTRY_SEAL_NAME = "project-registry.sha256"
ID_SAFE = re.compile(r"[^a-z0-9_-]+")
PREFLIGHT = {
    "constitution_resolved": True,
    "lease_valid": True,
    "scope_resolved": True,
    "side_effect_budget_set": True,
}


def _validate_control(value: object, schema_name: str) -> None:
    validate_instance(
        value, framework_root() / "contracts" / "project_stream" / schema_name
    )


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path
    projects: Path
    tracking: Path
    quarantine: Path
    shared_capabilities: Path
    registry: Path
    events: Path
    checkpoints: Path
    project_state: Path
    sessions: Path
    history: Path
    dashboard: Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, *, prefix: str) -> str:
    normalized = ID_SAFE.sub("-", value.casefold()).strip("-_") or "project"
    return f"{prefix}_{normalized}"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def workspace_paths(root: Path) -> WorkspacePaths:
    resolved = root.resolve()
    tracking = resolved / "projects_tracking"
    return WorkspacePaths(
        resolved,
        resolved / "projects",
        tracking,
        resolved / "repo_quarantine",
        resolved / "shared_capabilities",
        tracking / REGISTRY_NAME,
        tracking / "events",
        tracking / "checkpoints",
        tracking / "projects",
        tracking / "sessions",
        tracking / "history",
        tracking / "PROJECT_MANAGEMENT.md",
    )


def _locked_when_apply(function):
    @wraps(function)
    def wrapped(root: Path, *args, **kwargs):
        if kwargs.get("apply") is not True:
            return function(root, *args, **kwargs)
        paths = workspace_paths(root)
        with FileLock(paths.tracking / ".workspace-control.lock"):
            config_path = paths.root / WORKSPACE_CONFIG
            before = _sha(config_path) if config_path.is_file() else None
            result = function(root, *args, **kwargs)
            after = _sha(config_path) if config_path.is_file() else None
            if before is not None and after != before:
                raise ValueError("workspace configuration changed during mutation")
            return result

    return wrapped


def _locked_mutation(function):
    @wraps(function)
    def wrapped(root: Path, *args, **kwargs):
        paths = workspace_paths(root)
        with FileLock(paths.tracking / ".workspace-control.lock"):
            config_path = paths.root / WORKSPACE_CONFIG
            before = _sha(config_path) if config_path.is_file() else None
            result = function(root, *args, **kwargs)
            after = _sha(config_path) if config_path.is_file() else None
            if before is not None and after != before:
                raise ValueError("workspace configuration changed during mutation")
            return result

    return wrapped


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _write_json_new(path: Path, value: Mapping[str, object]) -> None:
    _write_new(path, (json.dumps(value, indent=2, default=str) + "\n").encode("utf-8"))


def _snapshot_and_replace(
    paths: WorkspacePaths, path: Path, value: Mapping[str, object]
) -> None:
    """Replace control state only after preserving the exact previous generation."""
    if path.is_file():
        relative = path.relative_to(paths.tracking).as_posix().replace("/", "--")
        archive = (
            paths.history
            / relative
            / f"{_now().replace(':', '-')}-{_sha(path)[:16]}.json"
        )
        _write_new(archive, path.read_bytes())
    payload = (json.dumps(value, indent=2, default=str) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + f".next-{_stable(value)[:12]}")
    _write_new(temporary, payload)
    os.replace(temporary, path)


def _replace_text_control(paths: WorkspacePaths, path: Path, text: str) -> None:
    if path.is_file():
        relative = path.relative_to(paths.tracking).as_posix().replace("/", "--")
        archive = (
            paths.history
            / relative
            / f"{_now().replace(':', '-')}-{_sha(path)[:16]}.txt"
        )
        _write_new(archive, path.read_bytes())
    payload = text.encode("utf-8")
    temporary = path.with_name(
        path.name + f".next-{hashlib.sha256(payload).hexdigest()[:12]}"
    )
    _write_new(temporary, payload)
    os.replace(temporary, path)


def _replace_registry(paths: WorkspacePaths, value: Mapping[str, object]) -> None:
    _snapshot_and_replace(paths, paths.registry, value)
    _replace_text_control(
        paths, paths.tracking / REGISTRY_SEAL_NAME, _sha(paths.registry) + "\n"
    )


def _workspace_config(workspace_id: str) -> str:
    return f'''workspace_id = "{workspace_id}"
policy_version = "1.0.0"
hard_delete_allowed_for_automation = false

[roots]
projects = "projects"
tracking = "projects_tracking"
quarantine = "repo_quarantine"
shared_capabilities = "shared_capabilities"

[boundaries]
cross_project_context_default = "deny"
untagged_context = "deny"
project_switch_requires_teardown = true
quarantine_indexing = false

[leases]
default_minutes = 60
max_minutes = 480
write_requires_intent = true

[memory]
canonical_format = "markdown"
address_scheme = "adaptive-minimum-bit-alphabetic-v1"
integrity_hash = "sha256"
'''


def _load_config(paths: WorkspacePaths) -> dict[str, object]:
    config_path = paths.root / WORKSPACE_CONFIG
    if not config_path.is_file():
        raise ValueError(f"workspace is not initialized: missing {WORKSPACE_CONFIG}")
    before = config_path.read_bytes()
    config_digest = hashlib.sha256(before).hexdigest()
    config = tomllib.loads(before.decode("utf-8"))
    _validate_control(config, "workspace_config.schema.json")
    seal = paths.tracking / CONFIG_SEAL_NAME
    if not seal.is_file() or seal.read_text(encoding="utf-8").strip() != config_digest:
        raise ValueError(
            "workspace configuration integrity seal is missing or mismatched"
        )
    if not re.fullmatch(r"wsp_[A-Za-z0-9_-]+", str(config.get("workspace_id", ""))):
        raise ValueError("workspace configuration has an invalid workspace_id")
    expected = {
        "projects": "projects",
        "tracking": "projects_tracking",
        "quarantine": "repo_quarantine",
        "shared_capabilities": "shared_capabilities",
    }
    if config.get("roots") != expected:
        raise ValueError("workspace roots drifted from the bounded layout")
    boundaries = config.get("boundaries", {})
    if (
        not isinstance(boundaries, Mapping)
        or boundaries.get("cross_project_context_default") != "deny"
        or boundaries.get("project_switch_requires_teardown") is not True
    ):
        raise ValueError("workspace isolation boundaries are not fail closed")
    if (
        config_path.read_bytes() != before
        or seal.read_text(encoding="utf-8").strip() != config_digest
    ):
        raise ValueError("workspace configuration changed during verified read")
    return config


def _load_registry(paths: WorkspacePaths) -> dict[str, object]:
    if not paths.registry.is_file():
        raise ValueError("workspace project registry is missing")
    value = json.loads(paths.registry.read_text(encoding="utf-8"))
    seal = paths.tracking / REGISTRY_SEAL_NAME
    if not seal.is_file() or seal.read_text(encoding="utf-8").strip() != _sha(
        paths.registry
    ):
        raise ValueError(
            "workspace registry projection integrity seal is missing or mismatched; run workspace rebuild --apply"
        )
    _validate_control(value, "workspace-registry.schema.json")
    if not isinstance(value.get("projects"), list):
        raise ValueError("workspace project registry is malformed")
    return value


def _project_by_id(
    registry: Mapping[str, object], project_id: str
) -> dict[str, object]:
    matches = [
        item
        for item in registry.get("projects", [])
        if isinstance(item, dict) and item.get("project_id") == project_id
    ]
    if len(matches) != 1:
        raise ValueError(f"project is not uniquely registered: {project_id}")
    return matches[0]


def _project_path(paths: WorkspacePaths, record: Mapping[str, object]) -> Path:
    project = (paths.root / str(record["path"])).resolve()
    if not _inside(project, paths.projects) or project == paths.projects:
        raise ValueError("registered project path escapes the project drop root")
    return project


def _memory_root(paths: WorkspacePaths, project_id: str) -> Path:
    return paths.project_state / project_id / "memory"


def _event_ledger(paths: WorkspacePaths) -> Path:
    return paths.events


def _pending_workspace_operations(paths: WorkspacePaths) -> tuple[str, ...]:
    intents: set[str] = set()
    completed: set[str] = set()
    for path in sorted(paths.events.glob("*.json")) if paths.events.is_dir() else ():
        event = json.loads(path.read_text(encoding="utf-8"))
        payload = event.get("payload", {})
        if not isinstance(payload, Mapping):
            continue
        operation_id = str(payload.get("operation_id", ""))
        if not operation_id:
            continue
        if event.get("kind") == "workspace-operation-intent":
            intents.add(operation_id)
        elif event.get("kind") in {
            "project-activated",
            "project-released",
            "session-created",
            "session-released",
            "workspace-operation-recovered",
        }:
            completed.add(operation_id)
    return tuple(sorted(intents - completed))


def _session_path(paths: WorkspacePaths, session_id: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,127}", session_id):
        raise ValueError("session_id is invalid")
    return paths.sessions / f"{session_id}.json"


def _session_projections_from_events(
    paths: WorkspacePaths,
) -> dict[str, dict[str, object]]:
    validation = validate_event_ledger(paths.events)
    if not validation["valid"]:
        raise ValueError(
            "workspace event ledger integrity failure: "
            + "; ".join(validation["errors"])
        )
    sessions: dict[str, dict[str, object]] = {}
    for event in validation["events"]:
        payload = event["payload"]
        kind = event["kind"]
        if kind in {"project-activated", "session-created"}:
            session = payload.get("active_session")
            if not isinstance(session, Mapping):
                raise ValueError("session creation event is malformed")
            session_id = str(session.get("scope", {}).get("session_id", ""))
            if not session_id:
                raise ValueError("session creation event has no session identity")
            sessions[session_id] = dict(session)
        elif kind in {"project-lease-renewed", "session-renewed"}:
            session_id = str(payload.get("session_id", ""))
            if (
                not session_id
                or session_id not in sessions
                or sessions[session_id].get("status") != "active"
            ):
                raise ValueError("session renewal event references no active session")
            if payload.get("lease_id") != sessions[session_id].get("scope", {}).get(
                "lease_id"
            ):
                raise ValueError("session renewal lease binding mismatch")
            sessions[session_id] = {
                **sessions[session_id],
                "expires_utc": payload["new_expiry"],
                "renewed_utc": payload["renewed_utc"],
            }
        elif kind in {
            "project-released",
            "session-released",
            "session-revoked",
            "session-expired",
        }:
            session_id = str(payload.get("session_id", ""))
            if session_id in sessions:
                status = {
                    "session-revoked": "revoked",
                    "session-expired": "expired",
                }.get(str(kind), "released")
                sessions[session_id] = {
                    **sessions[session_id],
                    "status": status,
                    str(payload.get("status_time_field", f"{status}_utc")): payload.get(
                        "status_time", event["created_utc"]
                    ),
                }
    return sessions


def _verified_session(
    paths: WorkspacePaths, session_id: str
) -> dict[str, object] | None:
    expected = _session_projections_from_events(paths).get(session_id)
    path = _session_path(paths, session_id)
    if expected is None:
        if path.is_file():
            raise ValueError(
                "session projection exists without authoritative lifecycle event"
            )
        return None
    if not path.is_file():
        raise ValueError("authoritative session event has no projection")
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("session projection is unreadable") from error
    if actual != expected:
        raise ValueError(
            "session projection differs from authoritative lifecycle events"
        )
    return expected


def _active_sessions(paths: WorkspacePaths) -> tuple[dict[str, object], ...]:
    expected = _session_projections_from_events(paths)
    actual_names = (
        {path.stem for path in paths.sessions.glob("*.json")}
        if paths.sessions.is_dir()
        else set()
    )
    if actual_names != set(expected):
        raise ValueError(
            "session projection set differs from authoritative lifecycle events"
        )
    values = [_verified_session(paths, session_id) for session_id in sorted(expected)]
    return tuple(
        value
        for value in values
        if value is not None and value.get("status") == "active"
    )


def _dashboard(
    paths: WorkspacePaths,
    registry: Mapping[str, object],
    active_sessions: Iterable[Mapping[str, object]],
) -> str:
    active_values = tuple(active_sessions)
    lines = [
        "# Workspace Project Management",
        "",
        f"Workspace: `{registry['workspace_id']}`  ",
        f"Registry revision: `{registry['revision']}`  ",
        f"Active sessions: `{len(active_values)}`",
        "",
        "## Project drop location",
        "",
        "`projects/`",
        "",
        "Drop one repository directory directly under `projects/`, then run workspace discovery. Each admitted project receives isolated tracking, checkpoints, leases, and memory.",
        "",
        "## Registered projects",
        "",
        "| Project | State | Repository | Memory namespace |",
        "|---|---|---|---|",
    ]
    for item in registry.get("projects", []):
        lines.append(
            f"| `{item['project_id']}` | `{item['state']}` | `{item['path']}` | `{item['memory_namespace']}` |"
        )
    if not registry.get("projects"):
        lines.append("| _none_ |  |  |  |")
    lines.extend(
        [
            "",
            "## Active session leases",
            "",
            "| Session | Agent | Project | Expires |",
            "|---|---|---|---|",
        ]
    )
    for active in active_values:
        lines.append(
            f"| `{active['scope']['session_id']}` | `{active['scope']['agent_id']}` | `{active['project_id']}` | `{active['expires_utc']}` |"
        )
    if not active_values:
        lines.append("| _none_ |  |  |  |")
    lines.extend(
        [
            "",
            "## Isolation contract",
            "",
            "- Exactly one active writable project lease is allowed per workspace session.",
            "- Project memory is stored below `projects_tracking/projects/<project-id>/memory/`.",
            "- Cross-project context and private-memory transfer are denied by default.",
            "- Switching requires a checkpoint, lease revocation, root rebinding, cache teardown confirmation, and a negative old-project access test.",
            "- Cleanup is recoverable quarantine only; automation never hard-deletes.",
            "",
        ]
    )
    return "\n".join(lines)


def _refresh_dashboard(paths: WorkspacePaths, registry: Mapping[str, object]) -> None:
    data = _dashboard(paths, registry, _active_sessions(paths)).encode("utf-8")
    if paths.dashboard.is_file():
        old = paths.dashboard.read_bytes()
        archive = (
            paths.history
            / "PROJECT_MANAGEMENT.md"
            / f"{_now().replace(':', '-')}-{hashlib.sha256(old).hexdigest()[:16]}.md"
        )
        _write_new(archive, old)
        temporary = paths.dashboard.with_name(
            paths.dashboard.name + f".next-{hashlib.sha256(data).hexdigest()[:12]}"
        )
        _write_new(temporary, data)
        os.replace(temporary, paths.dashboard)
    else:
        _write_new(paths.dashboard, data)


def _bind_project_management(
    paths: WorkspacePaths, project: Path, binding: Mapping[str, object]
) -> None:
    project_id = str(binding["project_id"])
    state_path = (
        project / ".engineering-bootstrap" / "project-management" / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["project"].update(
        {
            "workspace_id": binding["workspace_id"],
            "workspace_binding": ".engineering-bootstrap/workspace-binding.json",
            "central_tracking": binding["project_tracking"],
            "memory_namespace": binding["memory_namespace"],
        }
    )
    state["checkpoint"]["revision"] = int(state["checkpoint"].get("revision", 1)) + 1
    old_state = state_path.read_bytes()
    state_archive = (
        paths.history
        / "projects"
        / project_id
        / "project-management-state"
        / f"{_now().replace(':', '-')}-{hashlib.sha256(old_state).hexdigest()[:16]}.json"
    )
    _write_new(state_archive, old_state)
    temporary = state_path.with_name(state_path.name + f".next-{_stable(state)[:12]}")
    _write_new(temporary, (json.dumps(state, indent=2) + "\n").encode("utf-8"))
    os.replace(temporary, state_path)
    dashboard = project / "PROJECT_MANAGEMENT.md"
    marker = "## Workspace binding"
    if marker not in dashboard.read_text(encoding="utf-8"):
        old_dashboard = dashboard.read_bytes()
        dashboard_archive = (
            paths.history
            / "projects"
            / project_id
            / "PROJECT_MANAGEMENT"
            / f"{_now().replace(':', '-')}-{hashlib.sha256(old_dashboard).hexdigest()[:16]}.md"
        )
        _write_new(dashboard_archive, old_dashboard)
        addition = (
            f"\n{marker}\n\n"
            f"Workspace: `{binding['workspace_id']}`  \n"
            f"Central tracking: `{binding['project_tracking']}`  \n"
            f"Memory namespace: `{binding['memory_namespace']}`  \n"
            "Cross-project access: `deny`\n"
        ).encode("utf-8")
        temporary_dashboard = dashboard.with_name(
            dashboard.name
            + f".next-{hashlib.sha256(old_dashboard + addition).hexdigest()[:12]}"
        )
        _write_new(temporary_dashboard, old_dashboard + addition)
        os.replace(temporary_dashboard, dashboard)


@_locked_when_apply
def initialize_workspace(
    root: Path, *, workspace_id: str | None = None, apply: bool = False
) -> dict[str, object]:
    paths = workspace_paths(root)
    selected_id = workspace_id or _slug(paths.root.name, prefix="wsp")
    if not re.fullmatch(r"wsp_[A-Za-z0-9_-]+", selected_id):
        raise ValueError("workspace_id must match ^wsp_[A-Za-z0-9_-]+$")
    effects = [
        WORKSPACE_CONFIG,
        "projects/",
        "projects_tracking/",
        "repo_quarantine/",
        "shared_capabilities/",
        "projects_tracking/project-registry.json",
        "projects_tracking/workspace-config.sha256",
        "projects_tracking/project-registry.sha256",
        "projects_tracking/PROJECT_MANAGEMENT.md",
    ]
    config_path = paths.root / WORKSPACE_CONFIG
    if config_path.exists():
        config = _load_config(paths)
        if config["workspace_id"] != selected_id:
            raise ValueError("workspace already initialized with a different identity")
        status = workspace_status(paths.root)
        return {
            "valid": status["valid"],
            "applied": False,
            "already_initialized": True,
            "workspace_id": selected_id,
            "effects": effects,
            "status": status,
        }
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "workspace_id": selected_id,
            "effects": effects,
            "approval_required": True,
        }
    paths.root.mkdir(parents=True, exist_ok=True)
    for directory in (
        paths.projects,
        paths.tracking,
        paths.quarantine,
        paths.shared_capabilities,
        paths.events,
        paths.checkpoints,
        paths.project_state,
        paths.sessions,
        paths.history,
    ):
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"workspace layout collision: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
    _write_new(config_path, _workspace_config(selected_id).encode("utf-8"))
    _write_new(
        paths.tracking / CONFIG_SEAL_NAME, (_sha(config_path) + "\n").encode("utf-8")
    )
    registry = {
        "schema_version": "1.0",
        "workspace_id": selected_id,
        "revision": 1,
        "projects": [],
        "updated_utc": _now(),
    }
    _validate_control(registry, "workspace-registry.schema.json")
    _write_json_new(paths.registry, registry)
    _write_new(
        paths.tracking / REGISTRY_SEAL_NAME,
        (_sha(paths.registry) + "\n").encode("utf-8"),
    )
    append_event(
        _event_ledger(paths),
        "workspace-initialized",
        {"workspace_id": selected_id, "layout": effects, "hard_delete": False},
    )
    _refresh_dashboard(paths, registry)
    return {
        "valid": True,
        "applied": True,
        "workspace_id": selected_id,
        "effects": effects,
        "drop_location": paths.projects.as_posix(),
        "tracking": paths.tracking.as_posix(),
    }


@_locked_when_apply
def discover_projects(
    root: Path, *, source_root: Path, apply: bool = False, max_files: int = 100_000
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    registry = _load_registry(paths)
    registered_paths = {str(item["path"]): item for item in registry["projects"]}
    registered_ids = {
        str(item["project_id"]): str(item["path"]) for item in registry["projects"]
    }
    proposals = []
    for project in sorted(
        (item for item in paths.projects.iterdir() if item.is_dir()),
        key=lambda item: item.name.casefold(),
    ):
        if (
            not _inside(project, paths.projects)
            or project.resolve() == paths.projects.resolve()
        ):
            raise ValueError(f"project drop path escapes the workspace: {project}")
        relative = project.relative_to(paths.root).as_posix()
        if relative in registered_paths:
            continue
        record_path = project / ".engineering-bootstrap" / "project-record.json"
        existing_record = (
            json.loads(record_path.read_text(encoding="utf-8"))
            if record_path.is_file()
            else None
        )
        project_id = (
            str(existing_record.get("project_id"))
            if isinstance(existing_record, Mapping)
            else _slug(project.name, prefix="prj")
        )
        if not re.fullmatch(r"prj_[A-Za-z0-9_-]+", project_id):
            raise ValueError(f"invalid project identity in drop directory: {relative}")
        if project_id in registered_ids and registered_ids[project_id] != relative:
            raise ValueError(f"project identity collision: {project_id}")
        substantive = any(
            item.is_file()
            for item in project.rglob("*")
            if ".engineering-bootstrap" not in item.parts
        )
        if substantive:
            inspect_existing_project(project, max_files=max_files)
        mode = (
            str(existing_record.get("commissioning_mode"))
            if isinstance(existing_record, Mapping)
            and existing_record.get("commissioning_mode") in {"new", "existing"}
            else ("existing" if substantive else "new")
        )
        proposals.append(
            {
                "project_id": project_id,
                "path": relative,
                "mode": mode,
                "action": "commission_and_register",
            }
        )
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "workspace_id": config["workspace_id"],
            "proposals": proposals,
            "approval_required": bool(proposals),
        }
    admitted = []
    for proposal in proposals:
        project = paths.root / proposal["path"]
        result = commission(
            project, str(proposal["mode"]), apply=True, source_root=source_root
        )
        if not result.get("valid") or not result.get("applied"):
            raise RuntimeError(
                f"project commissioning failed: {proposal['path']}: {result.get('errors') or result.get('conflicts')}"
            )
        check = project_check(project, source_root=source_root)
        if not check.get("valid"):
            raise RuntimeError(
                f"project integrity check failed: {proposal['path']}: {check.get('errors')}"
            )
        local = json.loads(
            (project / ".engineering-bootstrap" / "project-record.json").read_text(
                encoding="utf-8"
            )
        )
        state_root = paths.project_state / str(local["project_id"])
        state_root.mkdir(parents=True, exist_ok=True)
        memory = _memory_root(paths, str(local["project_id"]))
        memory.mkdir(parents=True, exist_ok=True)
        binding = {
            "schema_version": "1.0",
            "workspace_id": config["workspace_id"],
            "project_id": local["project_id"],
            "project_path": proposal["path"],
            "central_registry": paths.registry.relative_to(paths.root).as_posix(),
            "project_tracking": state_root.relative_to(paths.root).as_posix(),
            "memory_namespace": f"project/{local['project_id']}",
            "memory_root": memory.relative_to(paths.root).as_posix(),
            "cross_project_access": "deny",
        }
        _validate_control(binding, "workspace-binding.schema.json")
        binding_path = project / ".engineering-bootstrap" / "workspace-binding.json"
        binding_bytes = (json.dumps(binding, indent=2) + "\n").encode("utf-8")
        if binding_path.is_file() and binding_path.read_bytes() != binding_bytes:
            raise ValueError(f"workspace binding collision: {proposal['path']}")
        if not binding_path.exists():
            _write_new(binding_path, binding_bytes)
        _bind_project_management(paths, project, binding)
        if str(proposal["mode"]) == "existing":
            # Workspace binding intentionally updates the project-facing
            # management dashboard after commissioning. Refresh the static
            # source map at that accepted mutation boundary so first activation
            # does not inherit a knowingly stale map.
            from .project_intelligence import build_project_map

            build_project_map(project)
        central = {
            "project_id": local["project_id"],
            "name": local["name"],
            "state": "registered",
            "path": proposal["path"],
            "commissioning_mode": local["commissioning_mode"],
            "classification": local.get("classification", "internal"),
            "memory_namespace": f"project/{local['project_id']}",
            "memory_root": memory.relative_to(paths.root).as_posix(),
            "project_record_sha256": _sha(
                project / ".engineering-bootstrap" / "project-record.json"
            ),
            "workspace_binding_sha256": _sha(binding_path),
            "project_management": (project / "PROJECT_MANAGEMENT.md")
            .relative_to(paths.root)
            .as_posix(),
            "registered_utc": _now(),
            "cross_project_access": "deny",
        }
        registry["projects"].append(central)
        registry["projects"] = sorted(
            registry["projects"], key=lambda item: str(item["project_id"])
        )
        registry["revision"] = int(registry["revision"]) + 1
        registry["updated_utc"] = _now()
        _validate_control(registry, "workspace-registry.schema.json")
        _replace_registry(paths, registry)
        append_event(
            _event_ledger(paths),
            "project-admitted",
            {
                "project": central,
                "commissioning": {"mode": proposal["mode"], "valid": True},
            },
        )
        admitted.append(central)
    _refresh_dashboard(paths, registry)
    return {
        "valid": True,
        "applied": True,
        "workspace_id": config["workspace_id"],
        "admitted": admitted,
        "registered_count": len(registry["projects"]),
    }


def create_project(
    root: Path, name: str, *, source_root: Path, apply: bool = False
) -> dict[str, object]:
    paths = workspace_paths(root)
    _load_config(paths)
    safe_name = ID_SAFE.sub("-", name.casefold()).strip("-_")
    if not safe_name or safe_name != name.casefold() or "/" in name or "\\" in name:
        raise ValueError(
            "project name must contain only lowercase letters, digits, hyphens, or underscores"
        )
    project = paths.projects / safe_name
    if project.exists():
        raise ValueError(
            "project drop directory already exists; use workspace discover"
        )
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "approval_required": True,
            "project_id": _slug(safe_name, prefix="prj"),
            "project": project.as_posix(),
            "effects": [
                "create empty project drop directory",
                "commission new project",
                "register isolated tracking and memory",
            ],
        }
    with FileLock(paths.tracking / ".workspace-control.lock"):
        project.mkdir(parents=False, exist_ok=False)
    discovered = discover_projects(paths.root, source_root=source_root, apply=True)
    project_id = _slug(safe_name, prefix="prj")
    admitted = [
        item for item in discovered["admitted"] if item["project_id"] == project_id
    ]
    if len(admitted) != 1:
        raise RuntimeError("new project directory was not uniquely admitted")
    return {
        "valid": True,
        "applied": True,
        "project": admitted[0],
        "drop_location": project.as_posix(),
    }


def _new_scope(
    workspace_id: str, project_id: str, *, agent_id: str, session_id: str
) -> ScopeEnvelope:
    suffix = _stable(
        {
            "workspace": workspace_id,
            "project": project_id,
            "agent": agent_id,
            "session": session_id,
            "time": _now(),
        }
    )[:16]
    return ScopeEnvelope(
        workspace_id,
        project_id,
        agent_id,
        session_id,
        f"work_{suffix}",
        f"lease_{suffix}",
        f"intent_{suffix}",
        f"corr_{suffix}",
    )


@_locked_mutation
def activate_project(
    root: Path,
    project_id: str,
    *,
    agent_id: str = "agent_operator",
    session_id: str = "session_operator",
    context_reset_confirmed: bool = False,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    registry = _load_registry(paths)
    target = _project_by_id(registry, project_id)
    if target.get("state") not in {"registered", "active"}:
        raise ValueError(
            f"project cannot be activated from state: {target.get('state')}"
        )
    project = _project_path(paths, target)
    check = project_check(project)
    if not check.get("valid"):
        raise ValueError(
            f"target project failed integrity check: {check.get('errors')}"
        )
    session_path = _session_path(paths, session_id)
    previous = _verified_session(paths, session_id)
    if (
        previous
        and previous.get("status") == "active"
        and previous.get("project_id") == project_id
    ):
        return {
            "valid": True,
            "activated": False,
            "already_active": True,
            "session": previous,
        }
    new_scope = _new_scope(
        str(config["workspace_id"]),
        project_id,
        agent_id=agent_id,
        session_id=session_id,
    )
    operation_id = _stable(
        {
            "operation": "activate",
            "project_id": project_id,
            "session_id": session_id,
            "lease_id": new_scope.lease_id,
        }
    )[:24]
    operation_intent_written = False
    switch_receipt = None
    if previous and previous.get("status") == "active":
        if not context_reset_confirmed:
            return {
                "valid": False,
                "activated": False,
                "approval_required": True,
                "errors": [
                    "project switch requires explicit context-reset confirmation"
                ],
            }
        append_event(
            _event_ledger(paths),
            "workspace-operation-intent",
            {
                "operation_id": operation_id,
                "operation": "activate",
                "project_id": project_id,
                "session_id": session_id,
            },
        )
        operation_intent_written = True
        old_scope = ScopeEnvelope(**previous["scope"])
        checkpoint = {
            "schema_version": "1.0",
            "project_id": old_scope.project_id,
            "session_id": old_scope.session_id,
            "scope": asdict(old_scope),
            "status": "released_for_switch",
            "next_safe_action": f"activate {project_id}",
            "created_utc": _now(),
        }
        checkpoint_path = (
            paths.checkpoints
            / old_scope.project_id
            / f"switch-{_stable(checkpoint)[:20]}.json"
        )
        _write_json_new(checkpoint_path, checkpoint)
        foreign = ContextObject(
            "negative-old-project-memory",
            "project",
            old_scope.project_id,
            "memory",
            "internal",
            "switch-negative-test",
        )
        negative = authorize_context(new_scope, (foreign,))
        evidence = SwitchEvidence(
            True, True, True, True, True, True, True, negative.decision == "deny"
        )
        switch_receipt = switch_project(
            _event_ledger(paths), old_scope, new_scope, evidence
        )
        if switch_receipt.get("decision") != "active":
            raise RuntimeError(
                f"project switch rejected: {switch_receipt.get('reasons')}"
            )
        previous = {
            **previous,
            "status": "revoked",
            "revoked_utc": _now(),
            "checkpoint": checkpoint_path.relative_to(paths.root).as_posix(),
        }
        history_path = (
            paths.project_state
            / old_scope.project_id
            / "leases"
            / f"{old_scope.lease_id}-revoked.json"
        )
        _write_json_new(history_path, previous)
        append_event(
            _event_ledger(paths),
            "session-revoked",
            {
                "operation_id": operation_id,
                "project_id": old_scope.project_id,
                "session_id": old_scope.session_id,
                "lease_id": old_scope.lease_id,
                "status_time": previous["revoked_utc"],
                "status_time_field": "revoked_utc",
            },
        )
    if not operation_intent_written:
        append_event(
            _event_ledger(paths),
            "workspace-operation-intent",
            {
                "operation_id": operation_id,
                "operation": "activate",
                "project_id": project_id,
                "session_id": session_id,
            },
        )
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=int(config["leases"]["default_minutes"])
    )
    active = {
        "schema_version": "1.0",
        "status": "active",
        "workspace_id": config["workspace_id"],
        "project_id": project_id,
        "project_root": project.relative_to(paths.root).as_posix(),
        "memory_namespace": target["memory_namespace"],
        "memory_root": target["memory_root"],
        "scope": asdict(new_scope),
        "writable_roots": [target["path"]],
        "created_utc": _now(),
        "expires_utc": expires.isoformat(),
        "cross_project_access": "deny",
        "switch_receipt": switch_receipt,
    }
    _validate_control(active, "active-session.schema.json")
    append_event(
        _event_ledger(paths),
        "session-created",
        {
            "operation_id": operation_id,
            "active_session": active,
            "old_project_negative_access_denied": True,
        },
    )
    _snapshot_and_replace(paths, session_path, active)
    active_project_ids = {str(item["project_id"]) for item in _active_sessions(paths)}
    for item in registry["projects"]:
        if item["project_id"] in active_project_ids:
            item["state"] = "active"
        elif item["state"] == "active":
            item["state"] = "registered"
    registry["revision"] = int(registry["revision"]) + 1
    registry["updated_utc"] = _now()
    _validate_control(registry, "workspace-registry.schema.json")
    _replace_registry(paths, registry)
    _refresh_dashboard(paths, registry)
    return {
        "valid": True,
        "activated": True,
        "session": active,
        "switch": switch_receipt,
    }


@_locked_mutation
def release_project(
    root: Path, *, session_id: str = "session_operator", context_reset_confirmed: bool
) -> dict[str, object]:
    paths = workspace_paths(root)
    _load_config(paths)
    registry = _load_registry(paths)
    session_path = _session_path(paths, session_id)
    if not session_path.is_file():
        return {"valid": True, "released": False, "reason": "no_active_project"}
    active = _verified_session(paths, session_id)
    if active is None:
        return {"valid": True, "released": False, "reason": "no_active_project"}
    if active.get("status") != "active":
        return {"valid": True, "released": False, "reason": "no_active_project"}
    if not context_reset_confirmed:
        return {
            "valid": False,
            "released": False,
            "approval_required": True,
            "errors": ["release requires explicit context-reset confirmation"],
        }
    released = {**active, "status": "released", "released_utc": _now()}
    scope = ScopeEnvelope(**active["scope"])
    operation_id = _stable(
        {
            "operation": "release",
            "project_id": scope.project_id,
            "session_id": scope.session_id,
            "lease_id": scope.lease_id,
        }
    )[:24]
    append_event(
        _event_ledger(paths),
        "workspace-operation-intent",
        {
            "operation_id": operation_id,
            "operation": "release",
            "project_id": scope.project_id,
            "session_id": scope.session_id,
        },
    )
    history_path = (
        paths.project_state
        / scope.project_id
        / "leases"
        / f"{scope.lease_id}-released.json"
    )
    _write_json_new(history_path, released)
    append_event(
        _event_ledger(paths),
        "session-released",
        {
            "operation_id": operation_id,
            "project_id": scope.project_id,
            "session_id": scope.session_id,
            "lease_id": scope.lease_id,
            "context_reset_confirmed": True,
            "status_time": released["released_utc"],
            "status_time_field": "released_utc",
        },
    )
    _snapshot_and_replace(paths, session_path, released)
    active_project_ids = {str(item["project_id"]) for item in _active_sessions(paths)}
    for item in registry["projects"]:
        if (
            item["project_id"] == scope.project_id
            and item["state"] == "active"
            and scope.project_id not in active_project_ids
        ):
            item["state"] = "registered"
    registry["revision"] = int(registry["revision"]) + 1
    registry["updated_utc"] = _now()
    _replace_registry(paths, registry)
    _refresh_dashboard(paths, registry)
    return {
        "valid": True,
        "released": True,
        "project_id": scope.project_id,
        "session_id": scope.session_id,
        "lease_id": scope.lease_id,
    }


def current_project(
    root: Path, *, session_id: str = "session_operator"
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    active = _verified_session(paths, session_id)
    return {
        "valid": True,
        "workspace_id": config["workspace_id"],
        "active": active if active and active.get("status") == "active" else None,
    }


def list_projects(root: Path) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    registry = _load_registry(paths)
    return {
        "valid": True,
        "workspace_id": config["workspace_id"],
        "revision": registry["revision"],
        "projects": registry["projects"],
    }


def show_project(root: Path, project_id: str) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    registry = _load_registry(paths)
    record = _project_by_id(registry, project_id)
    active = [
        item for item in _active_sessions(paths) if item.get("project_id") == project_id
    ]
    return {
        "valid": True,
        "workspace_id": config["workspace_id"],
        "project": record,
        "active_sessions": [item["scope"]["session_id"] for item in active],
    }


@_locked_mutation
def renew_project(
    root: Path, *, session_id: str = "session_operator", minutes: int = 60
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    maximum = int(config["leases"]["max_minutes"])
    if minutes < 1 or minutes > maximum:
        raise ValueError(f"lease renewal must be between 1 and {maximum} minutes")
    session_path = _session_path(paths, session_id)
    if not session_path.is_file():
        raise ValueError("no active project session")
    active = _verified_session(paths, session_id)
    if active is None:
        raise ValueError("no active project session")
    if active.get("status") != "active":
        raise ValueError("no active project session")
    prior_expiry = active["expires_utc"]
    activated = datetime.fromisoformat(str(active["created_utc"]))
    requested_expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    absolute_expiry = activated + timedelta(minutes=maximum)
    if requested_expiry > absolute_expiry:
        raise ValueError(
            "lease renewal would exceed the configured cumulative active lifetime"
        )
    active = {
        **active,
        "expires_utc": requested_expiry.isoformat(),
        "renewed_utc": _now(),
    }
    append_event(
        _event_ledger(paths),
        "session-renewed",
        {
            "session_id": session_id,
            "project_id": active["project_id"],
            "lease_id": active["scope"]["lease_id"],
            "prior_expiry": prior_expiry,
            "new_expiry": active["expires_utc"],
            "renewed_utc": active["renewed_utc"],
        },
    )
    _snapshot_and_replace(paths, session_path, active)
    return {
        "valid": True,
        "renewed": True,
        "project_id": active["project_id"],
        "lease_id": active["scope"]["lease_id"],
        "expires_utc": active["expires_utc"],
    }


@_locked_when_apply
def transition_project(
    root: Path,
    project_id: str,
    action: str,
    evidence: Iterable[str],
    *,
    apply: bool = False,
) -> dict[str, object]:
    transitions = {
        "pause": ("registered", "paused"),
        "resume": ("paused", "registered"),
        "archive": ("registered", "archived"),
    }
    if action not in transitions:
        raise ValueError("unsupported project lifecycle action")
    paths = workspace_paths(root)
    _load_config(paths)
    registry = _load_registry(paths)
    record = _project_by_id(registry, project_id)
    active = [
        item for item in _active_sessions(paths) if item.get("project_id") == project_id
    ]
    if active:
        raise ValueError(
            "release the active project before changing its lifecycle state"
        )
    expected, target = transitions[action]
    if record.get("state") != expected:
        raise ValueError(f"project lifecycle requires {expected} before {action}")
    evidence_ids = tuple(sorted(set(map(str, evidence))))
    if not evidence_ids:
        raise ValueError("project lifecycle transition requires evidence")
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "approval_required": True,
            "project_id": project_id,
            "action": action,
            "from": expected,
            "to": target,
            "evidence": evidence_ids,
        }
    record["state"] = target
    registry["revision"] = int(registry["revision"]) + 1
    registry["updated_utc"] = _now()
    _replace_registry(paths, registry)
    event = append_event(
        _event_ledger(paths),
        f"project-{action}",
        {
            "project_id": project_id,
            "from": expected,
            "to": target,
            "evidence": evidence_ids,
            "created_utc": _now(),
        },
    )
    _refresh_dashboard(paths, registry)
    return {
        "valid": True,
        "applied": True,
        "project_id": project_id,
        "state": target,
        "event": event.as_posix(),
    }


def _require_active(
    paths: WorkspacePaths, project_id: str, session_id: str = "session_operator"
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    registry = _load_registry(paths)
    project = _project_by_id(registry, project_id)
    active = _verified_session(paths, session_id)
    if active is None:
        raise ValueError("no active project session")
    if active.get("status") != "active" or active.get("project_id") != project_id:
        raise ValueError("requested project is outside the active project session")
    if datetime.fromisoformat(str(active["expires_utc"])) <= datetime.now(timezone.utc):
        raise ValueError("active project lease expired")
    return registry, project, active


def _vault(paths: WorkspacePaths, workspace_id: str, project_id: str) -> MemoryVault:
    return MemoryVault(
        _memory_root(paths, project_id),
        workspace_id=workspace_id,
        project_id=project_id,
    )


@_locked_when_apply
def capture_memory_source(
    root: Path,
    project_id: str,
    source: Path,
    *,
    source_kind: str,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    """Sanitize and hash-bind one project-local source into immutable L0 evidence."""
    from .memory_intelligence import capture_event

    paths = workspace_paths(root)
    config = _load_config(paths)
    _, project_record, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    project = _project_path(paths, project_record)
    source_path = source.resolve()
    if not source_path.is_file() or not _inside(source_path, project):
        raise ValueError(
            "memory capture source must be an existing file inside the active project"
        )
    payload = source_path.read_bytes()
    if not payload or len(payload) > 10 * 1024 * 1024 or b"\x00" in payload:
        raise ValueError(
            "memory capture source must be nonempty bounded textual evidence"
        )
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            "memory capture source must be UTF-8 textual evidence"
        ) from error
    scope = {
        "project_id": project_id,
        "agent_id": actor_id,
        "session_id": session_id,
        "task_id": str(active["scope"].get("intent_id", "")),
    }
    result = capture_event(
        _vault(paths, str(config["workspace_id"]), project_id).root,
        project_id=project_id,
        source_kind=source_kind,
        source_locator=source_path.relative_to(project).as_posix(),
        content=content,
        scope=scope,
        apply=apply,
    )
    result["approval_required"] = not apply
    if apply:
        event = result["event"]
        receipt = append_event(
            _event_ledger(paths),
            "memory-evidence-captured",
            {
                "project_id": project_id,
                "event_id": event["event_id"],
                "content_hash": event["content_hash"],
                "admission_status": event["admission_status"],
                "source_kind": source_kind,
            },
        )
        result["audit_event"] = receipt.as_posix()
    return result


@_locked_when_apply
def ingest_memory(
    root: Path,
    project_id: str,
    sources: Iterable[Path],
    *,
    source_root: Path,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    _, record, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    project = _project_path(paths, record)
    resolved = tuple(path.resolve() for path in sources)
    if not resolved or any(
        not path.is_file() or not _inside(path, project) for path in resolved
    ):
        raise ValueError(
            "memory sources must be existing files inside the active project"
        )
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "project_id": project_id,
            "sources": [path.relative_to(project).as_posix() for path in resolved],
            "approval_required": True,
        }
    artifacts = tuple(
        replace(
            SourceArtifact.from_path(path), locator=path.relative_to(project).as_posix()
        )
        for path in resolved
    )
    scope = ScopeEnvelope(**active["scope"])
    ProjectStreamContext, execute_project_stream = _project_stream_api()
    context = ProjectStreamContext(
        "memory_ingest_distill",
        str(config["workspace_id"]),
        project_id,
        scope.agent_id,
        scope.session_id,
        scope.intent_id,
        scope.correlation_id,
        PREFLIGHT,
        ("read_local", "write_workspace"),
        True,
        {
            "vault": _vault(paths, str(config["workspace_id"]), project_id),
            "sources": artifacts,
            "lease_id": scope.lease_id,
            "next_safe_action": "review and validate candidate memory",
        },
        str(active["expires_utc"]),
        120,
    )
    result = execute_project_stream(
        source_root, context, checkpoint_root=paths.checkpoints
    )
    output = asdict(result)
    output["valid"] = result.status == "completed"
    return output


@_locked_when_apply
def transition_memory(
    root: Path,
    project_id: str,
    memory_id: str,
    target: str,
    evidence: Iterable[str],
    *,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    _, _, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    evidence_ids = tuple(sorted(set(map(str, evidence))))
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "project_id": project_id,
            "memory_id": memory_id,
            "target": target,
            "evidence": evidence_ids,
            "approval_required": True,
        }
    decision = _vault(paths, str(config["workspace_id"]), project_id).transition(
        memory_id, target, evidence=evidence_ids
    )
    append_event(_event_ledger(paths), "memory-transitioned", asdict(decision))
    return {"valid": True, "applied": True, **asdict(decision)}


@_locked_when_apply
def correct_memory(
    root: Path,
    project_id: str,
    previous_memory_id: str,
    memory_id: str,
    source: Path,
    *,
    title: str,
    summary: str,
    memory_type: str = "fact",
    confidence: float = 0.8,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    """Append a candidate correction; it supersedes prior memory only after certification."""
    paths = workspace_paths(root)
    config = _load_config(paths)
    _, project_record, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    project = _project_path(paths, project_record)
    source_path = source.resolve()
    if not source_path.is_file() or not _inside(source_path, project):
        raise ValueError(
            "memory correction source must be an existing file inside the active project"
        )
    source_bytes = source_path.read_bytes()
    if (
        not source_bytes
        or len(source_bytes) > 10 * 1024 * 1024
        or b"\x00" in source_bytes
    ):
        raise ValueError(
            "memory correction source must be nonempty bounded textual evidence"
        )
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            "memory correction source must be UTF-8 textual evidence"
        ) from error
    if len(source_text.strip()) < 16 or len(source_text.split()) < 3:
        raise ValueError("memory correction source lacks substantive textual evidence")
    vault = _vault(paths, str(config["workspace_id"]), project_id)
    latest = {record.memory_id: record for record in vault.latest_records()}
    if previous_memory_id not in latest:
        raise ValueError("memory correction target does not exist")
    previous_state = vault.lifecycle_state(previous_memory_id)
    if previous_state in {"revoked", "superseded"}:
        raise ValueError(
            f"memory correction target is {previous_state}; use a distinct approved reinstatement workflow"
        )
    if memory_id in latest:
        raise ValueError("memory correction ID already exists")
    if not title.strip() or not summary.strip():
        raise ValueError("memory correction title and summary are required")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("memory correction confidence must be between zero and one")
    preview = {
        "valid": True,
        "applied": False,
        "approval_required": True,
        "project_id": project_id,
        "memory_id": memory_id,
        "supersedes": [previous_memory_id],
        "source": source_path.relative_to(project).as_posix(),
        "source_validation": {
            "bytes": len(source_bytes),
            "utf8": True,
            "non_whitespace_characters": len(source_text.strip()),
        },
        "retrieval_activation": "disabled_until_correction_certification",
        "derived_rebuild_required": [
            "embedding",
            "graph",
            "retrieval_cache",
            "summary",
            "transfer_exports",
        ],
    }
    if not apply:
        return preview
    scope = ScopeEnvelope(**active["scope"])
    now = datetime.now(timezone.utc)
    relative_source = source_path.relative_to(project).as_posix()
    record = MemoryRecord(
        memory_id=memory_id,
        workspace_id=str(config["workspace_id"]),
        project_id=project_id,
        owner_id=actor_id,
        session_id=session_id,
        lease_id=scope.lease_id,
        title=title.strip(),
        memory_type=memory_type,
        summary=summary.strip(),
        source_artifact=relative_source,
        source_sha256=_sha(source_path),
        evidence_locator=relative_source,
        epistemic_status="observation",
        confidence=confidence,
        confidence_method="correction_evidence",
        classification="internal",
        acl=(project_id,),
        observed_at=now,
        effective_at=now,
        supersedes=(previous_memory_id,),
    )
    written = vault.append(record)
    event = append_event(
        _event_ledger(paths),
        "memory-correction-created",
        {
            "project_id": project_id,
            "memory_id": memory_id,
            "supersedes": previous_memory_id,
            "source_sha256": record.source_sha256,
            "retrieval_activation": "disabled_until_correction_certification",
            "derived_rebuild_required": preview["derived_rebuild_required"],
        },
    )
    return {
        **preview,
        "applied": True,
        "approval_required": False,
        "write": asdict(written),
        "event": event.as_posix(),
    }


def search_memory(
    root: Path,
    project_id: str,
    query: str,
    *,
    actor_id: str,
    session_id: str = "session_operator",
    limit: int = 5,
) -> dict[str, object]:
    from .memory_intelligence import MemoryCaller, rank_memories

    paths = workspace_paths(root)
    config = _load_config(paths)
    _, _, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    vault = _vault(paths, str(config["workspace_id"]), project_id)
    records = vault.retrieval_records(actor_id=actor_id)
    scope = active["scope"]
    caller = MemoryCaller(
        project_id,
        actor_id,
        str(scope["agent_id"]),
        team_id=str(scope["team_id"]) if scope.get("team_id") else None,
        user_id=str(scope["user_id"]) if scope.get("user_id") else None,
        task_id=str(scope["intent_id"]) if scope.get("intent_id") else None,
    )
    recall = rank_memories(query, records, caller=caller, max_items=limit)
    results = [
        {
            "memory_id": item.record.memory_id,
            "title": item.record.title,
            "summary": item.record.summary,
            "source_artifact": item.record.source_artifact,
            "source_sha256": item.record.source_sha256,
            "evidence_locator": item.record.evidence_locator,
            "revision": item.record.revision,
            "layer": item.record.layer,
            "score": item.score,
            "reasons": list(item.reasons),
        }
        for item in recall.selected
    ]
    return {
        "valid": True,
        "project_id": project_id,
        "query": query,
        "results": results,
        "selection_receipt_sha256": _stable(
            {
                "workspace_id": config["workspace_id"],
                "project_id": project_id,
                "lease_id": active["scope"]["lease_id"],
                "actor_id": actor_id,
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "selected": [
                    (item["memory_id"], item["revision"], item["source_sha256"])
                    for item in results
                ],
            }
        ),
        "rejected": list(recall.rejected),
    }


@_locked_when_apply
def maintain_memory(
    root: Path,
    project_id: str,
    *,
    source_root: Path,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    _, _, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "project_id": project_id,
            "approval_required": True,
            "effects": ["append index generation", "preserve previous generations"],
        }
    scope = ScopeEnvelope(**active["scope"])
    ProjectStreamContext, execute_project_stream = _project_stream_api()
    context = ProjectStreamContext(
        "memory_maintenance",
        str(config["workspace_id"]),
        project_id,
        scope.agent_id,
        scope.session_id,
        scope.intent_id,
        scope.correlation_id,
        PREFLIGHT,
        ("read_local", "write_workspace"),
        True,
        {
            "vault": _vault(paths, str(config["workspace_id"]), project_id),
            "next_safe_action": "review memory health evidence",
        },
        str(active["expires_utc"]),
        120,
    )
    result = execute_project_stream(
        source_root, context, checkpoint_root=paths.checkpoints
    )
    output = asdict(result)
    output["valid"] = result.status == "completed"
    return output


def memory_status(
    root: Path, project_id: str, *, actor_id: str, session_id: str = "session_operator"
) -> dict[str, object]:
    from collections import Counter
    from .memory_intelligence import PersistentWriteQueue

    paths = workspace_paths(root)
    config = _load_config(paths)
    _, _, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    vault = _vault(paths, str(config["workspace_id"]), project_id)
    records = vault.latest_records()
    retrieval = vault.retrieval_records(actor_id=actor_id)
    errors = sorted(
        {error for record in records for error in record.validation_errors()}
    )
    return {
        "valid": not errors,
        "project_id": project_id,
        "memory_root": vault.root.as_posix(),
        "record_count": len(records),
        "retrievable_count": len(retrieval),
        "validation_errors": errors,
        "layer_counts": dict(sorted(Counter(item.layer for item in records).items())),
        "lifecycle_counts": dict(
            sorted(
                Counter(
                    vault.lifecycle_state(item.memory_id) for item in records
                ).items()
            )
        ),
        "write_queue": PersistentWriteQueue(vault.root, project_id).health(),
        "index": vault.reconcile_indexes(),
    }


@_locked_when_apply
def reconcile_memory(
    root: Path,
    project_id: str,
    *,
    session_id: str = "session_operator",
    actor_id: str = "agent_operator",
    apply: bool = False,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    _, _, active = _require_active(paths, project_id, session_id)
    if actor_id != active["scope"]["agent_id"]:
        raise ValueError("memory actor does not own the active project lease")
    vault = _vault(paths, str(config["workspace_id"]), project_id)
    status = vault.reconcile_indexes()
    orphans = tuple(status["orphan_generations"])
    if not orphans:
        return {
            "valid": True,
            "applied": False,
            "project_id": project_id,
            "orphan_generations": [],
            "action": "none",
            "hard_delete": False,
        }
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "approval_required": True,
            "project_id": project_id,
            "orphan_generations": list(orphans),
            "action": "move_to_recoverable_quarantine",
            "hard_delete": False,
        }
    quarantine = (
        paths.quarantine
        / "memory"
        / project_id
        / f"orphans-{_stable({'orphans': orphans, 'time': _now()})[:16]}"
    )
    inventory = []
    with FileLock(vault.root / ".memory-control" / "vault.lock"):
        for generation in orphans:
            source = (
                vault.root / ".memory-control" / "index" / "generations" / generation
            )
            if not source.is_dir():
                raise ValueError(
                    f"orphan generation disappeared before reconciliation: {generation}"
                )
            files = tuple(item for item in sorted(source.rglob("*")) if item.is_file())
            for item in files:
                inventory.append(
                    {
                        "generation": generation,
                        "path": item.relative_to(source).as_posix(),
                        "sha256": _sha(item),
                        "bytes": item.stat().st_size,
                    }
                )
            destination = quarantine / generation
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        for item in inventory:
            destination = quarantine / str(item["generation"]) / str(item["path"])
            if not destination.is_file() or _sha(destination) != item["sha256"]:
                raise RuntimeError("memory orphan quarantine reconciliation failed")
        manifest = {
            "schema_version": "1.0",
            "operation": "recoverable_move_to_quarantine",
            "workspace_id": config["workspace_id"],
            "project_id": project_id,
            "orphan_generations": list(orphans),
            "inventory": inventory,
            "inventory_reconciled": True,
            "hard_delete": False,
            "created_utc": _now(),
        }
        _write_json_new(quarantine / "QUARANTINE_MANIFEST.json", manifest)
    after = vault.reconcile_indexes()
    if any(generation in after["orphan_generations"] for generation in orphans):
        raise RuntimeError("memory orphan remained authoritative after quarantine")
    event = append_event(
        _event_ledger(paths),
        "memory-orphans-quarantined",
        {
            "project_id": project_id,
            "quarantine": quarantine.relative_to(paths.root).as_posix(),
            "generations": orphans,
            "inventory_reconciled": True,
            "hard_delete": False,
        },
    )
    return {
        "valid": True,
        "applied": True,
        "project_id": project_id,
        "quarantine": quarantine.as_posix(),
        "orphan_generations": list(orphans),
        "inventory_count": len(inventory),
        "event": event.as_posix(),
        "hard_delete": False,
    }


def list_workflows(source_root: Path) -> dict[str, object]:
    definitions = json.loads(
        (source_root / "registry" / "project_stream_orchestrations.json").read_text(
            encoding="utf-8"
        )
    )
    bindings = json.loads(
        (source_root / "registry" / "project_stream_handlers.json").read_text(
            encoding="utf-8"
        )
    )
    handlers = {item["orchestration_id"]: item for item in bindings["workflows"]}
    workflows = []
    for item in definitions["orchestrations"]:
        binding = handlers.get(item["orchestration_id"], {})
        workflows.append(
            {
                "workflow_id": item["orchestration_id"],
                "title": item["title"],
                "status": binding.get("status", "missing"),
                "effects": binding.get("effects", []),
                "skills": item.get("skills", []),
                "deferred_capabilities": item.get("deferred_capabilities", []),
                "outcomes": item.get("outcomes", []),
            }
        )
    return {
        "valid": len(workflows) == 17
        and all(item["status"] == "executable" for item in workflows),
        "workflow_count": len(workflows),
        "workflows": workflows,
    }


def _request_path(
    paths: WorkspacePaths, project: Path, value: object, *, scope: str = "project"
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workflow path value must be a non-empty string")
    requested = Path(value)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(
            "workflow path must be relative and must not contain parent traversal"
        )
    base = project if scope == "project" else paths.root
    candidate = (base / requested).resolve()
    boundary = project if scope == "project" else paths.root
    if not _inside(candidate, boundary):
        raise ValueError("workflow path escapes its authorized root")
    return candidate


def _materialize_workflow_payload(
    workflow_id: str,
    raw: Mapping[str, object],
    *,
    paths: WorkspacePaths,
    project: Path,
    workspace_id: str,
    project_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = dict(raw)
    payload["ledger"] = _event_ledger(paths)
    payload["active_root"] = project
    payload["workspace_root"] = paths.root
    payload["shared_root"] = paths.shared_capabilities
    payload["staging_root"] = project / ".engineering-bootstrap" / "staging"
    payload["transaction_root"] = paths.tracking / "transactions" / project_id
    if workflow_id in {"memory_ingest_distill", "memory_maintenance"}:
        payload["vault"] = _vault(paths, workspace_id, project_id)
    if workflow_id in {"memory_ingest_distill", "continuous_improvement"}:
        sources = raw.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(
                "workflow sources must be a non-empty list of project-relative paths"
            )
        materialized = tuple(_request_path(paths, project, value) for value in sources)
        payload["sources"] = tuple(
            replace(
                SourceArtifact.from_path(path),
                locator=path.relative_to(project).as_posix(),
            )
            for path in materialized
        )
    project_path_fields = {"candidate", "staged_file", "recovery_candidate"}
    for field in project_path_fields:
        if field in raw:
            payload[field] = _request_path(paths, project, raw[field])
            if not _inside(payload[field], payload["staging_root"]):
                raise ValueError(
                    f"workflow {field} must remain below the framework-owned staging root"
                )
    if workflow_id == "cross_project_transfer":
        package_raw = raw.get("package")
        if not isinstance(package_raw, Mapping):
            raise ValueError("cross-project transfer requires a package object")
        registry = _load_registry(paths)
        source_record = _project_by_id(
            registry, str(package_raw.get("source_project_id", ""))
        )
        if str(source_record["project_id"]) == project_id:
            raise ValueError(
                "cross-project transfer source must differ from the active destination project"
            )
        source_project = _project_path(paths, source_record)
        payload["source"] = _request_path(paths, source_project, raw.get("source"))
        payload["destination"] = _request_path(paths, project, raw.get("destination"))
        if package_raw.get("destination_project_id") != project_id:
            raise ValueError("transfer destination must equal the active project")
    else:
        for field in ("source", "destination"):
            if field in raw:
                payload[field] = _request_path(paths, project, raw[field])
    if "candidates" in raw:
        if not isinstance(raw["candidates"], list):
            raise ValueError("workflow candidates must be a list")
        payload["candidates"] = tuple(
            _request_path(paths, project, value) for value in raw["candidates"]
        )
    if "quarantine_root" in raw:
        payload["quarantine_root"] = _request_path(
            paths, project, raw["quarantine_root"], scope="workspace"
        )
        if not _inside(payload["quarantine_root"], paths.quarantine):
            raise ValueError(
                "workflow quarantine path must remain below repo_quarantine"
            )
    if "package" in raw:
        if not isinstance(raw["package"], Mapping):
            raise ValueError("workflow transfer package must be an object")
        package = dict(raw["package"])
        for field in ("provenance", "assumptions", "tests"):
            package[field] = tuple(map(str, package.get(field, ())))
        payload["package"] = TransferPackage(**package)
    payload["repository_state"] = dict(raw.get("repository_state", {}))
    payload["next_safe_action"] = str(
        raw.get("next_safe_action", "review workflow receipt")
    )
    return payload


def _validate_workflow_payload_shape(
    workflow_id: str, payload: Mapping[str, object]
) -> None:
    required: dict[str, dict[str, type | tuple[type, ...]]] = {
        "agent_create_validate": {"specification": Mapping},
        "chaos_resilience_cycle": {"experiments": list},
        "cross_project_transfer": {
            "source": str,
            "destination": str,
            "package": Mapping,
        },
        "guarded_change": {
            "staged_file": str,
            "destination": str,
            "quarantine_root": str,
            "expected_source_sha256": str,
            "evidence": Mapping,
        },
        "incident_diagnose_recover": {
            "recovery_candidate": str,
            "destination": str,
            "quarantine_root": str,
            "expected_source_sha256": str,
            "evidence": Mapping,
        },
        "memory_ingest_distill": {"sources": list},
        "memory_maintenance": {},
        "continuous_improvement": {"sources": list},
        "nightly_project_health": {"metrics": Mapping},
        "safe_cleanup": {"candidates": list, "quarantine_root": str},
        "shared_capability_promote": {
            "candidate": str,
            "expected_source_sha256": str,
            "evidence": Mapping,
        },
        "workstream_plan_dispatch": {"workstreams": list, "resource_snapshot": Mapping},
    }
    contract = required.get(workflow_id)
    if contract is None:
        raise ValueError("workflow has no safe JSON payload adapter")
    errors = []
    for field, expected in contract.items():
        if field not in payload:
            errors.append(f"missing:{field}")
        elif not isinstance(payload[field], expected):
            errors.append(f"invalid_type:{field}")
    for field in ("sources", "experiments", "candidates", "workstreams"):
        if field in payload and isinstance(payload[field], list) and not payload[field]:
            errors.append(f"empty:{field}")
    if errors:
        raise ValueError(
            "workflow payload contract failed: " + ", ".join(sorted(errors))
        )


@_locked_when_apply
def run_workflow_request(
    root: Path, request_path: Path, *, source_root: Path, apply: bool = False
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("schema_version") != "1.0":
        raise ValueError("workflow request schema_version must equal 1.0")
    workflow_id = str(request.get("workflow_id", ""))
    blocked_direct = {
        "workspace_bootstrap",
        "project_onboard",
        "project_switch",
        "project_pause_resume",
        "project_close",
    }
    if workflow_id in blocked_direct:
        raise ValueError(
            f"use the dedicated workspace/project command for {workflow_id}"
        )
    listing = list_workflows(source_root)
    workflow = next(
        (item for item in listing["workflows"] if item["workflow_id"] == workflow_id),
        None,
    )
    if workflow is None or workflow["status"] != "executable":
        raise ValueError("workflow is unknown or not executable")
    project_id = str(request.get("project_id", ""))
    session_id = str(request.get("session_id", ""))
    _, project_record, active = _require_active(paths, project_id, session_id)
    project = _project_path(paths, project_record)
    idempotency_key = str(request.get("idempotency_key", ""))
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,127}", idempotency_key):
        raise ValueError("workflow idempotency_key is missing or invalid")
    approved_effects = tuple(sorted(set(map(str, request.get("approved_effects", ())))))
    missing_effects = sorted(set(workflow["effects"]) - set(approved_effects))
    if missing_effects:
        if apply:
            append_event(
                _event_ledger(paths),
                "workflow-policy-denied",
                {
                    "workflow_id": workflow_id,
                    "project_id": project_id,
                    "session_id": session_id,
                    "requested_effects": list(approved_effects),
                    "missing_effects": missing_effects,
                },
            )
        raise ValueError(
            "workflow effects are not fully approved: " + ", ".join(missing_effects)
        )
    request_hash = _stable(request)
    receipt_path = paths.project_state / project_id / "runs" / f"{idempotency_key}.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("request_sha256") != request_hash:
            raise ValueError("idempotency key was already used for a different request")
        return {
            "valid": receipt.get("result", {}).get("status") == "completed",
            "replayed": True,
            "receipt": receipt,
        }
    if not apply:
        return {
            "valid": True,
            "applied": False,
            "approval_required": True,
            "workflow_id": workflow_id,
            "project_id": project_id,
            "effects": list(approved_effects),
            "request_sha256": request_hash,
            "outcomes": workflow["outcomes"],
        }
    raw_payload = request.get("payload", {})
    if not isinstance(raw_payload, Mapping):
        raise ValueError("workflow payload must be an object")
    _validate_workflow_payload_shape(workflow_id, raw_payload)
    payload = _materialize_workflow_payload(
        workflow_id,
        raw_payload,
        paths=paths,
        project=project,
        workspace_id=str(config["workspace_id"]),
        project_id=project_id,
    )
    scope = ScopeEnvelope(**active["scope"])
    payload["lease_id"] = scope.lease_id
    timeout_seconds = request.get("timeout_seconds", 120)
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 3600
    ):
        raise ValueError(
            "workflow timeout_seconds must be an integer between 1 and 3600"
        )
    lease_expiry = datetime.fromisoformat(str(active["expires_utc"]))
    if datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds) > lease_expiry:
        raise ValueError("workflow timeout budget exceeds the remaining project lease")
    ProjectStreamContext, execute_project_stream = _project_stream_api()
    context = ProjectStreamContext(
        workflow_id,
        str(config["workspace_id"]),
        project_id,
        scope.agent_id,
        scope.session_id,
        scope.intent_id,
        scope.correlation_id,
        PREFLIGHT,
        approved_effects,
        True,
        payload,
        str(active["expires_utc"]),
        timeout_seconds,
    )
    result = execute_project_stream(
        source_root, context, checkpoint_root=paths.checkpoints
    )
    result_value = asdict(result)
    receipt = {
        "schema_version": "1.0",
        "idempotency_key": idempotency_key,
        "request_sha256": request_hash,
        "workflow_id": workflow_id,
        "workspace_id": config["workspace_id"],
        "project_id": project_id,
        "lease_id": scope.lease_id,
        "approved_effects": list(approved_effects),
        "handler_status": workflow["status"],
        "result": result_value,
        "checkpoint_sha256": {
            checkpoint: _sha(Path(checkpoint))
            for checkpoint in result.checkpoints
            if Path(checkpoint).is_file()
        },
        "created_utc": _now(),
    }
    _write_json_new(receipt_path, receipt)
    append_event(
        _event_ledger(paths),
        "workflow-finished",
        {
            "receipt": receipt_path.relative_to(paths.root).as_posix(),
            "request_sha256": request_hash,
            "status": result.status,
        },
    )
    return {
        "valid": result.status == "completed",
        "applied": True,
        "replayed": False,
        "receipt": receipt,
    }


def workspace_status(
    root: Path, *, source_root: Path | None = None
) -> dict[str, object]:
    paths = workspace_paths(root)
    errors: list[str] = []
    try:
        config = _load_config(paths)
        registry = _load_registry(paths)
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        return {"valid": False, "errors": [str(error)]}
    for name in ("projects", "tracking", "quarantine", "shared_capabilities"):
        if not getattr(paths, name).is_dir():
            errors.append(f"missing_workspace_root:{name}")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    project_results = []
    for item in registry["projects"]:
        project_id = str(item.get("project_id", ""))
        relative = str(item.get("path", ""))
        if project_id in seen_ids:
            errors.append(f"duplicate_project_id:{project_id}")
        if relative in seen_paths:
            errors.append(f"duplicate_project_path:{relative}")
        seen_ids.add(project_id)
        seen_paths.add(relative)
        try:
            project = _project_path(paths, item)
            if not project.is_dir():
                raise ValueError("project directory missing")
            local_record = project / ".engineering-bootstrap" / "project-record.json"
            if not local_record.is_file() or _sha(local_record) != item.get(
                "project_record_sha256"
            ):
                raise ValueError("project record hash drift")
            binding_path = project / ".engineering-bootstrap" / "workspace-binding.json"
            if not binding_path.is_file() or _sha(binding_path) != item.get(
                "workspace_binding_sha256"
            ):
                raise ValueError("workspace binding hash drift")
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            if (
                binding.get("workspace_id") != config["workspace_id"]
                or binding.get("project_id") != project_id
                or binding.get("cross_project_access") != "deny"
            ):
                raise ValueError("workspace binding identity drift")
            if not _memory_root(paths, project_id).is_dir():
                raise ValueError("project memory root missing")
            checked = (
                project_check(project, source_root=source_root)
                if source_root
                else {"valid": True, "errors": []}
            )
            if not checked.get("valid"):
                raise ValueError(
                    "project check failed: " + ", ".join(checked.get("errors", []))
                )
            project_results.append({"project_id": project_id, "valid": True})
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"project_invalid:{project_id}:{error}")
            project_results.append(
                {"project_id": project_id, "valid": False, "error": str(error)}
            )
    try:
        active_sessions = _active_sessions(paths)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"session_projection_invalid:{error}")
        active_sessions = ()
    active_registry = [
        item for item in registry["projects"] if item.get("state") == "active"
    ]
    for active in active_sessions:
        if active.get("project_id") not in seen_ids:
            errors.append("active_session_project_not_registered")
        else:
            bound = _project_by_id(registry, str(active["project_id"]))
            if (
                active.get("writable_roots") != [bound["path"]]
                or active.get("memory_root") != bound["memory_root"]
            ):
                errors.append("active_session_root_binding_drift")
            try:
                if datetime.fromisoformat(str(active["expires_utc"])) <= datetime.now(
                    timezone.utc
                ):
                    errors.append("active_session_lease_expired")
            except (KeyError, ValueError):
                errors.append("active_session_expiry_invalid")
    active_project_ids = {str(item.get("project_id")) for item in active_sessions}
    registry_active_ids = {str(item.get("project_id")) for item in active_registry}
    if active_project_ids != registry_active_ids:
        errors.append("active_session_registry_projection_drift")
    if not active_sessions and active_registry:
        errors.append("registry_has_active_project_without_active_session")
    try:
        pending_operations = _pending_workspace_operations(paths)
        if pending_operations:
            errors.append(
                "incomplete_workspace_operation:" + ",".join(pending_operations)
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        pending_operations = ()
        errors.append(f"workspace_operation_journal_invalid:{error}")
    return {
        "valid": not errors,
        "workspace_id": config["workspace_id"],
        "root": paths.root.as_posix(),
        "drop_location": paths.projects.as_posix(),
        "tracking": paths.tracking.as_posix(),
        "registered_count": len(registry["projects"]),
        "active_session_count": len(active_sessions),
        "active_project_ids": sorted(active_project_ids),
        "pending_operation_ids": list(pending_operations),
        "active_project_id": next(iter(active_project_ids))
        if len(active_project_ids) == 1
        else None,
        "projects": project_results,
        "errors": errors,
    }


def workspace_monitor(root: Path, *, source_root: Path) -> dict[str, object]:
    """Compose live workspace, lease, memory, budget, and integration health without mutation."""
    status = workspace_status(root, source_root=source_root)
    paths = workspace_paths(root)
    if not status.get("valid"):
        return {
            "valid": False,
            "workspace": status,
            "memory": [],
            "integrations": {"valid": False, "errors": ["workspace invalid"]},
        }
    config = _load_config(paths)
    registry = _load_registry(paths)
    memory = []
    for record in registry["projects"]:
        project_id = str(record["project_id"])
        vault = _vault(paths, str(config["workspace_id"]), project_id)
        records = vault.latest_records()
        memory.append(
            {
                "project_id": project_id,
                "record_count": len(records),
                "bytes": sum(
                    path.stat().st_size
                    for path in vault.root.rglob("*")
                    if path.is_file()
                ),
                "index": vault.reconcile_indexes(),
            }
        )
    integrations = validate_integrations(source_root, smoke=True)
    return {
        "valid": status["valid"]
        and integrations["valid"]
        and all(not item["index"]["orphan_generations"] for item in memory),
        "workspace": status,
        "lease_policy": dict(config["leases"]),
        "memory": memory,
        "integrations": integrations,
        "recovery": "run workspace rebuild --apply only after reviewing any projection or operation-journal drift",
    }


@_locked_when_apply
def rebuild_workspace_projections(
    root: Path,
    *,
    apply: bool = False,
    fault_injector=None,
) -> dict[str, object]:
    paths = workspace_paths(root)
    config = _load_config(paths)
    event_paths = (
        tuple(sorted(paths.events.glob("*.json"))) if paths.events.is_dir() else ()
    )
    if not event_paths:
        raise ValueError("workspace event ledger is empty")
    ledger_validation = validate_event_ledger(paths.events)
    if not ledger_validation["valid"]:
        raise ValueError(
            "workspace event ledger integrity failure: "
            + "; ".join(ledger_validation["errors"])
        )
    projects: dict[str, dict[str, object]] = {}
    sessions: dict[str, dict[str, object]] = {}
    expected_sequence = 1
    relevant_updates = 0
    intent_ids: set[str] = set()
    completed_ids: set[str] = set()
    for path, event in zip(event_paths, ledger_validation["events"], strict=True):
        if event.get("sequence") != expected_sequence:
            raise ValueError("workspace event sequence is not contiguous")
        payload = event.get("payload")
        if not isinstance(payload, Mapping) or event.get("payload_sha256") != _stable(
            payload
        ):
            raise ValueError(f"workspace event integrity failure: {path.name}")
        kind = event.get("kind")
        operation_id = str(payload.get("operation_id", ""))
        if kind == "workspace-operation-intent" and operation_id:
            intent_ids.add(operation_id)
        elif kind == "workspace-operation-recovered" and operation_id:
            completed_ids.add(operation_id)
        elif kind == "project-admitted":
            project = payload.get("project")
            if not isinstance(project, Mapping):
                raise ValueError("project admission event is malformed")
            project_id = str(project.get("project_id", ""))
            if project_id in projects:
                raise ValueError(f"duplicate project admission event: {project_id}")
            projects[project_id] = dict(project)
            relevant_updates += 1
        elif kind in {"project-activated", "session-created"}:
            if operation_id:
                completed_ids.add(operation_id)
            session = payload.get("active_session")
            if (
                not isinstance(session, Mapping)
                or str(session.get("project_id", "")) not in projects
            ):
                raise ValueError(
                    "project activation event references an unknown project"
                )
            session_id = str(session.get("scope", {}).get("session_id", ""))
            if not session_id:
                raise ValueError("project activation event has no session identity")
            sessions[session_id] = dict(session)
            active_ids = {
                str(item["project_id"])
                for item in sessions.values()
                if item.get("status") == "active"
            }
            for project in projects.values():
                project["state"] = (
                    "active"
                    if project["project_id"] in active_ids
                    else (
                        "registered"
                        if project.get("state") == "active"
                        else project.get("state")
                    )
                )
            relevant_updates += 1
        elif kind in {
            "project-released",
            "session-released",
            "session-revoked",
            "session-expired",
        }:
            if operation_id:
                completed_ids.add(operation_id)
            project_id = str(payload.get("project_id", ""))
            if project_id not in projects:
                raise ValueError("project release event references an unknown project")
            session_id = str(payload.get("session_id", ""))
            if session_id in sessions:
                status = {
                    "session-revoked": "revoked",
                    "session-expired": "expired",
                }.get(str(kind), "released")
                sessions[session_id] = {
                    **sessions[session_id],
                    "status": status,
                    str(payload.get("status_time_field", f"{status}_utc")): payload.get(
                        "status_time", event["created_utc"]
                    ),
                }
            active_ids = {
                str(item["project_id"])
                for item in sessions.values()
                if item.get("status") == "active"
            }
            if project_id not in active_ids:
                projects[project_id]["state"] = "registered"
            relevant_updates += 1
        elif kind in {"project-lease-renewed", "session-renewed"}:
            session_id = str(payload.get("session_id", ""))
            if (
                session_id not in sessions
                or sessions[session_id].get("status") != "active"
            ):
                raise ValueError("session renewal event references no active session")
            sessions[session_id] = {
                **sessions[session_id],
                "expires_utc": payload["new_expiry"],
                "renewed_utc": payload.get("renewed_utc", event["created_utc"]),
            }
            relevant_updates += 1
        elif kind in {"project-pause", "project-resume", "project-archive"}:
            project_id = str(payload.get("project_id", ""))
            if project_id not in projects:
                raise ValueError(
                    "project lifecycle event references an unknown project"
                )
            projects[project_id]["state"] = str(payload.get("to", ""))
            relevant_updates += 1
        expected_sequence += 1
    registry = {
        "schema_version": "1.0",
        "workspace_id": config["workspace_id"],
        "revision": 1 + relevant_updates,
        "projects": sorted(projects.values(), key=lambda item: str(item["project_id"])),
        "updated_utc": str(ledger_validation["events"][-1]["created_utc"]),
    }
    preview = {
        "valid": True,
        "applied": False,
        "approval_required": True,
        "event_count": len(event_paths),
        "registered_count": len(projects),
        "active_project_ids": sorted(
            {
                str(item["project_id"])
                for item in sessions.values()
                if item.get("status") == "active"
            }
        ),
        "active_session_count": sum(
            item.get("status") == "active" for item in sessions.values()
        ),
        "registry_sha256": _stable(registry),
        "pending_operation_ids": sorted(intent_ids - completed_ids),
    }
    if not apply:
        return preview
    source_head = str(ledger_validation["head_sha256"])
    transaction = paths.tracking / "rebuild-transactions" / source_head
    prepared = transaction / "prepared"
    rollback = transaction / "rollback"
    transaction.mkdir(parents=True, exist_ok=True)
    prepared.mkdir(parents=True, exist_ok=True)
    rollback.mkdir(parents=True, exist_ok=True)
    registry_bytes = (json.dumps(registry, indent=2) + "\n").encode("utf-8")
    prepared_registry = prepared / REGISTRY_NAME
    if not prepared_registry.exists():
        _write_new(prepared_registry, registry_bytes)
    prepared_sessions = prepared / "sessions"
    prepared_sessions.mkdir(parents=True, exist_ok=True)
    for session_id, session in sessions.items():
        target = prepared_sessions / f"{session_id}.json"
        if not target.exists():
            _write_new(
                target,
                (json.dumps(session, indent=2, default=str) + "\n").encode("utf-8"),
            )
    checkpoint = {
        "schema_version": "1.0",
        "status": "prepared",
        "source_event_head": source_head,
        "processed_events": len(event_paths),
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "session_sha256": {
            path.name: _sha(path) for path in sorted(prepared_sessions.glob("*.json"))
        },
    }
    checkpoint_path = transaction / "0001-prepared.json"
    if not checkpoint_path.exists():
        _write_json_new(checkpoint_path, checkpoint)
    else:
        stored_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if stored_checkpoint.get("source_event_head") != source_head:
            raise ValueError(
                "projection rebuild checkpoint belongs to a different event head"
            )
        if stored_checkpoint.get("registry_sha256") != _sha(prepared_registry):
            raise ValueError("projection rebuild checkpoint registry hash mismatch")
        actual_session_hashes = {
            path.name: _sha(path) for path in sorted(prepared_sessions.glob("*.json"))
        }
        if stored_checkpoint.get("session_sha256") != actual_session_hashes:
            raise ValueError("projection rebuild checkpoint session hashes mismatch")
    if validate_event_ledger(paths.events)["head_sha256"] != source_head:
        raise ValueError("workspace event head changed during projection rebuild")
    _validate_control(registry, "workspace-registry.schema.json")
    for session in sessions.values():
        _validate_control(session, "active-session.schema.json")
    originals: dict[Path, Path] = {}
    targets = [
        paths.registry,
        paths.tracking / REGISTRY_SEAL_NAME,
        *(_session_path(paths, identifier) for identifier in sorted(sessions)),
    ]
    for target in targets:
        if target.is_file():
            relative = target.relative_to(paths.tracking).as_posix().replace("/", "--")
            preserved = rollback / relative
            if not preserved.exists():
                _write_new(preserved, target.read_bytes())
            originals[target] = preserved
    try:
        if fault_injector:
            fault_injector("before_registry_switch")
        registry_next = paths.registry.with_name(
            f".{paths.registry.name}.{source_head[:12]}.prepared"
        )
        if not registry_next.exists():
            _write_new(registry_next, prepared_registry.read_bytes())
        os.replace(registry_next, paths.registry)
        seal_next = (paths.tracking / REGISTRY_SEAL_NAME).with_name(
            f".{REGISTRY_SEAL_NAME}.{source_head[:12]}.prepared"
        )
        if not seal_next.exists():
            _write_new(seal_next, (_sha(paths.registry) + "\n").encode("utf-8"))
        os.replace(seal_next, paths.tracking / REGISTRY_SEAL_NAME)
        if fault_injector:
            fault_injector("after_registry_switch")
        for index, session_id in enumerate(sorted(sessions), start=1):
            session_next = _session_path(paths, session_id).with_name(
                f".{session_id}.{source_head[:12]}.prepared"
            )
            if not session_next.exists():
                _write_new(
                    session_next,
                    (prepared_sessions / f"{session_id}.json").read_bytes(),
                )
            os.replace(session_next, _session_path(paths, session_id))
            if fault_injector:
                fault_injector(f"after_session_switch_{index}")
    except BaseException as error:
        for target, preserved in originals.items():
            restore = target.with_name(f".{target.name}.{source_head[:12]}.rollback")
            if restore.exists():
                raise RuntimeError(
                    f"projection rollback collision: {restore}"
                ) from error
            _write_new(restore, preserved.read_bytes())
            os.replace(restore, target)
        _write_json_new(
            transaction / f"0002-rolled-back-{_stable(str(error))[:12]}.json",
            {
                "schema_version": "1.0",
                "status": "rolled_back",
                "source_event_head": source_head,
                "error": f"{type(error).__name__}: {error}",
                "restored": [path.as_posix() for path in originals],
            },
        )
        raise
    _write_json_new(
        transaction / "0002-committed.json",
        {
            "schema_version": "1.0",
            "status": "committed",
            "source_event_head": source_head,
            "registry_sha256": _sha(paths.registry),
            "session_sha256": {
                path.name: _sha(path) for path in sorted(paths.sessions.glob("*.json"))
            },
        },
    )
    for operation_id in sorted(intent_ids - completed_ids):
        append_event(
            _event_ledger(paths),
            "workspace-operation-recovered",
            {
                "operation_id": operation_id,
                "resolution": "rolled_back_to_last_committed_event_projection",
                "hard_delete": False,
            },
        )
    completed = append_event(
        _event_ledger(paths),
        "workspace-rebuild-completed",
        {
            "source_event_head": source_head,
            "processed_events": len(event_paths),
            "registry_sha256": _sha(paths.registry),
            "transaction": transaction.relative_to(paths.root).as_posix(),
        },
    )
    _refresh_dashboard(paths, registry)
    return {
        **preview,
        "applied": True,
        "approval_required": False,
        "transaction": transaction.as_posix(),
        "completion_event": completed.as_posix(),
    }
