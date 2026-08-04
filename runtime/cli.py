"""Command-line surface for the independent bootstrap."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys

from .version import VERSION


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="engineering-bootstrap",
        description="PACIFY-X package and command-line control plane",
    )
    result.add_argument("--root", type=Path, default=None)
    result.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("doctor")
    lifecycle = commands.add_parser("lifecycle")
    lifecycle.add_argument("action", choices=("status", "plan"))
    lifecycle.add_argument("--project", type=Path, required=True)
    contracts = commands.add_parser("contracts")
    contract_commands = contracts.add_subparsers(dest="contracts_action", required=True)
    contract_commands.add_parser("status")
    contract_validate = contract_commands.add_parser("validate")
    contract_validate.add_argument("--schema", type=Path, required=True)
    contract_validate.add_argument("--instance", type=Path, required=True)
    integrations = commands.add_parser("integrations")
    integrations.add_argument("action", choices=("status", "smoke"))
    graphs = commands.add_parser("graphs")
    graphs.add_argument("action", choices=("status",))
    audit = commands.add_parser("audit")
    audit.add_argument(
        "scope",
        nargs="?",
        choices=("release", "structure", "licensing"),
        default="release",
    )
    audit.add_argument("--strict-external-evidence", action="store_true")
    audit.add_argument("--write-report", action="store_true")
    gates = commands.add_parser("gates")
    gate_commands = gates.add_subparsers(dest="gates_action", required=True)
    gate_run = gate_commands.add_parser("run")
    gate_run.add_argument("--gate", action="append", default=[])
    gate_run.add_argument("--receipt-dir", type=Path, required=True)
    gate_run.add_argument("--force", action="store_true")
    gate_status = gate_commands.add_parser("finalize")
    gate_status.add_argument("--receipt-dir", type=Path, required=True)
    process = commands.add_parser("process")
    process_commands = process.add_subparsers(dest="process_action", required=True)
    process_compile = process_commands.add_parser("compile")
    process_compile.add_argument("--record", type=Path, required=True)
    process_compile.add_argument("--project", type=Path, required=True)
    process_compile.add_argument("--apply", action="store_true")
    research = commands.add_parser("research")
    research_commands = research.add_subparsers(dest="research_action", required=True)
    research_validate = research_commands.add_parser("validate")
    research_validate.add_argument(
        "--kind",
        choices=(
            "research-record",
            "operationalization-record",
            "experiment-card",
            "bootstrap-status",
            "skill-manifest",
        ),
        required=True,
    )
    research_validate.add_argument("--record", type=Path, required=True)
    startup = commands.add_parser("startup")
    startup.add_argument("--project", type=Path, required=True)
    tooling = commands.add_parser("tooling")
    tooling_commands = tooling.add_subparsers(dest="tooling_action", required=True)
    tooling_assess = tooling_commands.add_parser("assess")
    tooling_assess.add_argument("--project", type=Path, required=True)
    classify = commands.add_parser("classify")
    classify.add_argument("--task", required=True)
    select = commands.add_parser("select")
    select.add_argument("--goal", required=True)
    select.add_argument("--input", action="append", default=[])
    select.add_argument("--tool", action="append", default=[])
    select.add_argument("--kind", action="append", default=[])
    select.add_argument(
        "--max-risk", choices=("R0", "R1", "R2", "R3", "R4"), default="R4"
    )
    select.add_argument("--max-candidates", type=int, default=3)
    working_set = commands.add_parser("working-set")
    working_set.add_argument("--goal", required=True)
    hydrate = commands.add_parser("hydrate")
    hydrate.add_argument("--skill", required=True)
    hydrate.add_argument("--include-references", action="store_true")
    intake = commands.add_parser("commission")
    intake.add_argument("--mode", choices=("new", "existing"), required=True)
    intake.add_argument("--project", type=Path, required=True)
    intake.add_argument("--questionnaire", type=Path)
    intake.add_argument("--apply", action="store_true")
    inspect = commands.add_parser("intake")
    inspect.add_argument("--project", type=Path, required=True)
    source_intake = commands.add_parser("source-intake")
    source_intake.add_argument(
        "action", choices=("status", "open", "snapshot", "close", "verify")
    )
    source_intake.add_argument("--source", type=Path, required=True)
    source_intake.add_argument("--state-dir", type=Path, required=True)
    source_intake.add_argument("--source-alias", required=True)
    source_intake.add_argument("--actor")
    source_intake.add_argument("--minimum-stability-seconds", type=float, default=30.0)
    commands.add_parser("profiles")
    test_profile = commands.add_parser("test-profile")
    test_profile.add_argument("action", choices=("show", "run"))
    test_profile.add_argument("name", choices=("fast", "full", "release"))
    release = commands.add_parser("release")
    release_commands = release.add_subparsers(dest="release_action", required=True)
    release_verify = release_commands.add_parser("verify")
    release_verify.add_argument("--release")
    release_verify.add_argument("--artifact-dir", type=Path)
    release_finalize = release_commands.add_parser("finalize")
    release_finalize.add_argument("--release", default=VERSION)
    release_finalize.add_argument("--artifact-dir", type=Path)
    release_finalize.add_argument("--wheelhouse", type=Path)
    release_finalize.add_argument("--signing-key", type=Path)
    release_commands.add_parser("manifest")
    release_commands.add_parser("environment")
    brief = commands.add_parser("brief")
    brief.add_argument("--project", type=Path, required=True)
    brief.add_argument("--questionnaire", type=Path, required=True)
    brief.add_argument("--apply", action="store_true")
    tool_intake = commands.add_parser("tool-intake")
    tool_intake.add_argument("action", choices=("scan", "record"))
    tool_intake.add_argument("--project", type=Path, required=True)
    tool_intake.add_argument("--execute-scanners", action="store_true")
    tools = commands.add_parser("tools")
    tools.add_argument("action", choices=("certify",))
    tool_intake.add_argument("--approve-scanners", action="store_true")
    tool_intake.add_argument("--approve-components", action="store_true")
    tool_intake.add_argument("--allow-license", action="append", default=[])
    tool_intake.add_argument("--apply", action="store_true")
    check = commands.add_parser("project-check")
    check.add_argument("--project", type=Path, required=True)
    specialties = commands.add_parser("specialties")
    specialties.add_argument("--category")
    plan = commands.add_parser("plan")
    plan.add_argument("--goal", required=True)
    plan.add_argument("--input", action="append", default=[])
    plan.add_argument("--effect", action="append", default=["read_local"])
    candidate = commands.add_parser("review-candidate")
    candidate.add_argument("--manifest", type=Path, required=True)
    candidate.add_argument("--evidence", type=Path, required=True)
    candidate_claims = commands.add_parser("evaluate-admission-claims")
    candidate_claims.add_argument("--manifest", type=Path, required=True)
    candidate_claims.add_argument("--evidence", type=Path, required=True)
    authorization = commands.add_parser("authorize")
    authorization.add_argument("--request", type=Path, required=True)
    simulate = commands.add_parser("simulate-authorization")
    simulate.add_argument("--capability", required=True)
    simulate.add_argument("--effect", action="append", default=[])
    simulate.add_argument("--timeout", type=int, default=30)
    simulate.add_argument("--max-tool-calls", type=int, default=0)
    simulate.add_argument("--policy-allowed", action="store_true")
    simulate.add_argument("--approval-id")
    simulate.add_argument("--idempotency-key")
    outcome = commands.add_parser("verify-outcome")
    outcome.add_argument("--request", type=Path, required=True)
    outcome_claims = commands.add_parser("evaluate-outcome-claims")
    outcome_claims.add_argument("--request", type=Path, required=True)
    retry = commands.add_parser("retry-decision")
    retry.add_argument("--failure", type=Path, required=True)
    retry.add_argument("--attempt", type=int, required=True)
    retry.add_argument("--evidence-id", action="append", default=[])
    retry.add_argument("--max-retries", type=int, default=None)
    workspace = commands.add_parser("workspace")
    workspace_commands = workspace.add_subparsers(
        dest="workspace_action", required=True
    )
    workspace_init = workspace_commands.add_parser("init")
    workspace_init.add_argument("--workspace", type=Path, required=True)
    workspace_init.add_argument("--workspace-id")
    workspace_init.add_argument("--apply", action="store_true")
    workspace_discover = workspace_commands.add_parser("discover")
    workspace_discover.add_argument("--workspace", type=Path, required=True)
    workspace_discover.add_argument("--apply", action="store_true")
    workspace_discover.add_argument("--max-files", type=int, default=100_000)
    workspace_create = workspace_commands.add_parser("create-project")
    workspace_create.add_argument("--workspace", type=Path, required=True)
    workspace_create.add_argument("--name", required=True)
    workspace_create.add_argument("--apply", action="store_true")
    workspace_status_parser = workspace_commands.add_parser("status")
    workspace_status_parser.add_argument("--workspace", type=Path, required=True)
    workspace_monitor_parser = workspace_commands.add_parser("monitor")
    workspace_monitor_parser.add_argument("--workspace", type=Path, required=True)
    workspace_rebuild = workspace_commands.add_parser("rebuild")
    workspace_rebuild.add_argument("--workspace", type=Path, required=True)
    workspace_rebuild.add_argument("--apply", action="store_true")
    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_action", required=True)
    project_activate = project_commands.add_parser("activate")
    project_activate.add_argument("--workspace", type=Path, required=True)
    project_activate.add_argument("--project-id", required=True)
    project_activate.add_argument("--agent-id", default="agent_operator")
    project_activate.add_argument("--session-id", default="session_operator")
    project_activate.add_argument("--context-reset-confirmed", action="store_true")
    project_current = project_commands.add_parser("current")
    project_current.add_argument("--workspace", type=Path, required=True)
    project_current.add_argument("--session-id", default="session_operator")
    project_release = project_commands.add_parser("release")
    project_release.add_argument("--workspace", type=Path, required=True)
    project_release.add_argument("--context-reset-confirmed", action="store_true")
    project_release.add_argument("--session-id", default="session_operator")
    project_list = project_commands.add_parser("list")
    project_list.add_argument("--workspace", type=Path, required=True)
    project_show = project_commands.add_parser("show")
    project_show.add_argument("--workspace", type=Path, required=True)
    project_show.add_argument("--project-id", required=True)
    project_renew = project_commands.add_parser("renew")
    project_renew.add_argument("--workspace", type=Path, required=True)
    project_renew.add_argument("--minutes", type=int, default=60)
    project_renew.add_argument("--session-id", default="session_operator")
    project_transition = project_commands.add_parser("transition")
    project_transition.add_argument("--workspace", type=Path, required=True)
    project_transition.add_argument("--project-id", required=True)
    project_transition.add_argument(
        "--action", choices=("pause", "resume", "archive"), required=True
    )
    project_transition.add_argument("--evidence", action="append", default=[])
    project_transition.add_argument("--apply", action="store_true")
    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_action", required=True)
    memory_ingest = memory_commands.add_parser("ingest")
    memory_ingest.add_argument("--workspace", type=Path, required=True)
    memory_ingest.add_argument("--project-id", required=True)
    memory_ingest.add_argument("--source", type=Path, action="append", required=True)
    memory_ingest.add_argument("--apply", action="store_true")
    memory_ingest.add_argument("--session-id", default="session_operator")
    memory_ingest.add_argument("--actor-id", default="agent_operator")
    memory_transition = memory_commands.add_parser("transition")
    memory_transition.add_argument("--workspace", type=Path, required=True)
    memory_transition.add_argument("--project-id", required=True)
    memory_transition.add_argument("--memory-id", required=True)
    memory_transition.add_argument(
        "--target",
        choices=("validated", "certified", "trusted", "revoked", "superseded"),
        required=True,
    )
    memory_transition.add_argument("--evidence", action="append", default=[])
    memory_transition.add_argument("--apply", action="store_true")
    memory_transition.add_argument("--session-id", default="session_operator")
    memory_transition.add_argument("--actor-id", default="agent_operator")
    memory_correct = memory_commands.add_parser("correct")
    memory_correct.add_argument("--workspace", type=Path, required=True)
    memory_correct.add_argument("--project-id", required=True)
    memory_correct.add_argument("--previous-memory-id", required=True)
    memory_correct.add_argument("--memory-id", required=True)
    memory_correct.add_argument("--source", type=Path, required=True)
    memory_correct.add_argument("--title", required=True)
    memory_correct.add_argument("--summary", required=True)
    memory_correct.add_argument(
        "--type",
        dest="memory_type",
        choices=(
            "fact",
            "decision",
            "failure",
            "pattern",
            "preference",
            "skill",
            "architecture",
            "risk",
            "assumption",
            "lesson",
            "relationship",
            "procedure",
        ),
        default="fact",
    )
    memory_correct.add_argument("--confidence", type=float, default=0.8)
    memory_correct.add_argument("--apply", action="store_true")
    memory_correct.add_argument("--session-id", default="session_operator")
    memory_correct.add_argument("--actor-id", default="agent_operator")
    memory_search = memory_commands.add_parser("search")
    memory_search.add_argument("--workspace", type=Path, required=True)
    memory_search.add_argument("--project-id", required=True)
    memory_search.add_argument("--query", required=True)
    memory_search.add_argument("--actor-id", default="agent_operator")
    memory_search.add_argument("--limit", type=int, default=5)
    memory_search.add_argument("--session-id", default="session_operator")
    memory_maintain = memory_commands.add_parser("maintain")
    memory_maintain.add_argument("--workspace", type=Path, required=True)
    memory_maintain.add_argument("--project-id", required=True)
    memory_maintain.add_argument("--apply", action="store_true")
    memory_maintain.add_argument("--session-id", default="session_operator")
    memory_maintain.add_argument("--actor-id", default="agent_operator")
    memory_status_parser = memory_commands.add_parser("status")
    memory_status_parser.add_argument("--workspace", type=Path, required=True)
    memory_status_parser.add_argument("--project-id", required=True)
    memory_status_parser.add_argument("--actor-id", default="agent_operator")
    memory_status_parser.add_argument("--session-id", default="session_operator")
    memory_reconcile = memory_commands.add_parser("reconcile")
    memory_reconcile.add_argument("--workspace", type=Path, required=True)
    memory_reconcile.add_argument("--project-id", required=True)
    memory_reconcile.add_argument("--apply", action="store_true")
    memory_reconcile.add_argument("--session-id", default="session_operator")
    memory_reconcile.add_argument("--actor-id", default="agent_operator")
    workflow = commands.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_action", required=True)
    workflow_commands.add_parser("list")
    workflow_run = workflow_commands.add_parser("run")
    workflow_run.add_argument("--workspace", type=Path, required=True)
    workflow_run.add_argument("--request", type=Path, required=True)
    workflow_run.add_argument("--apply", action="store_true")
    declared = commands.add_parser("declared-suite")
    declared_commands = declared.add_subparsers(dest="declared_action", required=True)
    declared_list = declared_commands.add_parser("list")
    declared_list.add_argument("--kind", choices=("skill", "script", "orchestration"))
    declared_list.add_argument("--owner")
    declared_describe = declared_commands.add_parser("describe")
    declared_describe.add_argument(
        "--kind", choices=("skill", "script", "orchestration"), required=True
    )
    declared_describe.add_argument("--id", required=True)
    declared_plan = declared_commands.add_parser("plan")
    declared_plan.add_argument(
        "--kind", choices=("skill", "script", "orchestration"), required=True
    )
    declared_plan.add_argument("--id", required=True)
    declared_plan.add_argument("--input", type=Path, required=True)
    declared_run = declared_commands.add_parser("run-script")
    declared_run.add_argument("--id", required=True)
    declared_run.add_argument("--input", type=Path, required=True)
    declared_commands.add_parser("validate")
    metacognitive = commands.add_parser("metacognitive")
    metacognitive_commands = metacognitive.add_subparsers(
        dest="metacognitive_action", required=True
    )
    metacognitive_list = metacognitive_commands.add_parser("list")
    metacognitive_list.add_argument("--domain")
    metacognitive_describe = metacognitive_commands.add_parser("describe")
    metacognitive_describe.add_argument("--id", required=True)
    metacognitive_run = metacognitive_commands.add_parser("run")
    metacognitive_run.add_argument("--operation", required=True)
    metacognitive_run.add_argument("--input", type=Path, required=True)
    metacognitive_commands.add_parser("validate")
    scheduling = commands.add_parser("scheduling")
    scheduling_commands = scheduling.add_subparsers(
        dest="scheduling_action", required=True
    )
    scheduling_commands.add_parser("list")
    scheduling_describe = scheduling_commands.add_parser("describe")
    scheduling_describe.add_argument("--id", required=True)
    scheduling_simulate = scheduling_commands.add_parser("simulate")
    scheduling_simulate.add_argument("--input", type=Path, required=True)
    scheduling_commands.add_parser("validate")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        from .paths import declared_file_available, framework_root

        root = args.root or framework_root()
        if args.command == "validate":
            from .registry import validate_registry

            output = validate_registry(root)
        elif args.command == "doctor":
            from .platform_support import runtime_python_status

            capability_map = json.loads(
                (root / "registry" / "capability_map.json").read_text(encoding="utf-8")
            )
            active = capability_map.get("active_capabilities", [])
            registry_errors = [
                f"missing active capability surface: {item.get(field)}"
                for item in active
                for field in ("contract", "implementation", "evidence")
                if not declared_file_available(root, str(item.get(field, "")))
            ]
            registry = {
                "valid": not registry_errors,
                "active_count": len(active),
                "errors": registry_errors,
                "scope": "lightweight_startup_health",
            }
            python_status = runtime_python_status(root)
            output = {
                "valid": registry["valid"] and python_status["supported"],
                "python": sys.version.split()[0],
                "python_support": python_status,
                "registry": registry,
                "tools": {name: shutil.which(name) for name in ("git", "rg", "docker")},
            }
        elif args.command == "lifecycle":
            from .engineering_lifecycle import lifecycle_status

            status = lifecycle_status(root, args.project)
            if args.action == "status":
                output = status
            else:
                output = {
                    "valid": status["valid"],
                    "complete": status["complete"],
                    "next_stage": status["next_stage"],
                    "next_stage_contract": status["next_stage_contract"],
                    "remaining": [
                        item for item in status["checks"] if not item["complete"]
                    ],
                    "metadata_only": True,
                }
        elif args.command == "contracts":
            from .contracts import validate_contract_corpus, validate_instance

            if args.contracts_action == "status":
                output = validate_contract_corpus(root)
            else:
                schema = (
                    args.schema if args.schema.is_absolute() else root / args.schema
                )
                instance = json.loads(args.instance.read_text(encoding="utf-8"))
                validate_instance(instance, schema)
                output = {
                    "valid": True,
                    "schema": schema.resolve().as_posix(),
                    "instance": args.instance.resolve().as_posix(),
                }
        elif args.command == "integrations":
            from .integration_registry import validate_integrations

            output = validate_integrations(root, smoke=args.action == "smoke")
        elif args.command == "graphs":
            from .graph_registry import validate_graph_artifacts

            output = validate_graph_artifacts(root)
        elif args.command == "audit":
            if args.scope == "structure":
                from .structural_integrity import audit_structural_integrity

                output = audit_structural_integrity(root)
            elif args.scope == "licensing":
                from .licensing import validate_licensing, write_licensing_report

                output = (
                    write_licensing_report(root)
                    if args.write_report
                    else validate_licensing(root)
                )
            else:
                from .release_audit import audit_framework

                output = audit_framework(
                    root, require_external_manifests=args.strict_external_evidence
                )
        elif args.command == "gates":
            from .gate_runner import finalize_gates, run_gates

            if args.gates_action == "run":
                output = run_gates(
                    root, args.receipt_dir, args.gate or None, force=args.force
                )
            else:
                output = finalize_gates(root, args.receipt_dir)
        elif args.command == "process":
            from .process_memory import record_process_candidate

            record = json.loads(args.record.read_text(encoding="utf-8"))
            output = record_process_candidate(
                root, args.project, record, apply=args.apply
            )
        elif args.command == "research":
            from .research_assimilation import validate_research_candidate

            record = json.loads(args.record.read_text(encoding="utf-8"))
            output = validate_research_candidate(root, args.kind, record)
        elif args.command == "startup":
            from .startup import bounded_startup
            from .tool_recommendations import assess_project_tooling

            snapshot = bounded_startup(root, args.project)
            output = {
                "valid": True,
                "capability_metadata_count": len(snapshot.capabilities),
                "policy_summary_count": len(snapshot.policy_summaries),
                "tools": dict(snapshot.tools),
                "models": list(snapshot.models),
                "project_profile": snapshot.project_profile,
                "skill_catalog_metadata_count": len(snapshot.skill_catalog_metadata),
                "hydrated_skill_bodies": list(snapshot.hydrated_skill_bodies),
                "tooling_assessment": assess_project_tooling(root, args.project),
            }
        elif args.command == "tooling":
            from .tool_recommendations import assess_project_tooling

            output = assess_project_tooling(root, args.project)
        elif args.command == "classify":
            from .classifier import classify_task

            output = {"valid": True, **asdict(classify_task(args.task))}
        elif args.command == "select":
            from .registry import skill_navigation_index
            from .skill_navigator import navigate

            selected = navigate(
                args.goal,
                skill_navigation_index(root),
                {name: True for name in args.input},
                max_candidates=args.max_candidates,
                constraints={"max_risk": args.max_risk, "available_tools": args.tool}
                if args.tool
                else {"max_risk": args.max_risk},
                include_kinds=args.kind,
            )
            output = {
                "valid": True,
                "examined": selected.examined,
                "truncated": selected.truncated,
                "reason": selected.reason,
                "index_revision": selected.index_revision,
                "candidates": [asdict(item) for item in selected.candidates],
                "excluded": [
                    {"capability_id": capability_id, "reason": reason}
                    for capability_id, reason in selected.excluded
                ],
            }
        elif args.command == "working-set":
            from .registry import skill_navigation_index
            from .skill_navigator import select_working_set

            selected = select_working_set(args.goal, skill_navigation_index(root))
            output = {"valid": bool(selected.capability_ids), **asdict(selected)}
        elif args.command == "hydrate":
            from .lazy_loader import LazySkillLoader

            loader = LazySkillLoader.from_catalog(root)
            selected = loader.hydrate(
                args.skill, include_references=args.include_references
            )
            output = {
                "valid": True,
                "skill": selected.capability_id,
                "body": selected.body,
                "references": [
                    {"path": path, "content": content}
                    for path, content in selected.references
                ],
                "bytes_loaded": selected.bytes_loaded,
                "active_ids": list(loader.active_ids),
                "release": "process_exit_releases_hydrated_context",
            }
        elif args.command == "commission":
            from .commissioning import commission

            result = commission(
                args.project,
                args.mode,
                apply=args.apply,
                source_root=root,
                questionnaire=args.questionnaire,
            )
            output = result
        elif args.command == "intake":
            from .intake import inspect_existing_project

            output = {"valid": True, **inspect_existing_project(args.project)}
        elif args.command == "source-intake":
            from .intake_lifecycle import (
                close_intake,
                intake_status,
                open_intake,
                record_snapshot,
                require_closed_stable,
            )

            if args.action == "status":
                output = {"valid": True, **intake_status(args.state_dir)}
            elif args.action == "open":
                event = open_intake(
                    args.state_dir,
                    source_alias=args.source_alias,
                    opened_by=args.actor or "",
                )
                output = {
                    "valid": True,
                    "event": event["event"],
                    "sequence": event["sequence"],
                    "status": "open",
                }
            elif args.action == "snapshot":
                event = record_snapshot(
                    args.source, args.state_dir, source_alias=args.source_alias
                )
                snapshot = event["snapshot"]
                output = {
                    "valid": True,
                    "event": "snapshot",
                    "sequence": event["sequence"],
                    **{
                        key: snapshot[key]
                        for key in ("file_count", "byte_count", "tree_sha256")
                    },
                }
            elif args.action == "close":
                event = close_intake(
                    args.source,
                    args.state_dir,
                    source_alias=args.source_alias,
                    approved_by=args.actor or "",
                    minimum_stability_seconds=args.minimum_stability_seconds,
                )
                snapshot = event["accepted_snapshot"]
                output = {
                    "valid": True,
                    "event": "close",
                    "sequence": event["sequence"],
                    "status": "closed",
                    **{
                        key: snapshot[key]
                        for key in ("file_count", "byte_count", "tree_sha256")
                    },
                }
            else:
                snapshot = require_closed_stable(
                    args.source, args.state_dir, source_alias=args.source_alias
                )
                output = {
                    "valid": True,
                    "status": "closed_stable",
                    **{
                        key: snapshot[key]
                        for key in ("file_count", "byte_count", "tree_sha256")
                    },
                }
        elif args.command == "profiles":
            from .profiles import validate_profile_set

            output = validate_profile_set(root / "bootstrap" / "profiles")
        elif args.command == "test-profile":
            from .test_profiles import resolve_test_profile
            from .test_runner import run_test_command

            output = resolve_test_profile(root, args.name)
            if args.action == "run":
                import os

                environment = dict(os.environ)
                environment.update(
                    {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
                )
                execution = run_test_command(
                    output["command"],
                    cwd=root,
                    environment=environment,
                    timeout_seconds=output["timeout_seconds"],
                )
                output = {
                    **output,
                    **execution,
                    "profile_budget_seconds": output["timeout_seconds"],
                }
        elif args.command == "release":
            from .release_artifacts import classify_tree
            from .release_certification import (
                finalize_release,
                verify_release_certificate,
            )
            from .release_environment import validate_release_environment

            if args.release_action == "verify":
                output = verify_release_certificate(
                    root, release=args.release, artifact_dir=args.artifact_dir
                )
            elif args.release_action == "manifest":
                output = classify_tree(root)
            elif args.release_action == "environment":
                output = validate_release_environment(root)
            else:
                output = finalize_release(
                    root,
                    args.release,
                    artifact_dir=args.artifact_dir,
                    wheelhouse=args.wheelhouse,
                    signing_key=args.signing_key,
                )
        elif args.command == "brief":
            from .commissioning import apply_project_brief

            output = apply_project_brief(
                args.project, args.questionnaire, source_root=root, apply=args.apply
            )
        elif args.command == "tool-intake":
            from .tool_intake import record_tool_intake

            output = record_tool_intake(
                args.project,
                root,
                apply=args.apply if args.action == "record" else False,
                execute_scanners=args.execute_scanners,
                scanner_approval=args.approve_scanners,
                component_approval=args.approve_components,
                allowed_licenses=args.allow_license,
            )
        elif args.command == "project-check":
            from .commissioning import project_check

            output = project_check(args.project, source_root=root)
        elif args.command == "specialties":
            from .registry import load_json

            specialty_map = load_json(root / "registry" / "specialty_map.json")
            categories = specialty_map["categories"]
            if args.category:
                categories = [
                    item for item in categories if item["id"] == args.category
                ]
            output = {
                "valid": bool(categories),
                **{
                    key: specialty_map[key]
                    for key in (
                        "loading_rule",
                        "candidate_count",
                        "active_candidate_count",
                        "deferred_candidate_count",
                        "framework_only_active",
                    )
                },
                "categories": categories,
            }
            if not categories:
                output["errors"] = [f"unknown specialty category: {args.category}"]
        elif args.command == "plan":
            from .registry import skill_navigation_index
            from .skill_navigator import navigate

            selected = navigate(
                args.goal,
                skill_navigation_index(root),
                {name: True for name in args.input},
            )
            output = {
                "valid": bool(selected.candidates),
                "goal": args.goal,
                "declared_effects": sorted(set(args.effect)),
                "candidate_bundle": [asdict(item) for item in selected.candidates],
                "activation_limit": 1,
                "unload_plan": "release the selected handler and task context after its checkpointed step",
                "errors": [] if selected.candidates else [selected.reason],
            }
        elif args.command == "review-candidate":
            from .admission_controller import review_authoritative
            from .exit_codes import decision_exit_code
            from .registry import load_json

            decision = review_authoritative(
                root, load_json(args.manifest), load_json(args.evidence)
            )
            output = {
                "valid": decision.accepted,
                **asdict(decision),
                "_exit_code": decision_exit_code(decision.disposition),
            }
        elif args.command == "evaluate-admission-claims":
            from .admission_controller import (
                evaluate_claims as evaluate_admission_claims,
            )
            from .registry import load_json

            decision = evaluate_admission_claims(
                load_json(args.manifest), load_json(args.evidence)
            )
            output = {"valid": True, **asdict(decision)}
        elif args.command == "authorize":
            from .execution_contract import authorize_with_policy_evidence
            from .registry import load_json

            active = load_json(root / "registry" / "capability_map.json")[
                "active_capabilities"
            ]
            request = load_json(args.request)
            item = next(
                (
                    record
                    for record in active
                    if record["id"] == request.get("capability_id")
                ),
                None,
            )
            if item is None:
                output = {
                    "valid": False,
                    "approved": False,
                    "authoritative": False,
                    "errors": ["capability is not active"],
                }
            else:
                manifest = load_json(root / item["contract"])
                output = authorize_with_policy_evidence(root, manifest, request)
                output["valid"] = output["approved"]
        elif args.command == "simulate-authorization":
            from .execution_contract import (
                ExecutionRequest,
                PolicyDecision,
                simulate_authorization,
            )
            from .registry import load_json

            active = load_json(root / "registry" / "capability_map.json")[
                "active_capabilities"
            ]
            item = next(
                (record for record in active if record["id"] == args.capability), None
            )
            if item is None:
                output = {
                    "valid": False,
                    "approved": False,
                    "authoritative": False,
                    "errors": ["capability is not active"],
                }
            else:
                manifest = load_json(root / item["contract"])
                effects = tuple(args.effect or ["read_local"])
                output = simulate_authorization(
                    ExecutionRequest(
                        args.capability,
                        effects,
                        args.timeout,
                        args.max_tool_calls,
                        args.idempotency_key,
                    ),
                    PolicyDecision(
                        args.policy_allowed,
                        effects if args.policy_allowed else (),
                        args.approval_id,
                    ),
                    manifest,
                )
                output["valid"] = True
        elif args.command == "verify-outcome":
            from .exit_codes import decision_exit_code
            from .outcome_verifier import verify_authoritative
            from .registry import load_json

            request = load_json(args.request)
            output = verify_authoritative(root, request)
            output["valid"] = output["verified"]
            output["_exit_code"] = decision_exit_code(output["decision"])
        elif args.command == "evaluate-outcome-claims":
            from .outcome_verifier import evaluate_claims as evaluate_outcome_claims
            from .registry import load_json

            request = load_json(args.request)
            decision = evaluate_outcome_claims(
                request.get("postconditions", {}),
                request.get("evidence", []),
                policy_allowed=request.get("policy_allowed") is True,
                executor_claimed_complete=request.get("executor_claimed_complete")
                is True,
            )
            output = {"valid": True, **asdict(decision)}
        elif args.command == "retry-decision":
            from .config import load_startup_config
            from .lifecycle import FailureRecord, decide_retry
            from .registry import load_json

            data = load_json(args.failure)
            previous = FailureRecord(
                data["task_id"],
                data.get("capability_id"),
                data["fingerprint"],
                int(data["attempt"]),
                tuple(data.get("evidence_ids", ())),
                data["message"],
            )
            config = load_startup_config(root / "bootstrap" / "startup.toml")
            decision = decide_retry(
                previous,
                candidate_attempt=args.attempt,
                evidence_ids=args.evidence_id,
                max_retries=config.lifecycle.max_retries
                if args.max_retries is None
                else args.max_retries,
                require_new_evidence=config.lifecycle.retry_requires_new_evidence,
            )
            output = {"valid": decision.allowed, **asdict(decision)}
        elif args.command == "workspace":
            from .workspace_manager import (
                create_project,
                discover_projects,
                initialize_workspace,
                rebuild_workspace_projections,
                workspace_monitor,
                workspace_status,
            )

            if args.workspace_action == "init":
                output = initialize_workspace(
                    args.workspace, workspace_id=args.workspace_id, apply=args.apply
                )
            elif args.workspace_action == "discover":
                output = discover_projects(
                    args.workspace,
                    source_root=root,
                    apply=args.apply,
                    max_files=args.max_files,
                )
            elif args.workspace_action == "create-project":
                output = create_project(
                    args.workspace, args.name, source_root=root, apply=args.apply
                )
            elif args.workspace_action == "rebuild":
                output = rebuild_workspace_projections(args.workspace, apply=args.apply)
            elif args.workspace_action == "monitor":
                output = workspace_monitor(args.workspace, source_root=root)
            else:
                output = workspace_status(args.workspace, source_root=root)
        elif args.command == "project":
            from .workspace_manager import (
                activate_project,
                current_project,
                list_projects,
                release_project,
                renew_project,
                show_project,
                transition_project,
            )

            if args.project_action == "activate":
                output = activate_project(
                    args.workspace,
                    args.project_id,
                    agent_id=args.agent_id,
                    session_id=args.session_id,
                    context_reset_confirmed=args.context_reset_confirmed,
                )
            elif args.project_action == "release":
                output = release_project(
                    args.workspace,
                    session_id=args.session_id,
                    context_reset_confirmed=args.context_reset_confirmed,
                )
            elif args.project_action == "list":
                output = list_projects(args.workspace)
            elif args.project_action == "show":
                output = show_project(args.workspace, args.project_id)
            elif args.project_action == "renew":
                output = renew_project(
                    args.workspace, session_id=args.session_id, minutes=args.minutes
                )
            elif args.project_action == "transition":
                output = transition_project(
                    args.workspace,
                    args.project_id,
                    args.action,
                    args.evidence,
                    apply=args.apply,
                )
            else:
                output = current_project(args.workspace, session_id=args.session_id)
        elif args.command == "memory":
            from .workspace_manager import (
                correct_memory,
                ingest_memory,
                maintain_memory,
                memory_status,
                reconcile_memory,
                search_memory,
                transition_memory,
            )

            if args.memory_action == "ingest":
                output = ingest_memory(
                    args.workspace,
                    args.project_id,
                    args.source,
                    source_root=root,
                    session_id=args.session_id,
                    actor_id=args.actor_id,
                    apply=args.apply,
                )
            elif args.memory_action == "transition":
                output = transition_memory(
                    args.workspace,
                    args.project_id,
                    args.memory_id,
                    args.target,
                    args.evidence,
                    session_id=args.session_id,
                    actor_id=args.actor_id,
                    apply=args.apply,
                )
            elif args.memory_action == "correct":
                output = correct_memory(
                    args.workspace,
                    args.project_id,
                    args.previous_memory_id,
                    args.memory_id,
                    args.source,
                    title=args.title,
                    summary=args.summary,
                    memory_type=args.memory_type,
                    confidence=args.confidence,
                    session_id=args.session_id,
                    actor_id=args.actor_id,
                    apply=args.apply,
                )
            elif args.memory_action == "search":
                output = search_memory(
                    args.workspace,
                    args.project_id,
                    args.query,
                    actor_id=args.actor_id,
                    session_id=args.session_id,
                    limit=args.limit,
                )
            elif args.memory_action == "maintain":
                output = maintain_memory(
                    args.workspace,
                    args.project_id,
                    source_root=root,
                    session_id=args.session_id,
                    actor_id=args.actor_id,
                    apply=args.apply,
                )
            elif args.memory_action == "reconcile":
                output = reconcile_memory(
                    args.workspace,
                    args.project_id,
                    session_id=args.session_id,
                    actor_id=args.actor_id,
                    apply=args.apply,
                )
            else:
                output = memory_status(
                    args.workspace,
                    args.project_id,
                    actor_id=args.actor_id,
                    session_id=args.session_id,
                )
        elif args.command == "workflow":
            from .workspace_manager import list_workflows, run_workflow_request

            if args.workflow_action == "list":
                output = list_workflows(root)
            else:
                output = run_workflow_request(
                    args.workspace, args.request, source_root=root, apply=args.apply
                )
        elif args.command == "tools":
            from .exact_tool_certification import certify_exact_tools
            from .python_surface_certification import certify_python_surfaces

            output = certify_exact_tools(root)
            output["python_surfaces"] = certify_python_surfaces(root, output)
            output["errors"] = [
                *output.get("errors", []),
                *output["python_surfaces"].get("errors", []),
            ]
            output["valid"] = output["valid"] and output["python_surfaces"]["valid"]
        elif args.command == "declared-suite":
            from .declared_suite import (
                describe_outcome,
                list_outcomes,
                plan_outcome,
                run_script_outcome,
                validate_declared_suite,
            )

            if args.declared_action == "list":
                output = list_outcomes(root, kind=args.kind, owner=args.owner)
            elif args.declared_action == "describe":
                output = describe_outcome(root, args.kind, args.id)
            elif args.declared_action == "plan":
                output = plan_outcome(root, args.kind, args.id, load_json(args.input))
            elif args.declared_action == "run-script":
                output = run_script_outcome(root, args.id, load_json(args.input))
            else:
                output = validate_declared_suite(root)
        elif args.command == "metacognitive":
            from .metacognitive_evolution.facade import (
                describe_capability,
                list_capabilities,
                run_operation,
                validate_layer,
            )

            if args.metacognitive_action == "list":
                output = list_capabilities(root, domain=args.domain)
            elif args.metacognitive_action == "describe":
                output = describe_capability(root, args.id)
            elif args.metacognitive_action == "run":
                output = run_operation(args.operation, load_json(args.input))
            else:
                output = validate_layer(root)
        elif args.command == "scheduling":
            from .capability_scheduler import (
                describe_scheduling_capability,
                list_scheduling_capabilities,
                simulate_schedule,
                validate_scheduling_layer,
            )

            if args.scheduling_action == "list":
                output = list_scheduling_capabilities(root)
            elif args.scheduling_action == "describe":
                output = describe_scheduling_capability(root, args.id)
            elif args.scheduling_action == "simulate":
                output = simulate_schedule(load_json(args.input))
            else:
                output = validate_scheduling_layer(root)
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        output = {"valid": False, "errors": [f"{type(error).__name__}: {error}"]}
    exit_code = int(output.pop("_exit_code", 0 if output.get("valid", True) else 1))
    print(json.dumps(output, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
