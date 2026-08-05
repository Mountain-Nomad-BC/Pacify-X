"""Deterministic project-management artifacts for commissioned repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .contracts import validate_instance
from .paths import framework_root
from .version import VERSION


CONTROL_DIR = Path(".engineering-bootstrap/project-management")
CONTROL_FILES = (
    "PROJECT_CONTEXT.md",
    "ASSUMPTIONS.md",
    "EXECUTION_PLAN.md",
    "PUNCH_CARDS.md",
    "ORCHESTRATION.md",
    "RISKS.md",
    "ACCEPTANCE_CRITERIA.md",
)
COMPACT_OUTPUT_FILES = (
    "PROJECT_BLUEPRINT.md",
    "ARCHITECTURE_GOVERNANCE_AND_RISK.md",
    "EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md",
)


def _document(title: str, purpose: str, sections: tuple[tuple[str, str], ...]) -> bytes:
    lines = [f"# {title}", "", purpose, ""]
    for heading, body in sections:
        lines.extend((f"## {heading}", "", body, ""))
    return "\n".join(lines).encode("utf-8")


def project_management_files(
    project: Path,
    mode: str,
    inventory: Mapping[str, object] | None = None,
    questionnaire: Mapping[str, object] | None = None,
) -> dict[Path, bytes]:
    if mode not in {"new", "existing"}:
        raise ValueError("mode must be new or existing")
    inventory = dict(inventory or {})
    questionnaire = dict(questionnaire or {})
    answers = dict(questionnaire.get("answers", {}))
    accepted = questionnaire.get("human_acceptance", {})
    brief_accepted = bool(accepted) and all(
        value is True for value in accepted.values()
    )
    project_name = project.resolve().name
    inventory_summary = (
        f"Read-only intake recorded {inventory.get('file_count', 0)} files with inventory SHA-256 "
        f"`{inventory.get('inventory_sha256', 'not-applicable')}`."
        if mode == "existing"
        else "No pre-existing repository inventory applies. Establish the product brief before implementation."
    )
    state = {
        "schema_version": "1.0",
        "project": {"name": project_name, "root": ".", "mode": mode},
        "lifecycle": {
            "phase": "commissioning",
            "status": "brief_accepted_awaiting_plan"
            if brief_accepted
            else (
                "awaiting_project_brief"
                if mode == "new"
                else "inventory_complete_awaiting_plan"
            ),
            "next_action": "create bounded milestones and acceptance-linked punch cards"
            if brief_accepted
            else "confirm objective, scope, constraints, risks, and acceptance criteria",
        },
        "controls": {
            "proposal_before_mutation": True,
            "explicit_approval_for_writes": True,
            "quarantine_only_cleanup": True,
            "metadata_only_startup": True,
            "maximum_selected_skills": 3,
            "checkpoint_after_material_steps": True,
        },
        "work": {
            "objective": answers.get("goal"),
            "scope": {
                "included": [answers["scope"]] if answers.get("scope") else [],
                "excluded": [],
            },
            "active_punch_card": "PM-002",
            "milestones": [],
            "backlog": [],
        },
        "knowledge": {
            "facts": list(questionnaire.get("facts", [])),
            "assumptions": list(questionnaire.get("assumptions", [])),
            "contradictions": list(questionnaire.get("contradictions", [])),
            "unknowns": list(questionnaire.get("unknowns", [])),
        },
        "governance": {
            "assumptions": list(questionnaire.get("assumptions", [])),
            "risks": [
                *list(questionnaire.get("unknowns", [])),
                *list(questionnaire.get("contradictions", [])),
            ],
            "decisions": [],
            "pending_approvals": list(
                questionnaire.get("decisions_requiring_approval", [])
            ),
        },
        "checkpoint": {
            "revision": 1,
            "repository": {
                "root": ".",
                "branch": None,
                "commit": None,
                "working_tree_sha256": None,
            },
            "versions": {
                "plan": 1,
                "assumptions": 1,
                "project_management_schema": "1.0",
            },
            "approved_effects": [],
            "approval_expiry": None,
            "active_skills": [],
            "tool_versions": {},
            "runtime_version": VERSION,
            "changed_file_sha256": {},
            "validation": {"tests": "not_run", "verifier": "not_run"},
            "budgets": {"maximum_selected_skills": 3, "maximum_heavy_lanes": 1},
            "failures": [],
            "retries": [],
            "degraded_components": [],
            "open_circuits": [],
            "next_safe_action": "create bounded milestones and acceptance-linked punch cards"
            if brief_accepted
            else "confirm objective, scope, constraints, risks, and acceptance criteria",
        },
        "evidence": {
            "commissioning_receipt": ".engineering-bootstrap/commissioning-receipt.json",
            "existing_project_inventory": ".engineering-bootstrap/existing-project-inventory.json"
            if mode == "existing"
            else None,
            "validation_receipt": None,
            "commissioning_questionnaire": ".engineering-bootstrap/project-management/commissioning-questionnaire.json"
            if questionnaire
            else None,
        },
        "commissioning_outputs": list(COMPACT_OUTPUT_FILES),
    }
    files: dict[Path, bytes] = {
        CONTROL_DIR / "state.json": (json.dumps(state, indent=2) + "\n").encode(
            "utf-8"
        ),
        Path("PROJECT_MANAGEMENT.md"): _document(
            "Project Management",
            "This is the durable human entry point for the governed engineering loop. Update it from evidence; keep machine-readable state synchronized in `.engineering-bootstrap/project-management/state.json`.",
            (
                (
                    "Current state",
                    f"Mode: `{mode}`  \nPhase: `commissioning`  \nStatus: `{state['lifecycle']['status']}`  \nNext: {state['lifecycle']['next_action']}",
                ),
                (
                    "Commissioning outputs",
                    "- [Project blueprint](PROJECT_BLUEPRINT.md)\n- [Architecture, governance, and risk](ARCHITECTURE_GOVERNANCE_AND_RISK.md)\n- [Execution plan, punch cards, and acceptance](EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md)",
                ),
                (
                    "Control files",
                    "- [Project context](.engineering-bootstrap/project-management/PROJECT_CONTEXT.md)\n- [Assumptions](.engineering-bootstrap/project-management/ASSUMPTIONS.md)\n- [Execution plan](.engineering-bootstrap/project-management/EXECUTION_PLAN.md)\n- [Punch cards](.engineering-bootstrap/project-management/PUNCH_CARDS.md)\n- [Orchestration](.engineering-bootstrap/project-management/ORCHESTRATION.md)\n- [Risks](.engineering-bootstrap/project-management/RISKS.md)\n- [Acceptance criteria](.engineering-bootstrap/project-management/ACCEPTANCE_CRITERIA.md)",
                ),
                (
                    "Update contract",
                    "Checkpoint before and after material work. Record facts, assumptions, decisions, approvals, evidence, residual risks, and the next action. Never mark work complete from an executor claim alone.",
                ),
            ),
        ),
        CONTROL_DIR / "PROJECT_CONTEXT.md": _document(
            "Project Context",
            "Record verified project reality before planning changes.",
            (
                (
                    "Identity",
                    f"Project: `{project_name}`  \nMode: `{mode}`  \nRoot: `.`",
                ),
                ("Intake evidence", inventory_summary),
                ("Objective", "Pending user confirmation."),
                ("Scope and constraints", "Pending evidence-backed definition."),
                (
                    "Canonical owners",
                    "Preserve existing architecture, instruction, build, test, security, and deployment owners unless an approved decision changes them.",
                ),
            ),
        ),
        CONTROL_DIR / "ASSUMPTIONS.md": _document(
            "Assumptions",
            "Separate verified facts, assumptions, contradictions, and unknowns.",
            (
                (
                    "Ledger",
                    "| ID | Statement | Type | Confidence | Risk | Evidence | Status |\n|---|---|---|---|---|---|---|\n| A-001 | Project objective is not yet confirmed. | unknown | n/a | high | user confirmation required | open |",
                ),
                (
                    "Rule",
                    "High- or critical-risk assumptions block implementation unless the user approves a bounded exception.",
                ),
            ),
        ),
        CONTROL_DIR / "EXECUTION_PLAN.md": _document(
            "Execution Plan",
            "Plan dependency-ordered work from current evidence.",
            (
                (
                    "Active wave",
                    "Wave 0 — confirm context, objective, constraints, risks, and acceptance criteria.",
                ),
                (
                    "Later waves",
                    "Create implementation waves only after Wave 0 is accepted. Declare effects, owners, validation, rollback, and evidence for each wave.",
                ),
                (
                    "Resume contract",
                    "On resume, reconcile repository drift, configuration hashes, tool availability, pending approvals, and evidence before continuing.",
                ),
            ),
        ),
        CONTROL_DIR / "PUNCH_CARDS.md": _document(
            "Punch Cards",
            "Use bounded cards with explicit acceptance evidence.",
            (
                (
                    "PM-001 — Commission bootstrap",
                    "Status: complete after `engineering-bootstrap project-check --project .` passes.",
                ),
                (
                    "PM-002 — Confirm project brief",
                    "Status: active. Capture objective, users, constraints, deployment boundary, and exclusions.",
                ),
                (
                    "PM-003 — Freeze acceptance contract",
                    "Status: pending. Define observable postconditions and required evidence.",
                ),
                (
                    "PM-004 — Execute approved waves",
                    "Status: pending. Create one bounded card per approved work package.",
                ),
            ),
        ),
        CONTROL_DIR / "ORCHESTRATION.md": _document(
            "Orchestration",
            "Operate through compact metadata and hydrate only the selected capability.",
            (
                (
                    "Loop",
                    "Validate → inspect project state → classify goal → select at most three metadata candidates → hydrate one skill → declare effects → obtain approval when required → execute → verify → checkpoint → release context.",
                ),
                (
                    "Commands",
                    '`engineering-bootstrap validate`  \n`engineering-bootstrap startup --project .`  \n`engineering-bootstrap working-set --goal "<goal>"`  \n`engineering-bootstrap hydrate --skill <selected-id>`',
                ),
                (
                    "Stop conditions",
                    "Stop on unknown mutation, secret exposure, project-root ambiguity, unresolved high-risk assumptions, registry failure, or unverifiable completion.",
                ),
            ),
        ),
        CONTROL_DIR / "RISKS.md": _document(
            "Risks",
            "Track exposure, mitigation, owner, evidence, and residual risk.",
            (
                (
                    "Register",
                    "| ID | Risk | Severity | Mitigation | Evidence | Status |\n|---|---|---|---|---|---|\n| R-001 | Project intent is incomplete. | high | Confirm the project brief before implementation. | user-approved brief | open |",
                ),
                (
                    "Escalation",
                    "Critical risks and destructive, privileged, external, security-sensitive, or deployment effects require explicit approval.",
                ),
            ),
        ),
        CONTROL_DIR / "ACCEPTANCE_CRITERIA.md": _document(
            "Acceptance Criteria",
            "Define observable outcomes before implementation.",
            (
                ("Project outcomes", "Pending user confirmation."),
                (
                    "Engineering baseline",
                    "- [ ] Intended and actual changes match.\n- [ ] Relevant tests and static checks pass.\n- [ ] Security, data, dependency, accessibility, and deployment effects are reviewed.\n- [ ] Rollback remains viable.\n- [ ] Evidence is current, scoped, and sanitized.\n- [ ] Independent outcome verification passes.",
                ),
                (
                    "Completion rule",
                    "A successful command, tool call, build, or executor claim is not sufficient evidence of completion.",
                ),
            ),
        ),
        Path("PROJECT_BLUEPRINT.md"): _document(
            "Project Blueprint",
            "Compact commissioning output. Replace pending sections only with confirmed facts, labeled assumptions, or explicit unknowns.",
            (
                ("Executive summary", "Pending project brief."),
                ("Problem and users", "Pending user confirmation."),
                ("Scope and non-goals", "Pending approval."),
                ("Roles and core workflows", "Pending discovery."),
                ("Functional requirements", "Pending discovery."),
                ("Non-functional requirements", "Pending risk and workload analysis."),
                ("Data and source of truth", "Pending discovery."),
                (
                    "Accessibility",
                    "Determine deployment, audience, jurisdiction, target standard, assistive-technology behavior, and evidence.",
                ),
                ("Success criteria", "Pending observable acceptance outcomes."),
            ),
        ),
        Path("ARCHITECTURE_GOVERNANCE_AND_RISK.md"): _document(
            "Architecture, Governance, and Risk",
            "Compact commissioning output. Architecture and compliance claims remain proposals until approved and evidenced.",
            (
                (
                    "Facts, assumptions, unknowns, contradictions",
                    "See `.engineering-bootstrap/project-management/ASSUMPTIONS.md`; summarize accepted findings here.",
                ),
                (
                    "Options and recommendation",
                    "Pending evidence-backed comparison of cost, maintenance, security, accessibility, and operations.",
                ),
                (
                    "Technology and capability decisions",
                    "Pending. Justify deterministic software, AI, retrieval, and agents independently.",
                ),
                (
                    "Integrations and data adaptation",
                    "Pending source-of-truth and direction mapping.",
                ),
                (
                    "Security, privacy, and retention",
                    "Pending risk classification and approval.",
                ),
                (
                    "Deployment, recovery, and operations",
                    "Pending deployment boundary and ownership.",
                ),
                ("Cost envelope", "Pending current evidence."),
                (
                    "Governance gates",
                    "Approval is required before implementation, installation, external access, migration, security-sensitive testing, or deployment.",
                ),
                (
                    "Risks and mitigations",
                    "See `.engineering-bootstrap/project-management/RISKS.md`.",
                ),
            ),
        ),
        Path("EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md"): _document(
            "Execution Plan, Punch Cards, and Acceptance",
            "Compact commissioning output. Freeze only approved work and retain rollback and evidence requirements.",
            (
                (
                    "Execution waves",
                    "Wave 0: commissioning and evidence reconciliation. Later waves remain pending approval.",
                ),
                (
                    "Punch cards and dependencies",
                    "See `.engineering-bootstrap/project-management/PUNCH_CARDS.md` and `EXECUTION_PLAN.md`.",
                ),
                (
                    "Approval checkpoints",
                    "Require explicit approval for mutations, installs, external access, services, secrets, migrations, destructive work, security-sensitive testing, and deployment.",
                ),
                (
                    "Test and verification strategy",
                    "Define positive, negative, integration, accessibility, security, deployment, and outcome checks appropriate to the approved scope.",
                ),
                (
                    "Deployment gates and rollback",
                    "Block deployment without current tests, security review, evidence, rollback, and explicit approval.",
                ),
                (
                    "Acceptance criteria and definition of done",
                    "See `.engineering-bootstrap/project-management/ACCEPTANCE_CRITERIA.md`.",
                ),
                (
                    "Initial project prompt",
                    "Use `.engineering-bootstrap/prompts/new-project.md` or `existing-project.md` according to the commissioned mode.",
                ),
            ),
        ),
    }
    if questionnaire:
        files[CONTROL_DIR / "commissioning-questionnaire.json"] = (
            json.dumps(questionnaire, indent=2) + "\n"
        ).encode("utf-8")
    return files


def validate_project_management(project: Path) -> list[str]:
    root = project.resolve()
    errors: list[str] = []
    if not (root / "PROJECT_MANAGEMENT.md").is_file():
        errors.append("missing PROJECT_MANAGEMENT.md")
    for name in CONTROL_FILES:
        if not (root / CONTROL_DIR / name).is_file():
            errors.append(f"missing {(CONTROL_DIR / name).as_posix()}")
    for name in COMPACT_OUTPUT_FILES:
        if not (root / name).is_file():
            errors.append(f"missing {name}")
    state_path = root / CONTROL_DIR / "state.json"
    if not state_path.is_file():
        errors.append(f"missing {(CONTROL_DIR / 'state.json').as_posix()}")
        return errors
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        validate_instance(
            state, framework_root() / "contracts" / "project-management.schema.json"
        )
        if state.get("schema_version") != "1.0":
            errors.append("invalid project-management schema version")
        if state.get("project", {}).get("mode") not in {"new", "existing"}:
            errors.append("invalid project-management mode")
        if state.get("controls", {}).get("maximum_selected_skills") != 3:
            errors.append("invalid project-management skill budget")
        if state.get("controls", {}).get("quarantine_only_cleanup") is not True:
            errors.append("project management does not enforce quarantine-only cleanup")
        checkpoint = state.get("checkpoint", {})
        if (
            not isinstance(checkpoint.get("revision"), int)
            or checkpoint["revision"] < 1
            or checkpoint.get("next_safe_action")
            != state.get("lifecycle", {}).get("next_action")
        ):
            errors.append(
                "project-management checkpoint is incomplete or unsynchronized"
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"invalid project-management state: {error}")
    return errors
