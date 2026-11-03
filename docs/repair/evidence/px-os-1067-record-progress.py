"""Record the Priority 4-6 continuation results in the human-readable progress ledger.

Additive to the task list and session record; no status is promoted beyond what the
evidence supports. Every producer disposition stays unresolved.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "docs/repair/evidence/px-os-1067-progress.json"


def sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


document = json.loads(TARGET.read_text(encoding="utf-8"))
document["updated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
document["session"] = {
    "session_id": "px-os-1067-p4-script-producers-r-20261103",
    "admission_event_id": "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036527",
    "prior_admission_closed": "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036510",
    "branch": "work/px-os-1067-b7-runtime-state",
    "baseline_head": "a4bddfde",
    "latest_checkpoint_event_id": "pending-this-pass",
}

for task in document["tasks"]:
    if task["task_id"] == "priority-4-unresolved-script-producers":
        task["status"] = "TRACED_DISPOSITIONS_UNRESOLVED"
        task["result"] = {
            "direct_site_references_reviewed": 135,
            "direct_site_references_total": 135,
            "producers_resolved": 0,
            "producers_unresolved": 78,
            "notes": (
                "All scanner-emitted references traced. Caller-directed outputs use atomic "
                "temp+os.replace with owned-ephemeral cleanup but have no destination grant. "
                "apply/check-gated repository writers were traced without authorizing them."
            ),
        }

document["tasks"].append(
    {
        "task_id": "priority-5-px-skills-owner-architecture",
        "priority": 5,
        "status": "EVIDENCE_COMPLETE_DISPOSITIONS_UNRESOLVED",
        "starting_state": "11 unresolved .px/skills producers; roles unverified.",
        "evidence": "docs/repair/evidence/px-os-1067-px-skills-owner-audit.json",
        "result": {
            "population": 11,
            "reconciles_with_census_family": True,
            "registered": 0,
            "destructive_producers": 0,
            "role_categories": "investigation labels only; none approved",
        },
        "blockers": ["Governed role and ownership decision per skill script."],
    }
)
document["tasks"].append(
    {
        "task_id": "priority-6-tooling-hardening",
        "priority": 6,
        "status": "COMPLETED",
        "changes": [
            "runtime/effect_surface.py: recognize shutil.copyfile/copyfileobj and Path.copy; "
            "exclude docs/repair/evidence tooling from the producer census.",
            "runtime/mutating_producer_registry.py: share one effect scan across "
            "discover/build/validate instead of rescanning per delegated producer.",
            "runtime/producer_census.py: pass the shared scan into build_registry.",
            "tests/test_effect_surface_copy_recognizers.py: 7 focused regression tests.",
        ],
        "result": {
            "census_elapsed_seconds": "307+ (unmeasured) -> 57",
            "effect_records": "1697 -> 1700 (two recovered copyfile writes + one Path.copy site)",
            "figure_changes": "none: 377 any-effect / 373 mutating / 216 resolved / 157 unresolved / 310 findings",
            "gate_valid": False,
        },
    }
)

document["verification"] = {
    "focused_suite": {
        "command": (
            ".venv-repair\\Scripts\\python.exe -m pytest -q tests\\test_effect_surface.py "
            "tests\\test_effect_surface_copy_recognizers.py tests\\test_output_roots.py "
            "tests\\test_mixed_destination_effects.py tests\\test_producer_census.py "
            "tests\\test_runtime_state_ownership.py"
        ),
        "passed": 88,
        "failed": 1,
        "failed_tests": ["tests/test_effect_surface.py::test_every_executable_effect_surface_is_owned_and_bounded"],
        "failure_meaning": (
            "Repository-wide green-gate assertion. Red because the inherited worktree carries "
            "310 gate findings and 157 unresolved producers. Not weakened."
        ),
        "elapsed_seconds": 207.85,
    },
    "pre_existing_inherited_failures": [
        "tests/test_effect_pure_string_discovery.py",
        "tests/test_effect_stream_discovery.py",
    ],
    "b7_matrix": {
        "runtime_producers": 68,
        "resource_groups": 32,
        "approved_owners": 0,
        "reconciles_with_live_census": True,
    },
    "census_artifact": {
        "path": "docs/repair/evidence/px-os-1067-census-2026-11-03.json",
        "sha256": sha("docs/repair/evidence/px-os-1067-census-2026-11-03.json"),
    },
}
document["pinned_sources"] = {
    "runtime/effect_surface.py": sha("runtime/effect_surface.py"),
    "runtime/mutating_producer_registry.py": sha("runtime/mutating_producer_registry.py"),
    "runtime/producer_census.py": sha("runtime/producer_census.py"),
}

temporary = TARGET.with_suffix(".json.tmp")
temporary.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
temporary.replace(TARGET)
print("progress updated")
