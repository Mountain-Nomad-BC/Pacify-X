"""Proposal-first project commissioning with collision-safe adoption."""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Mapping

from .intake import inspect_existing_project
from .contracts import validate_instance
from .event_ledger import append_chained_event, validate_event_ledger
from .paths import framework_root
from .project_management import project_management_files, validate_project_management
from .release_identity import authoritative_version


AGENTS = """# Repository engineering contract

- Begin with `PROJECT_MANAGEMENT.md` and `.engineering-bootstrap/AI_ASSISTANT.md`.
- Keep startup bounded: inspect compact metadata before loading a selected skill body.
- Preserve existing owners and use only admitted capabilities.
- Declare effects and obtain approval before writes, installs, network access, services, migrations, privileged actions, or destructive work.
- Checkpoint material steps and retain current evidence for completion claims.
- Quarantine instead of deleting.
- Run `engineering-bootstrap project-check --project .` before declaring bootstrap changes complete.
"""

CODEX_CONFIG = """# Project-scoped Codex settings. Provider, credentials, model, and global profile stay user-owned.
project_doc_max_bytes = 32768

[agents]
max_concurrent_threads_per_session = 2
"""

AI_ASSISTANT = """# Model-neutral assistant entry point

1. Read `PROJECT_MANAGEMENT.md`, this file, and the repository's existing instruction owners.
2. Run `engineering-bootstrap validate`, `project-check --project .`, and `startup --project .`; stop closed on failure.
3. Keep startup metadata-only. Run `working-set --goal "<goal>"`, select at most three candidates, then `hydrate --skill <id>` for one required body.
4. Declare effects, approval boundaries, postconditions, rollback, and evidence before execution.
5. Update project-management state at material checkpoints. Verify observable outcomes independently and release selected task context.
6. Preserve existing owners and quarantine cleanup candidates; never hard-delete.
"""

AI_CONFIG = """schema_version = "1.0"
entrypoint = ".engineering-bootstrap/AI_ASSISTANT.md"
repository_contract = ".engineering-bootstrap/AGENTS.md"
project_management = "PROJECT_MANAGEMENT.md"
model_agnostic = true
metadata_only_at_startup = true
max_selected_capabilities = 3
cross_project_default = "deny"
cleanup_mode = "quarantine_only"
"""

VSCODE_SETTINGS = {
    "chatgpt.commentCodeLensEnabled": True,
    "chatgpt.openOnStartup": False,
    "chatgpt.followUpQueueMode": "queue",
    "files.watcherExclude": {
        "**/raw/**": True,
        "**/quarantine/**": True,
        "**/evidence/**": True,
        "**/planning/inventory/**": True,
        "**/.engineering-bootstrap/cache/**": True,
    },
    "search.exclude": {
        "**/raw/**": True,
        "**/quarantine/**": True,
        "**/evidence/**": True,
    },
}

VSCODE_TASKS = {
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Bootstrap: validate installation",
            "type": "shell",
            "command": "engineering-bootstrap validate",
            "problemMatcher": [],
        },
        {
            "label": "Bootstrap: check project",
            "type": "shell",
            "command": "engineering-bootstrap project-check --project .",
            "problemMatcher": [],
        },
        {
            "label": "Bootstrap: bounded startup",
            "type": "shell",
            "command": "engineering-bootstrap startup --project .",
            "problemMatcher": [],
        },
        {
            "label": "Bootstrap: doctor",
            "type": "shell",
            "command": "engineering-bootstrap doctor",
            "problemMatcher": [],
        },
    ],
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _framework_binding(source: Path) -> dict[str, object]:
    version = authoritative_version(source)
    certificate = source / "evidence" / f"release-certification-{version}.json"
    revocation = source / "evidence" / f"release-revocation-{version}.json"
    return {
        "version": version,
        "certificate": certificate.relative_to(source).as_posix()
        if certificate.is_file()
        else None,
        "certificate_sha256": _sha256(certificate.read_bytes())
        if certificate.is_file()
        else None,
        "revoked": revocation.is_file(),
        "revocation_sha256": _sha256(revocation.read_bytes())
        if revocation.is_file()
        else None,
    }


def _project_toml(mode: str) -> str:
    map_required = "true" if mode == "existing" else "false"
    return f'''[project]\nmode = "{mode}"\nframework = "engineering-loop-bootstrap"\nproject_management = "PROJECT_MANAGEMENT.md"\n\n[startup]\nmetadata_only = true\nmax_selected_capabilities = 3\n\n[project_map]\nrequired = {map_required}\nmetadata_first = true\nrefresh_after_accepted_changes = true\n\n[lifecycle]\ncheckpoint_after_each_step = true\nunload_after_step = true\nretry_requires_new_evidence = true\ncleanup_mode = "quarantine_only"\n'''


def _bootstrap_manifest(mode: str) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": "1.0",
                "mode": mode,
                "profile": "default",
                "stack": "project-owned",
                "questionnaire": {
                    "stack": "discover_or_select",
                    "deployment": "explicit",
                    "sensitive_data": "policy_gated",
                },
                "baselines": {
                    "security": True,
                    "tests": True,
                    "evidence": True,
                    "accessibility": True,
                },
                "model_routing": "capability_contract",
                "tool_installation": "approval_required",
                "startup": {
                    "metadata_only": True,
                    "maximum_selected_skills": 3,
                    "skill_bodies_copied_to_project": False,
                },
                "project_management": {
                    "entrypoint": "PROJECT_MANAGEMENT.md",
                    "state": ".engineering-bootstrap/project-management/state.json",
                },
                "prompts": {
                    "new": ".engineering-bootstrap/prompts/new-project.md",
                    "existing": ".engineering-bootstrap/prompts/existing-project.md",
                },
                "deployment_guardrails": [
                    "tests_pass",
                    "security_review",
                    "evidence_current",
                    "rollback_viable",
                    "explicit_approval",
                ],
            },
            indent=2,
        )
        + "\n"
    ).encode()


def _skill_registry(source: Path, mode: str) -> bytes:
    catalog = tomllib.loads(
        (source / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    records = []
    for item in catalog.get("skills", ()):
        status = str(item.get("status", "candidate"))
        if status not in {"active", "admitted"}:
            continue
        body = Path(str(item["body"]))
        content = (source / body).read_bytes()
        records.append(
            {
                "id": str(item["id"]),
                "body": body.as_posix(),
                "status": status,
                "sha256": _sha256(content),
                "bytes": len(content),
                "source": "installed_framework",
            }
        )
    return (
        json.dumps(
            {
                "schema_version": "1.0",
                "mode": mode,
                "canonical_runtime_registry": "installed_framework",
                "loading_rule": "metadata_only_at_startup_body_after_selection",
                "max_selected_skills": 3,
                "skill_bodies_copied_to_project": False,
                "skills": sorted(records, key=lambda item: item["id"]),
            },
            indent=2,
        )
        + "\n"
    ).encode()


def _project_record(
    project: Path, mode: str, inventory: Mapping[str, object] | None
) -> bytes:
    slug = (
        re.sub(r"[^A-Za-z0-9_-]+", "-", project.resolve().name).strip("-") or "project"
    )
    owners = list(map(str, (inventory or {}).get("canonical_owner_candidates", ())))
    record = {
        "project_id": f"prj_{slug}",
        "name": project.resolve().name,
        "state": "registered",
        "classification": "internal",
        "repositories": [
            {
                "repository_id": f"repo_{slug}",
                "logical_root": ".",
                "role": "application",
            }
        ],
        "owners": owners,
        "policy_overlay": None,
        "memory_namespace": f"project/prj_{slug}",
        "cross_project_access": "deny",
        "required_gates": ["constitution", "boundary", "tests", "outcome", "evidence"],
        "commissioning_mode": mode,
    }
    return (json.dumps(record, indent=2) + "\n").encode()


def scaffold_files(
    mode: str,
    project: Path | None = None,
    source_root: Path | None = None,
    inventory: Mapping[str, object] | None = None,
    questionnaire: Mapping[str, object] | None = None,
) -> dict[Path, bytes]:
    source = (source_root or framework_root()).resolve()
    target = (project or Path("project")).resolve()
    if mode not in {"new", "existing"}:
        raise ValueError("mode must be new or existing")
    prompts = source / "bootstrap" / "prompts"
    files: dict[Path, bytes] = {
        Path("AGENTS.md"): AGENTS.encode(),
        Path(
            "AI_ASSISTANT.md"
        ): b"# Assistant entry point\n\nFollow `.engineering-bootstrap/AI_ASSISTANT.md`, `PROJECT_MANAGEMENT.md`, and existing repository instructions.\n",
        Path(
            "CLAUDE.md"
        ): b"# Assistant instructions\n\nFollow `.engineering-bootstrap/AI_ASSISTANT.md` and existing repository instructions.\n",
        Path(
            "GEMINI.md"
        ): b"# Assistant instructions\n\nFollow `.engineering-bootstrap/AI_ASSISTANT.md` and existing repository instructions.\n",
        Path(".ai/assistant.toml"): AI_CONFIG.encode(),
        Path(
            ".github/copilot-instructions.md"
        ): b"# Repository assistant contract\n\nFollow `.engineering-bootstrap/AI_ASSISTANT.md` and existing repository instructions.\n",
        Path(".codex/config.toml"): CODEX_CONFIG.encode(),
        Path(".vscode/settings.json"): (
            json.dumps(VSCODE_SETTINGS, indent=2) + "\n"
        ).encode(),
        Path(".vscode/tasks.json"): (
            json.dumps(VSCODE_TASKS, indent=2) + "\n"
        ).encode(),
        Path(".engineering-bootstrap/AGENTS.md"): AGENTS.encode(),
        Path(".engineering-bootstrap/AI_ASSISTANT.md"): AI_ASSISTANT.encode(),
        Path(".engineering-bootstrap/project.toml"): _project_toml(mode).encode(),
        Path(".engineering-bootstrap/bootstrap-manifest.json"): _bootstrap_manifest(
            mode
        ),
        Path(".engineering-bootstrap/project-registry.json"): _skill_registry(
            source, mode
        ),
        Path(".engineering-bootstrap/project-record.json"): _project_record(
            target, mode, inventory
        ),
        Path(".engineering-bootstrap/prompts/new-project.md"): (
            prompts / "NEW_PROJECT_PROMPT.md"
        ).read_bytes(),
        Path(".engineering-bootstrap/prompts/existing-project.md"): (
            prompts / "EXISTING_PROJECT_PROMPT.md"
        ).read_bytes(),
        Path(".engineering-bootstrap/vscode.settings.json"): (
            json.dumps(VSCODE_SETTINGS, indent=2) + "\n"
        ).encode(),
        Path(".engineering-bootstrap/vscode.tasks.json"): (
            json.dumps(VSCODE_TASKS, indent=2) + "\n"
        ).encode(),
        Path(
            ".engineering-bootstrap/SECURITY_BASELINE.md"
        ): b"# Security baseline\n\nLeast privilege, secret redaction, dependency review, and explicit mutation approval are required.\n",
        Path(
            ".engineering-bootstrap/TEST_BASELINE.md"
        ): b"# Test baseline\n\nNew capabilities require positive, negative, integration, and effect-boundary tests plus the repository's own validation commands.\n",
        Path(
            ".engineering-bootstrap/EVIDENCE_BASELINE.md"
        ): b"# Evidence baseline\n\nCompletion requires deterministic, sanitized, current, task-scoped evidence and independent outcome verification.\n",
        Path(
            ".engineering-bootstrap/DEPLOYMENT_GUARDRAILS.md"
        ): b"# Deployment guardrails\n\nDeployment is blocked without tests, security review, current evidence, viable rollback, and explicit approval.\n",
    }
    files.update(project_management_files(target, mode, inventory, questionnaire))
    profile_root = source / "bootstrap" / "profiles"
    for profile in sorted(profile_root.glob("*.toml")):
        files[Path(".engineering-bootstrap/profiles") / profile.name] = (
            profile.read_bytes()
        )
    if mode == "existing":
        files[Path(".engineering-bootstrap/existing-project-inventory.json")] = (
            json.dumps(dict(inventory or {}), indent=2) + "\n"
        ).encode()
    return files


def _diff(existing: bytes, proposed: bytes, path: str) -> list[str]:
    try:
        before = existing.decode("utf-8").splitlines()
        after = proposed.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return ["binary content differs"]
    return list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"existing/{path}",
            tofile=f"bootstrap/{path}",
            lineterm="",
        )
    )[:200]


def inspect_scaffold(
    project: Path, expected: Mapping[Path, bytes]
) -> tuple[list[str], list[str], list[str], list[dict[str, object]]]:
    create: list[str] = []
    unchanged: list[str] = []
    conflicts: list[str] = []
    plan: list[dict[str, object]] = []
    for relative, content in sorted(
        expected.items(), key=lambda item: item[0].as_posix()
    ):
        target = project / relative
        path = relative.as_posix()
        record: dict[str, object] = {
            "path": path,
            "scope": "bootstrap_owned"
            if path.startswith(".engineering-bootstrap/")
            else "integration",
            "proposed_sha256": _sha256(content),
        }
        if not target.exists():
            create.append(path)
            record["action"] = "create"
        elif target.is_file() and target.read_bytes() == content:
            unchanged.append(path)
            record["action"] = "unchanged"
        else:
            conflicts.append(path)
            record["action"] = "preserve_existing"
            if target.is_file():
                existing = target.read_bytes()
                record["existing_sha256"] = _sha256(existing)
                record["diff"] = _diff(existing, content, path)
        plan.append(record)
    return create, unchanged, conflicts, plan


def _existing_inventory(project: Path) -> dict[str, object]:
    saved = project / ".engineering-bootstrap/existing-project-inventory.json"
    if saved.is_file():
        return json.loads(saved.read_text(encoding="utf-8"))
    return inspect_existing_project(project)


def commission(
    project: Path,
    mode: str,
    *,
    apply: bool = False,
    source_root: Path | None = None,
    questionnaire: Path | None = None,
) -> dict:
    if mode not in {"new", "existing"}:
        raise ValueError("mode must be new or existing")
    resolved = project.resolve()
    if mode == "existing" and not resolved.is_dir():
        raise ValueError("existing project must be a directory")
    if mode == "new" and resolved.exists() and not resolved.is_dir():
        raise ValueError("new project path must be absent or a directory")
    source = (source_root or framework_root()).resolve()
    questionnaire_record = None
    if questionnaire is not None:
        questionnaire_record = json.loads(questionnaire.read_text(encoding="utf-8"))
        validate_instance(
            questionnaire_record,
            source / "contracts" / "commissioning-questionnaire.schema.json",
        )
        if questionnaire_record.get("mode") != mode:
            raise ValueError("questionnaire mode does not match commissioning mode")
    inventory = _existing_inventory(resolved) if mode == "existing" else None
    expected = scaffold_files(mode, resolved, source, inventory, questionnaire_record)
    create, unchanged, conflicts, file_plan = inspect_scaffold(resolved, expected)
    bootstrap_conflicts = [
        path for path in conflicts if path.startswith(".engineering-bootstrap/")
    ]
    blocking_conflicts = conflicts if mode == "new" else bootstrap_conflicts
    preserved = conflicts if mode == "existing" else []
    flow = (
        ["brief", "architecture", "governance", "acceptance", "plan", "approval"]
        if mode == "new"
        else [
            "inventory",
            "architecture-truth-map",
            "canonical-owners",
            "risk",
            "adoption-plan",
            "approval",
        ]
    )
    result = {
        "valid": not blocking_conflicts,
        "mode": mode,
        "project": str(resolved),
        "applied": False,
        "effects": ["read_local"] if not apply else ["read_local", "write_workspace"],
        "flow": flow,
        "next": "resolve-bootstrap-conflicts" if blocking_conflicts else "approval",
        "create": create,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "blocking_conflicts": blocking_conflicts,
        "preserved_existing": preserved,
        "file_plan": file_plan,
    }
    if not apply or blocking_conflicts:
        return result
    resolved.mkdir(parents=True, exist_ok=True)
    for relative, content in expected.items():
        target = resolved / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    control = resolved / ".engineering-bootstrap"
    adoption_path = control / "adoption-plan.json"
    adoption = {
        "schema_version": "1.0",
        "mode": mode,
        "effects": ["read_local", "write_workspace"],
        "plan": file_plan,
        "blocking_conflicts": blocking_conflicts,
        "preserved_existing": preserved,
    }
    if not adoption_path.exists():
        adoption_path.write_bytes((json.dumps(adoption, indent=2) + "\n").encode())
    project_map_result = None
    if mode == "existing":
        from .project_intelligence import build_project_map

        project_map_result = build_project_map(resolved)
    receipt_path = control / "commissioning-receipt.json"
    mutable_prefixes = (
        "PROJECT_MANAGEMENT.md",
        "PROJECT_BLUEPRINT.md",
        "ARCHITECTURE_GOVERNANCE_AND_RISK.md",
        "EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md",
        ".engineering-bootstrap/project-management/",
    )
    managed = {}
    for relative, proposed in expected.items():
        path = relative.as_posix()
        if any(
            path == prefix or path.startswith(prefix) for prefix in mutable_prefixes
        ):
            continue
        target = resolved / relative
        if target.is_file() and target.read_bytes() == proposed:
            managed[path] = _sha256(proposed)
    project_record = json.loads(
        (control / "project-record.json").read_text(encoding="utf-8")
    )
    base_receipt = {
        "schema_version": "2.0",
        "mode": mode,
        "created": create,
        "unchanged": unchanged,
        "preserved_existing": preserved,
        "blocking_conflicts": [],
        "managed_file_sha256": managed,
        "managed_manifest_sha256": _sha256(
            json.dumps(managed, sort_keys=True, separators=(",", ":")).encode()
        ),
        "mutable_project_management": list(mutable_prefixes),
        "adoption_plan": ".engineering-bootstrap/adoption-plan.json",
        "project_id": project_record["project_id"],
        "project_record_sha256": _sha256(
            (control / "project-record.json").read_bytes()
        ),
        "framework_release": _framework_binding(source),
        "commissioning_tool_version": authoritative_version(source),
        "project_map_revision": project_map_result.get("map_revision")
        if project_map_result
        else None,
        "project_map_source_inventory_sha256": project_map_result.get(
            "source_inventory_sha256"
        )
        if project_map_result
        else None,
        "commissioned_utc": datetime.now(timezone.utc).isoformat(),
        "approving_identity": "local-operator",
    }
    base_digest = _sha256(
        json.dumps(base_receipt, sort_keys=True, separators=(",", ":")).encode()
    )
    event_path = append_chained_event(
        control / "commissioning-events",
        "project-commissioned",
        {
            "project_id": project_record["project_id"],
            "framework_release": base_receipt["framework_release"],
            "managed_manifest_sha256": base_receipt["managed_manifest_sha256"],
            "receipt_payload_sha256": base_digest,
        },
    )
    event = json.loads(event_path.read_text(encoding="utf-8"))
    receipt = {
        **base_receipt,
        "receipt_payload_sha256": base_digest,
        "commissioning_event_sha256": event["event_sha256"],
    }
    receipt["receipt_sha256"] = _sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    )
    if receipt_path.is_file():
        prior = receipt_path.read_bytes()
        history = control / "commissioning-history" / f"{_sha256(prior)}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        if not history.exists():
            history.write_bytes(prior)
    temporary_receipt = receipt_path.with_name(
        f".{receipt_path.name}.{event['sequence']:06d}.prepared"
    )
    temporary_receipt.write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    os.replace(temporary_receipt, receipt_path)
    result.update(
        {
            "applied": True,
            "next": "validate",
            "receipt": str(receipt_path),
            "adoption_plan": str(adoption_path),
            "project_map": project_map_result,
        }
    )
    return result


def apply_project_brief(
    project: Path,
    questionnaire: Path,
    *,
    source_root: Path | None = None,
    apply: bool = False,
) -> dict[str, object]:
    """Validate and version a questionnaire into an already commissioned project."""
    resolved = project.resolve()
    source = (source_root or framework_root()).resolve()
    errors = validate_project_management(resolved)
    if errors:
        raise ValueError(f"project management is invalid: {errors}")
    state_path = resolved / ".engineering-bootstrap/project-management/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    answers = json.loads(questionnaire.read_text(encoding="utf-8"))
    validate_instance(
        answers, source / "contracts/commissioning-questionnaire.schema.json"
    )
    if answers["mode"] != state["project"]["mode"]:
        raise ValueError("questionnaire mode does not match commissioned project mode")
    accepted = all(value is True for value in answers["human_acceptance"].values())
    updated = json.loads(json.dumps(state))
    updated["work"]["objective"] = answers["answers"].get("goal")
    updated["work"]["scope"]["included"] = (
        [answers["answers"]["scope"]] if answers["answers"].get("scope") else []
    )
    updated["knowledge"] = {
        "facts": answers["facts"],
        "assumptions": answers["assumptions"],
        "contradictions": answers["contradictions"],
        "unknowns": answers["unknowns"],
    }
    updated["governance"]["assumptions"] = answers["assumptions"]
    updated["governance"]["risks"] = [*answers["unknowns"], *answers["contradictions"]]
    updated["governance"]["pending_approvals"] = answers["decisions_requiring_approval"]
    next_action = (
        "create bounded milestones and acceptance-linked punch cards"
        if accepted
        else "resolve unaccepted commissioning decisions"
    )
    updated["lifecycle"] = {
        "phase": "planning" if accepted else "commissioning",
        "status": "brief_accepted_awaiting_plan" if accepted else "brief_incomplete",
        "next_action": next_action,
    }
    updated["checkpoint"]["revision"] = int(updated["checkpoint"]["revision"]) + 1
    updated["checkpoint"]["next_safe_action"] = next_action
    updated["evidence"]["commissioning_questionnaire"] = (
        ".engineering-bootstrap/project-management/commissioning-questionnaire.json"
    )
    validate_instance(updated, source / "contracts/project-management.schema.json")
    target = state_path.parent / "commissioning-questionnaire.json"
    result = {
        "valid": True,
        "applied": False,
        "accepted": accepted,
        "project": resolved.as_posix(),
        "effects": ["write_project_management"],
        "target": target.relative_to(resolved).as_posix(),
        "next_action": next_action,
    }
    if not apply:
        return {**result, "approval_required": True}
    history = state_path.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    for current in (state_path, target, resolved / "PROJECT_MANAGEMENT.md"):
        if current.is_file():
            preserved = (
                history
                / f"{current.stem}-{_sha256(current.read_bytes())[:16]}{current.suffix}"
            )
            if not preserved.exists():
                preserved.write_bytes(current.read_bytes())
    target_next = target.with_suffix(".json.next")
    target_next.write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    os.replace(target_next, target)
    state_next = state_path.with_suffix(".json.next")
    state_next.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    os.replace(state_next, state_path)
    dashboard = resolved / "PROJECT_MANAGEMENT.md"
    text = dashboard.read_text(encoding="utf-8")
    summary = f"## Current state\n\nMode: `{answers['mode']}`  \nPhase: `{updated['lifecycle']['phase']}`  \nStatus: `{updated['lifecycle']['status']}`  \nNext: {next_action}\n\n"
    text = re.sub(
        r"## Current state\s+.*?(?=\n## )",
        summary.rstrip(),
        text,
        count=1,
        flags=re.DOTALL,
    )
    dashboard_next = dashboard.with_suffix(".md.next")
    dashboard_next.write_text(text, encoding="utf-8")
    os.replace(dashboard_next, dashboard)
    return {
        **result,
        "applied": True,
        "state_revision": updated["checkpoint"]["revision"],
    }


def project_check(project: Path, source_root: Path | None = None) -> dict:
    resolved = project.resolve()
    source = (source_root or framework_root()).resolve()
    errors: list[str] = []
    required = [
        Path(".engineering-bootstrap/AGENTS.md"),
        Path(".engineering-bootstrap/AI_ASSISTANT.md"),
        Path(".engineering-bootstrap/project.toml"),
        Path(".engineering-bootstrap/bootstrap-manifest.json"),
        Path(".engineering-bootstrap/project-registry.json"),
        Path(".engineering-bootstrap/commissioning-receipt.json"),
        Path(".engineering-bootstrap/project-record.json"),
        Path(".engineering-bootstrap/adoption-plan.json"),
        Path(".engineering-bootstrap/prompts/new-project.md"),
        Path(".engineering-bootstrap/prompts/existing-project.md"),
    ]
    for relative in required:
        if not (resolved / relative).is_file():
            errors.append(f"missing {relative.as_posix()}")
    errors.extend(validate_project_management(resolved))
    project_toml: dict[str, object] = {}
    try:
        project_toml = tomllib.loads(
            (resolved / ".engineering-bootstrap/project.toml").read_text(
                encoding="utf-8"
            )
        )
        if project_toml.get("startup", {}).get("max_selected_capabilities") != 3:
            errors.append("project skill budget must equal three")
        if project_toml.get("startup", {}).get("metadata_only") is not True:
            errors.append("project startup must be metadata-only")
    except (OSError, tomllib.TOMLDecodeError) as error:
        errors.append(f"invalid project.toml: {error}")
    mode = project_toml.get("project", {}).get("mode") if project_toml else None
    project_map_policy = project_toml.get("project_map", {}) if project_toml else {}
    if project_map_policy.get("required") is True:
        try:
            from .project_intelligence import validate_project_map

            map_validation = validate_project_map(resolved, check_freshness=True)
            errors.extend(
                f"project map: {item}" for item in map_validation.get("errors", ())
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"project map unavailable: {error}")
    if (
        mode == "existing"
        and not (
            resolved / ".engineering-bootstrap/existing-project-inventory.json"
        ).is_file()
    ):
        errors.append("missing existing-project inventory")
    try:
        manifest = json.loads(
            (resolved / ".engineering-bootstrap/bootstrap-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if (
            manifest.get("startup", {}).get("skill_bodies_copied_to_project")
            is not False
        ):
            errors.append("bootstrap manifest permits eager skill copying")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid bootstrap manifest: {error}")
    skills: list[str] = []
    try:
        registry = json.loads(
            (resolved / ".engineering-bootstrap/project-registry.json").read_text(
                encoding="utf-8"
            )
        )
        if (
            registry.get("max_selected_skills") != 3
            or registry.get("skill_bodies_copied_to_project") is not False
        ):
            errors.append("invalid project skill registry loading policy")
        for item in registry.get("skills", []):
            body = (source / item["body"]).resolve()
            if source not in body.parents or not body.is_file():
                errors.append(f"missing canonical skill body: {item.get('id')}")
                continue
            content = body.read_bytes()
            if _sha256(content) != item.get("sha256") or len(content) != item.get(
                "bytes"
            ):
                errors.append(f"canonical skill hash mismatch: {item.get('id')}")
                continue
            text = content.decode("utf-8")
            name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", text, re.MULTILINE)
            description_match = re.search(
                r"^description:\s*(.+)\s*$", text, re.MULTILINE
            )
            if (
                not text.startswith("---\n")
                or not name_match
                or name_match.group(1) != item.get("id")
            ):
                errors.append(f"invalid skill identity: {item.get('id')}")
                continue
            if not description_match or "TODO" in description_match.group(1):
                errors.append(f"invalid skill description: {item.get('id')}")
                continue
            skills.append(item["id"])
    except (OSError, json.JSONDecodeError, KeyError) as error:
        errors.append(f"invalid project registry: {error}")
    try:
        record = json.loads(
            (resolved / ".engineering-bootstrap/project-record.json").read_text(
                encoding="utf-8"
            )
        )
        if not re.fullmatch(r"prj_[A-Za-z0-9_-]+", str(record.get("project_id", ""))):
            errors.append("invalid project record identity")
        if record.get("state") not in {
            "discovered",
            "registered",
            "active",
            "paused",
            "dormant",
            "archived",
            "retired",
        }:
            errors.append("invalid project record state")
        if record.get("cross_project_access") not in {"deny", "explicit-only"}:
            errors.append("invalid project cross-project boundary")
        repositories = record.get("repositories", [])
        if not repositories or any(
            not str(item.get("repository_id", "")).startswith("repo_")
            for item in repositories
        ):
            errors.append("invalid repository identity in project record")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid project record: {error}")
    try:
        receipt = json.loads(
            (resolved / ".engineering-bootstrap/commissioning-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        receipt_digest = receipt.pop("receipt_sha256", None)
        if receipt_digest != _sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        ):
            errors.append("commissioning receipt digest mismatch")
        payload_digest = receipt.get("receipt_payload_sha256")
        base = {
            key: value
            for key, value in receipt.items()
            if key not in {"receipt_payload_sha256", "commissioning_event_sha256"}
        }
        if payload_digest != _sha256(
            json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
        ):
            errors.append("commissioning receipt payload digest mismatch")
        project_record_path = resolved / ".engineering-bootstrap/project-record.json"
        if receipt.get("project_id") != record.get("project_id") or receipt.get(
            "project_record_sha256"
        ) != _sha256(project_record_path.read_bytes()):
            errors.append("commissioning receipt project binding mismatch")
        framework = _framework_binding(source)
        if (
            receipt.get("framework_release") != framework
            or receipt.get("commissioning_tool_version") != framework["version"]
        ):
            errors.append("commissioning receipt framework release binding mismatch")
        lifecycle = validate_event_ledger(
            resolved / ".engineering-bootstrap/commissioning-events"
        )
        if not lifecycle["valid"]:
            errors.extend(
                f"commissioning event ledger: {item}" for item in lifecycle["errors"]
            )
        bound = next(
            (
                event
                for event in lifecycle["events"]
                if event.get("event_sha256")
                == receipt.get("commissioning_event_sha256")
            ),
            None,
        )
        if (
            bound is None
            or bound.get("payload", {}).get("receipt_payload_sha256") != payload_digest
        ):
            errors.append("commissioning receipt event anchor mismatch")
        managed = receipt.get("managed_file_sha256", {})
        if receipt.get("managed_manifest_sha256") != _sha256(
            json.dumps(managed, sort_keys=True, separators=(",", ":")).encode()
        ):
            errors.append("commissioning managed manifest digest mismatch")
        for relative, digest in receipt.get("managed_file_sha256", {}).items():
            target = (resolved / relative).resolve()
            if (
                resolved not in target.parents
                or not target.is_file()
                or _sha256(target.read_bytes()) != digest
            ):
                errors.append(f"managed commissioning file drift: {relative}")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid commissioning receipt: {error}")
    for relative in (
        Path(".engineering-bootstrap/vscode.settings.json"),
        Path(".engineering-bootstrap/vscode.tasks.json"),
    ):
        try:
            json.loads((resolved / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"invalid {relative.as_posix()}: {error}")
    return {
        "valid": not errors,
        "project": str(resolved),
        "mode": mode,
        "skill_count": len(skills),
        "skills": skills,
        "errors": errors,
    }
