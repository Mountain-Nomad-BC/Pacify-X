"""Owner-script projection driver with commissioned native process custody.

Several registry documents are generated projections that are validated against
their source on every governed run. When authored files change, those projections
go stale and the owning runtime reports it, naming the generator to run. That
detection existed but nothing ran the generators automatically, so a projection
drifted whenever an unrelated file was added.

This runs each declared owner in dependency order, then re-verifies. It never
edits a projection by hand: every change goes through the owner that declares it.

Order matters. test_group_index must precede current_evidence_index, because the
evidence index evaluates receipt currentness through the section/group status
that the test group index backs.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (label, owner script relative to ROOT, extra argv, whether --apply mutates)
PROJECTIONS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("build_claims", "scripts/build_claims.py", ("--apply",), True),
    ("test_group_index", "scripts/build_test_group_index.py", (), True),
    ("registry_envelope_inventory", "scripts/build_registry_envelope_inventory.py", (), True),
    ("provider_route_index", "scripts/build_provider_route_index.py", (), True),
    ("current_evidence_index", "scripts/build_current_evidence_index.py", ("--apply",), True),
    ("completion_status", "scripts/build_completion_status.py", (), True),
)


GUARDED_OWNER_SCRIPTS = frozenset({
    "scripts/build_historical_external_references.py",
    "scripts/build_registry_envelope_inventory.py",
    "scripts/build_test_group_index.py",
    "scripts/build_effect_surface_ownership.py",
    "scripts/build_python_surface_ownership.py",
    "scripts/build_artifact_reachability.py",
    "scripts/build_provider_route_index.py",
})

# Preserve the actual native owners when settlement is uncertain. A diagnostic
# dictionary or serialized PID cannot substitute for retained Job/process handles.
RETAINED_PROCESS_CUSTODY: dict[str, object] = {}


def admit_driver(admission_event_id: str) -> None:
    """Validate caller-supplied native write/execute scopes without granting work."""
    from runtime.guarded_registry_projection import _admit_projection_write
    from runtime.operational_gap_ledger import read_snapshot, guard_work_admission
    _admit_projection_write(ROOT, admission_event_id)
    snapshot = read_snapshot(ROOT)
    admission = next(row for row in snapshot["work_admissions"] if row["event_id"] == admission_event_id)
    scope = next((row["scope"] for row in admission.get("effect_scopes", [])
                  if row["effect"] == "execute"), None)
    if scope is None:
        raise ValueError("projection driver requires current execute admission")
    guard_work_admission(snapshot, gap_id=admission["gap_id"], effect="execute",
                         scope=scope, admission_event_id=admission_event_id)
    for _, script, _, _ in PROJECTIONS:
        if not any(script == str(item).rstrip("/") or
                   script.startswith(str(item).rstrip("/") + "/") for item in scope):
            raise ValueError("projection driver execute scope omits " + script)


def _configured_host():
    from runtime.gremlin.host_configuration import (
        load_configured_gremlin_runtime, resolve_recovery_verifier_from_environment,
    )
    from runtime.gremlin.host_process_observer import make_process_tree_poller
    from runtime.gremlin.observers import ObserverSet
    from runtime.isolated_sandbox import load_sandbox_policy
    # Real observation of the host's own supervised children (Toolhelp32);
    # the reconciliation profile claims only this enforcement surface.
    observers = ObserverSet()
    observers.register("process_tree", make_process_tree_poller())
    from runtime.gremlin.host_enforcement_backend import ProcessSupervisorEnforcementBackend

    host = load_configured_gremlin_runtime(ROOT,
        recovery_verifier=resolve_recovery_verifier_from_environment(), observers=observers,
        supervisor_backend=ProcessSupervisorEnforcementBackend())
    host.nanny.apply_sandbox_policy(load_sandbox_policy(ROOT))
    return host


def _host_configuration_digest():
    from runtime.archive_io import reject_path_links
    from runtime.gremlin.host_configuration import CONFIGURATION_RELATIVE
    from runtime.json_io import read_bounded_bytes
    path = ROOT / CONFIGURATION_RELATIVE
    reject_path_links(path)
    return hashlib.sha256(read_bounded_bytes(path, max_bytes=65536)).hexdigest()


def _sandbox_digest():
    from runtime.isolated_sandbox import load_sandbox_policy
    return load_sandbox_policy(ROOT).as_dict()["policy_sha256"]


def run(label: str, script: str, argv: tuple[str, ...], *, admission_event_id: str,
        cancel_event: threading.Event | None = None, deadline: float | None = None) -> dict[str, object]:
    """Retain exact native process/Job custody and enroll before OS release."""
    from dataclasses import asdict
    from runtime.execution_context import ExecutionContext
    from runtime.gremlin.enrollment import enroll_supervised_process
    from runtime.operational_gap_ledger import read_snapshot, guard_work_admission
    from runtime.process_supervisor import ProcessBudgets, ProcessSupervisor
    from runtime.resource_lifecycle import ResourceManager, ResourceStatus, RunState

    cancel_event = cancel_event if cancel_event is not None else threading.Event()
    admit_driver(admission_event_id)
    snapshot = read_snapshot(ROOT)
    admission = next(row for row in snapshot["work_admissions"] if row["event_id"] == admission_event_id)
    read_scope = next((row["scope"] for row in admission["effect_scopes"] if row["effect"] == "read"), None)
    if read_scope is None:
        raise ValueError("commissioned projection host requires read admission")
    key_root = os.environ.get("PX_STUDIO_KEY_ROOT", "").strip()
    if not key_root or not Path(key_root).is_absolute():
        raise ValueError("projection host requires an explicit existing PX_STUDIO_KEY_ROOT binding")
    for target in (".agentic_engineering_os_px/sandbox", ".agentic_engineering_os_px/runtime-core",
                   ".agentic_engineering_os_px/studios/authority", Path(key_root).as_posix()):
        if not any(target == str(item).rstrip("/") or target.startswith(str(item).rstrip("/") + "/") for item in read_scope):
            raise ValueError("commissioned projection host read scope omits " + target)
    guard_work_admission(snapshot, gap_id=admission["gap_id"], effect="read",
                         scope=read_scope, admission_event_id=admission_event_id)
    host_revision = _host_configuration_digest()
    host = _configured_host()  # Missing real commissioning fails before any workspace/spawn.
    if _host_configuration_digest() != host_revision:
        raise PermissionError("commissioned projection host changed during loading")
    control_root = ROOT / ".agentic_engineering_os_px/resource-lifecycle"
    manager = ResourceManager(control_root / "ledger.json")
    run_id = "projection-" + uuid4().hex
    timeout = min(1800.0, max(0.0, (deadline - time.monotonic()) if deadline is not None else 1800.0))
    if timeout <= 0:
        raise TimeoutError("projection deadline expired before workspace creation")
    deadline = min(deadline, time.monotonic() + timeout) if deadline is not None else time.monotonic() + timeout
    budgets = ProcessBudgets(startup_timeout_seconds=timeout, idle_timeout_seconds=timeout,
        total_timeout_seconds=timeout, graceful_shutdown_seconds=min(3.0, timeout),
        force_shutdown_seconds=min(15.0, timeout), stdout_limit_bytes=65536, stderr_limit_bytes=65536)
    budget = {key: value for key, value in asdict(budgets).items() if key != "poll_interval_seconds"}
    context = ExecutionContext(execution_id=run_id, parent_execution_id=None, root_execution_id=run_id,
        project_id=ROOT.as_posix(), session_id=admission["session_id"],
        revision=admission["sequence"], epoch=admission["sequence"], generation_vector_sha256=None,
        authority_reference_sha256=admission["event_sha256"],
        effect_budget_sha256=hashlib.sha256(json.dumps(budget, sort_keys=True).encode()).hexdigest(),
        cancellation_scope_id=run_id, deadline_utc=(datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(),
        actor_id=admission["actor"], provider_id=None, trace_root_id=run_id,
        gremlin_revision=host_revision, network_policy_revision=host.nanny.sandbox_policy_sha256)

    def assert_current(observed):
        if observed.context_sha256 != context.context_sha256:
            raise PermissionError("projection execution context changed")
        admit_driver(admission_event_id)  # Independent current ledger observation, not a pinned-vector echo.
        if (_host_configuration_digest() != context.gremlin_revision
                or _sandbox_digest() != context.network_policy_revision):
            raise PermissionError("commissioned host or sandbox policy became stale")
        if cancel_event is not None and cancel_event.is_set():
            raise PermissionError("projection execution was cancelled")
        if time.monotonic() >= deadline:
            raise TimeoutError("projection deadline expired")

    assert_current(context)
    workspace_parent = control_root / "projection-workspaces"
    workspace_parent.mkdir(parents=True, exist_ok=True)
    workspace = manager.create_workspace(workspace_parent,
        project_id=context.project_id, run_id=run_id, lane_id="projection-reconciliation",
        creator="scripts.regenerate_projections", prefix="projection-")
    environment = dict(os.environ)
    environment.update({key: workspace.path for key in ("TMP", "TEMP", "TMPDIR")})
    action = {"action_id": run_id, "effects": ["process"], "allowed_effects": ["process"],
        "target_paths": [str(ROOT)], "owned_paths": [str(ROOT)],
        "budget": budget, "limits": budget, "approval": True, "policy_override_requested": False}
    enrollment = None
    resource_id = None
    enforcement_job_id = ""
    result = None
    cleanup = None

    def before_release(custody):
        nonlocal enrollment, resource_id, enforcement_job_id
        assert_current(context)
        resource_id = custody.parent_resource_id
        from runtime.gremlin.host_enforcement_backend import ProcessSupervisorEnforcementBackend
        enforcement_job_id = str(custody.job_object_id or "")
        if enforcement_job_id:
            ProcessSupervisorEnforcementBackend.REGISTRY[enforcement_job_id] = supervisor
        enrollment = enroll_supervised_process(host.nanny, manager, custody,
            execution_id=run_id, agent_id="projection-reconciliation",
            policy_profile="projection-reconciliation", orchestration_id=run_id)
        return enrollment

    from runtime.process_supervisor import ProcessSupervisor as _CustodySupervisor
    supervisor = _CustodySupervisor(manager)
    try:
        result = supervisor.run([sys.executable, script, *argv], cwd=ROOT,
            action=action, project_id=context.project_id, run_id=run_id,
            lane_id="projection-reconciliation", creator="scripts.regenerate_projections",
            environment=environment, cancel_event=cancel_event, deadline=deadline,
            parent_resource_id=workspace.resource_id, before_release=before_release,
            execution_context=context, assert_execution_current=assert_current)
        if not result.tree_closed:
            raise RuntimeError("projection process tree closure remains unproven")
    finally:
        primary = sys.exception()
        try:
            from runtime.gremlin.host_enforcement_backend import ProcessSupervisorEnforcementBackend
            if enforcement_job_id:
                ProcessSupervisorEnforcementBackend.REGISTRY.pop(enforcement_job_id, None)
            if enrollment is not None and resource_id is not None:
                host.nanny.close_supervised_execution(run_id, manager, resource_id)
            if (manager._processes or manager._process_jobs or manager._failed_creation_custody
                    or manager._supervision_failures):
                raise RuntimeError("native retained process custody blocks workspace reclamation")
            manager.update(workspace.resource_id, active=False,
                run_state=RunState.COMPLETED.value if result is not None and result.exit_code == 0 else RunState.FAILED.value,
                status=ResourceStatus.RECLAIMABLE.value)
            cleanup = manager.reclaim(workspace.resource_id, reason="projection_process_scope_closed", apply=True)
            if cleanup.resources_reclaimed != 1 or cleanup.errors:
                raise RuntimeError("projection workspace cleanup remains unproven")
        except BaseException as closure_error:
            RETAINED_PROCESS_CUSTODY[run_id] = {"manager": manager, "host": host,
                "workspace_resource_id": workspace.resource_id, "process_resource_id": resource_id}
            if primary is None:
                raise
            try:
                BaseException.add_note(primary, "Projection custody closure remains uncertain: " + type(closure_error).__name__)
            except BaseException:
                pass
    return {"label": label, "script": script, "argv": list(argv),
        "exit_code": result.exit_code if result.status == "exited" and result.exit_code is not None else 1,
        "process_exit_code": result.exit_code,
        "stdout_tail": result.stdout.text.strip().splitlines()[-3:],
        "stderr_tail": result.stderr.text.strip().splitlines()[-3:],
        "resource_id": result.resource_id, "supervision_receipt": result.receipt_path,
        "supervision_status": result.status, "tree_closed": result.tree_closed,
        "execution_context_sha256": context.context_sha256, "workspace_cleanup_id": cleanup.cleanup_id}


def verify() -> dict[str, object]:
    """Re-read each owning runtime validator rather than trusting exit codes."""
    from runtime.build_claims import validate_build_claims
    from runtime.registry_envelope import validate_registry_envelopes
    from runtime.registry import validate_registry

    claims = validate_build_claims(ROOT)
    envelopes = validate_registry_envelopes(ROOT)
    registry = validate_registry(ROOT)

    from runtime.provider_gateway import scan_direct_provider_routes
    from runtime.generated_artifacts import validate_generated_artifacts

    provider = scan_direct_provider_routes(ROOT)
    generated = validate_generated_artifacts(ROOT)

    stale_projection_checks = sorted(
        name
        for name, result in generated.get("checks", {}).items()
        if not (result.get("valid") if isinstance(result, dict) else result)
    )

    return {
        "build_claims_valid": claims["valid"],
        "build_claims_errors": claims["errors"],
        "registry_envelopes_valid": envelopes["valid"],
        "registry_valid": registry["valid"],
        "registry_errors": registry["errors"],
        "provider_route_violations": provider.get("violations", []),
        "provider_route_index_current": provider.get("index_current"),
        "stale_generated_projections": stale_projection_checks,
    }


def _admission_argv(admission_event_id: str) -> tuple[str, ...]:
    # Builders that publish through guarded registry admission need the exact
    # current admission id; the driver supplies it, never the caller's shell.
    return ("--admission-event-id", admission_event_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate every declared generated projection through its owner"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify currentness without writing anything",
    )
    parser.add_argument(
        "--authoritative",
        action="store_true",
        help=(
            "run the full candidate projection rebuild declared by "
            "scripts/clean_source_export._rebuild_candidate_projections instead of "
            "the individual owner scripts"
        ),
    )
    parser.add_argument("--admission-event-id", help="explicit current native work admission for mutation")
    args = parser.parse_args(argv)

    if args.check_only:
        report = verify()
        print(json.dumps(report, indent=2, sort_keys=True))
        clean = (
            report["build_claims_valid"]
            and report["registry_envelopes_valid"]
            and report["registry_valid"]
            and not report["provider_route_violations"]
            and not report["stale_generated_projections"]
        )
        return 0 if clean else 1

    if not args.admission_event_id:
        parser.error("mutation requires --admission-event-id; no admission is created automatically")
    if args.authoritative:
        parser.error("authoritative candidate rebuild has unguarded direct publication paths; use admitted individual owners until integration is complete")
    admit_driver(args.admission_event_id)

    results = []
    for label, script, argv, _mutates in PROJECTIONS:
        if not (ROOT / script).is_file():
            results.append(
                {"label": label, "script": script, "exit_code": None,
                 "error": "declared owner script is missing"}
            )
            break
        child_argv = argv
        if script in GUARDED_OWNER_SCRIPTS:
            child_argv = (*argv, "--admission-event-id", args.admission_event_id)
        result = run(label, script, child_argv, admission_event_id=args.admission_event_id)
        results.append(result)
        if result["exit_code"] != 0:
            break

    failed = [item for item in results if item.get("exit_code") not in (0, None)]
    missing = [item for item in results if item.get("error")]

    report = {
        "projections": results,
        "failed": [item["label"] for item in failed],
        "missing_owners": [item["label"] for item in missing],
        "verification": None if failed or missing else verify(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if missing:
        return 1
    if failed:
        return 1
    verification = report["verification"]
    clean = (
        verification["build_claims_valid"]
        and verification["registry_envelopes_valid"]
        and verification["registry_valid"]
        and not verification["provider_route_violations"]
        and not verification["stale_generated_projections"]
    )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
