"""Mechanically reconcile composite claims with tested child-capability status."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


IMPLEMENTED_TITLES = {
    "agent_create_validate": "Validate and register a supplied agent specification",
    "chaos_resilience_cycle": "Evaluate supplied bounded resilience experiment records",
    "continuous_improvement": "Compile supplied sources into a candidate-only improvement backlog",
    "cross_project_transfer": "Validate and import an approved cross-project transfer package",
    "guarded_change": "Validate and apply or quarantine one staged change",
    "incident_diagnose_recover": "Validate and apply or quarantine one supplied recovery candidate",
    "memory_ingest_distill": "Compile supplied sources into candidate project memory",
    "memory_maintenance": "Reconcile and rebuild project memory indexes without deletion",
    "nightly_project_health": "Evaluate supplied project-health metrics",
    "project_close": "Record an evidence-backed project archive transition",
    "project_onboard": "Inventory and register one existing project",
    "project_pause_resume": "Record an evidence-backed pause or resume transition",
    "project_switch": "Validate and record an isolated project-session switch",
    "safe_cleanup": "Move explicitly supplied cleanup candidates to recoverable quarantine",
    "shared_capability_promote": "Validate and copy an approved candidate to shared capability storage",
    "workspace_bootstrap": "Initialize a bounded workspace and register dropped projects",
    "workstream_plan_dispatch": "Validate and dispatch supplied bounded workstreams",
}


def reconcile(root: Path) -> dict[str, int]:
    capability_path = root / "registry" / "project_stream_capabilities.json"
    orchestration_path = root / "registry" / "project_stream_orchestrations.json"
    handler_path = root / "registry" / "project_stream_handlers.json"
    capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
    orchestrations = json.loads(orchestration_path.read_text(encoding="utf-8"))
    handlers = json.loads(handler_path.read_text(encoding="utf-8"))
    levels = {item["id"]: item["implementation_level"] for item in capabilities["capabilities"]}
    readiness: dict[str, list[str]] = {}
    for item in orchestrations["orchestrations"]:
        declared = list(dict.fromkeys([*item.get("skills", ()), *item.get("deferred_capabilities", ())]))
        missing = sorted(skill for skill in declared if levels.get(skill) != "operational_control_or_validator")
        operational = sorted(skill for skill in declared if levels.get(skill) == "operational_control_or_validator")
        item["skills"] = operational
        item["deferred_capabilities"] = missing
        item["missing_capabilities"] = []
        item["source_status"] = "adapted-bounded-runtime"
        item["source_title"] = item.get("source_title", item["title"])
        item["title"] = IMPLEMENTED_TITLES[item["orchestration_id"]]
        item["integration_status"] = "executable_bounded_scope_with_deferred_enhancements" if missing else "executable_composite"
        readiness[item["orchestration_id"]] = missing
    executable = 0
    for item in handlers["workflows"]:
        missing = readiness[item["orchestration_id"]]
        item["status"] = "executable"
        item["deferred_capabilities"] = missing
        item["scope"] = "bounded_runtime_handler_only; deferred capabilities are excluded"
        executable += item["status"] == "executable"
    handlers["executable_count"] = executable
    handlers["plan_only_count"] = len(handlers["workflows"]) - executable
    orchestration_path.write_text(json.dumps(orchestrations, indent=2) + "\n", encoding="utf-8")
    handler_path.write_text(json.dumps(handlers, indent=2) + "\n", encoding="utf-8")
    return {"executable": executable, "plan_only": len(handlers["workflows"]) - executable}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    print(json.dumps(reconcile(parser.parse_args().root.resolve()), indent=2))
