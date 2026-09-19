"""Non-consuming full PACIFY-X certification orchestration dry run.

This command evaluates configuration, command topology, current candidate
readiness, and all twelve canonical stage contracts without invoking an owner in
execute mode.  Later stages are reported as dependency-blocked rather than
falsely "passed" when an earlier real stage has not produced its state yet.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.certification_contract import CONTRACTS, STEP_ORDER  # noqa: E402
from scripts.run_release_candidate import Config as AutomationConfig, plan as automation_plan  # noqa: E402
from scripts.run_release_stage_owner import Config as StageConfig, check as stage_check, plan as stage_plan  # noqa: E402
from scripts.validate_certification_pipeline import validate as validate_pipeline  # noqa: E402

SCHEMA = "px.release-candidate-dry-run/1.0"


def _git_status(root: Path) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        timeout=60,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        raise RuntimeError("Git status unavailable during dry-run mutation guard")
    return result.stdout


def _command_target(root: Path, command: Sequence[str]) -> tuple[bool, str]:
    if len(command) >= 3 and command[1] == "-B" and command[2] == "-m":
        if len(command) < 4:
            return False, "Python -m command has no module"
        module = command[3]
        path = root / (module.replace(".", "/") + ".py")
        package = root / module.replace(".", "/") / "__main__.py"
        ok = path.is_file() or package.is_file()
        return ok, module
    if len(command) >= 3 and command[1] == "-B":
        target = root / command[2]
        return target.is_file(), command[2]
    return True, "external command"


def dry_run(automation_path: Path, stage_path: Path) -> dict[str, Any]:
    automation = AutomationConfig.load(automation_path.resolve())
    stage = StageConfig.load(stage_path.resolve())
    before = _git_status(automation.root)

    validation = validate_pipeline(automation_path, stage_path, allow_started=False)
    first_runtime_check: dict[str, Any] | None = None
    try:
        first_runtime_check = stage_check(stage, STEP_ORDER[0])
    except Exception as exc:
        first_runtime_check = {
            "schema_version": "px.release-stage-owner-check/1.0",
            "candidate_id": automation.candidate_id,
            "step": STEP_ORDER[0],
            "valid": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    stages: list[dict[str, Any]] = []
    prerequisite_chain_green = validation.get("valid") is True
    for contract in CONTRACTS:
        commands = automation.owners[contract.step]
        command_results = []
        static_valid = True
        for command in commands:
            target_ok, target = _command_target(automation.root, command)
            static_valid = static_valid and target_ok
            command_results.append(
                {
                    "argv": list(command),
                    "target": target,
                    "target_exists": target_ok,
                }
            )

        stage_owner_plan: dict[str, Any] | None = None
        if contract.owner_kind == "stage_owner":
            try:
                stage_owner_plan = stage_plan(stage, contract.step)
                static_valid = static_valid and stage_owner_plan.get("valid") is True
            except Exception as exc:
                static_valid = False
                stage_owner_plan = {"valid": False, "error": f"{type(exc).__name__}: {exc}"}

        if contract.ordinal == 1:
            runtime_check = first_runtime_check
            runtime_ready = prerequisite_chain_green and runtime_check is not None and runtime_check.get("valid") is True
            dependency_state = "READY" if runtime_ready else "BLOCKED_CURRENT_STATE"
        else:
            runtime_check = None
            runtime_ready = False
            dependency_state = "BLOCKED_BY_PREDECESSOR_NOT_EXECUTED"

        stages.append(
            {
                "ordinal": contract.ordinal,
                "step": contract.step,
                "owner_kind": contract.owner_kind,
                "one_shot": contract.one_shot,
                "phase_before": contract.phase_before,
                "phase_after": contract.phase_after,
                "release_stage": contract.release_stage,
                "receipt_schema": contract.receipt_schema,
                "receipt_candidate_field": contract.receipt_candidate_field,
                "timeout_seconds": automation.timeouts_seconds[contract.step],
                "commands": command_results,
                "static_contract": "PASS" if static_valid else "FAIL",
                "owner_plan": stage_owner_plan,
                "current_runtime_check": runtime_check,
                "dependency_state": dependency_state,
                "would_execute_now": bool(runtime_ready and static_valid),
                "actual_stage_verdict": "NOT_EXECUTED",
            }
        )

    after = _git_status(automation.root)
    nonmutating = before == after
    all_static = all(row["static_contract"] == "PASS" for row in stages)
    ready = validation.get("valid") is True and stages[0]["would_execute_now"] is True
    valid = bool(ready and all_static and nonmutating)
    return {
        "schema_version": SCHEMA,
        "candidate_id": automation.candidate_id,
        "mode": "non-consuming",
        "effects": False,
        "actual_owners_executed": 0,
        "valid": valid,
        "verdict": "WOULD_START_CANONICAL_CERTIFICATION" if valid else "BLOCKED",
        "canonical_step_order": list(STEP_ORDER),
        "pipeline_validation": validation,
        "automation_plan": automation_plan(automation),
        "stages": stages,
        "repository_status_unchanged": nonmutating,
        "notes": [
            "Only stage 1 can be runtime-ready before a fresh campaign begins.",
            "Stages 2-12 are intentionally dependency-blocked until their real predecessors produce state.",
            "A dry run never creates the identity manifest, candidate, journal, claims, receipts, tag transitions, or card mutations.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automation-config", type=Path, required=True)
    parser.add_argument("--stage-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = dry_run(args.automation_config, args.stage_config)
    except Exception as exc:
        result = {
            "schema_version": SCHEMA,
            "mode": "non-consuming",
            "effects": False,
            "valid": False,
            "verdict": "BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
