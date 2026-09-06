"""Bounded test-process execution with partial evidence and tree termination."""

from __future__ import annotations

import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from typing import Mapping, Sequence

from .process_supervisor import (
    MAX_DISK_CONSUMPTION_LIMIT_BYTES,
    ProcessBudgets,
    ProcessSupervisor,
)
from .resource_lifecycle import ResourceManager, ResourceStatus, RunState


TEST_DISK_CONSUMPTION_LIMIT_BYTES = 8 * 1024 * 1024 * 1024


def aggregate_test_disk_consumption_limit(work_units: int) -> int:
    """Bound a coordinator without weakening each owned test-unit ceiling."""

    if (
        isinstance(work_units, bool)
        or not isinstance(work_units, int)
        or work_units < 1
    ):
        raise ValueError("aggregate test work units must be a positive integer")
    return min(
        TEST_DISK_CONSUMPTION_LIMIT_BYTES * work_units,
        MAX_DISK_CONSUMPTION_LIMIT_BYTES,
    )


def validate_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError("test timeout must be a finite positive number")
    return float(value)


def _terminate_tree(process: subprocess.Popen[str]) -> dict[str, object]:
    errors: list[str] = []
    method = "process_group"
    try:
        if os.name == "nt":
            method = "taskkill_tree"
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if result.returncode not in {0, 128}:
                errors.append(
                    result.stderr.strip() or f"taskkill exit {result.returncode}"
                )
            if process.poll() is None:
                process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(f"{type(error).__name__}: {error}")
        if process.poll() is None:
            process.kill()
    return {"method": method, "errors": errors}


def _is_pytest_command(command: Sequence[str]) -> bool:
    """Recognize direct and coverage-wrapped pytest invocations."""

    return any(
        Path(str(value)).name.lower() in {"pytest", "pytest.exe"} for value in command
    )


def _has_pytest_basetemp(command: Sequence[str]) -> bool:
    return any(
        str(value) == "--basetemp" or str(value).startswith("--basetemp=")
        for value in command
    )


def _has_pytest_rootdir(command: Sequence[str]) -> bool:
    return any(
        str(value) == "--rootdir" or str(value).startswith("--rootdir=")
        for value in command
    )


def _disables_pytest_cache(command: Sequence[str]) -> bool:
    values = [str(value) for value in command]
    return any(
        value == "no:cacheprovider" and index > 0 and values[index - 1] == "-p"
        for index, value in enumerate(values)
    )


def _loads_pytest_lifecycle_guards(command: Sequence[str]) -> bool:
    values = [str(value) for value in command]
    return any(
        value == "tests.pytest_guards"
        and index > 0
        and values[index - 1] == "-p"
        for index, value in enumerate(values)
    )


def run_test_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: object,
    resource_manager: ResourceManager | None = None,
    project_id: str = "pacify-x",
    run_id: str = "test-profile",
    lane_id: str = "tests",
    disk_consumption_paths: Sequence[Path] = (),
    disk_consumption_limit_bytes: int = TEST_DISK_CONSUMPTION_LIMIT_BYTES,
    manage_process_temp: bool = False,
) -> dict[str, object]:
    timeout = validate_timeout(timeout_seconds)
    effective_timeout = max(1.0, timeout)
    if resource_manager is None:
        resource_manager = ResourceManager(
            cwd.resolve(strict=True)
            / ".engineering-bootstrap"
            / "resource-lifecycle"
            / "ledger.json"
        )
    workspace_record = None
    workspace_path: Path | None = None
    workspace_kind: str | None = None
    effective_command = list(command)
    effective_environment = dict(environment)
    accounting_paths = [Path(path).resolve(strict=False) for path in disk_consumption_paths]
    owned_paths = [cwd.resolve(strict=True)]
    pytest_workspace = _is_pytest_command(effective_command) and not _has_pytest_basetemp(
        effective_command
    )
    if pytest_workspace or manage_process_temp:
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        workspace_kind = (
            "managed_pytest_basetemp"
            if pytest_workspace
            else "managed_process_temp"
        )
        workspace_record = resource_manager.create_workspace(
            temporary_root,
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator="runtime.test_runner.pytest",
            prefix=("pacify-x-pytest-" if pytest_workspace else "pacify-x-process-"),
        )
        workspace_path = Path(workspace_record.path or "")
        accounting_paths.append(workspace_path.resolve(strict=True))
        owned_paths.append(workspace_path.resolve(strict=True))
        process_temp_path = workspace_path / "process-temp"
        process_temp_path.mkdir()
        if pytest_workspace:
            pytest_path = workspace_path / "pytest"
            pytest_path.mkdir()
            effective_command.append(f"--basetemp={pytest_path}")
        # Test code frequently uses tempfile directly rather than pytest's
        # tmp_path fixture. Bind every inherited temporary-directory spelling
        # to the same registered workspace so failures and timeouts cannot
        # strand framework clones or build/release fixtures in the user temp.
        for variable in ("TMP", "TEMP", "TMPDIR"):
            effective_environment[variable] = str(process_temp_path)
        # The lifecycle guard uses this explicit ownership marker to reclaim
        # only per-test children of the runner-owned temporary directory.  A
        # full release profile otherwise retains direct ``tempfile.mkdtemp``
        # trees from hundreds of tests until session end and can cross the
        # fail-closed disk ceiling before pytest writes JUnit evidence.
        if pytest_workspace:
            effective_environment["PACIFY_X_PYTEST_PROCESS_TEMP_ROOT"] = str(
                process_temp_path
            )
        # Governed test runs must never read, create, or mutate the operator's
        # real host authority keys. Give every managed pytest subprocess its own
        # authority root inside the exact registered/reclaimed workspace. An
        # inherited outer-test root is not a valid child-run boundary.
        effective_environment["PX_STUDIO_KEY_ROOT"] = str(
            process_temp_path / "authority-keys"
        )
    for path in accounting_paths:
        owner = path if path.is_dir() else path.parent
        resolved_owner = owner.resolve(strict=True)
        if resolved_owner not in owned_paths:
            owned_paths.append(resolved_owner)
    if _is_pytest_command(effective_command):
        if not _has_pytest_rootdir(effective_command):
            effective_command.append(f"--rootdir={cwd.resolve(strict=True)}")
        if not _disables_pytest_cache(effective_command):
            effective_command.extend(("-p", "no:cacheprovider"))
        if not _loads_pytest_lifecycle_guards(effective_command):
            # Explicit loading also covers governed tests whose files are
            # outside the repository conftest discovery tree.
            effective_command.extend(("-p", "tests.pytest_guards"))
    result: dict[str, object] = {}
    try:
        force_timeout = min(15.0, effective_timeout)
        budgets = ProcessBudgets(
            startup_timeout_seconds=effective_timeout,
            idle_timeout_seconds=effective_timeout,
            total_timeout_seconds=effective_timeout,
            graceful_shutdown_seconds=min(3.0, max(1.0, effective_timeout)),
            force_shutdown_seconds=force_timeout,
            stdout_limit_bytes=64 * 1024 * 1024,
            stderr_limit_bytes=64 * 1024 * 1024,
            disk_consumption_limit_bytes=disk_consumption_limit_bytes,
        )
        action = {
            "action_id": f"test-runner:{run_id}",
            "effects": ["process"],
            "allowed_effects": ["process"],
            "target_paths": [
                str(cwd.resolve(strict=True)),
                *(str(path) for path in accounting_paths),
            ],
            "owned_paths": [str(path) for path in owned_paths],
            "disk_consumption_paths": [str(path) for path in accounting_paths],
            "budget": {
                field: getattr(budgets, field)
                for field in ProcessBudgets.__dataclass_fields__
                if field != "poll_interval_seconds"
            },
            "limits": {
                field: getattr(budgets, field)
                for field in ProcessBudgets.__dataclass_fields__
                if field != "poll_interval_seconds"
            },
            "approval": True,
            "policy_override_requested": False,
        }
        supervised = ProcessSupervisor(resource_manager).run(
            effective_command,
            cwd=cwd,
            action=action,
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator="runtime.test_runner",
            environment=effective_environment,
        )
        timed_out = supervised.status in {
            "startup_timeout",
            "idle_timeout",
            "total_timeout",
        }
        result = {
            "valid": supervised.status == "exited"
            and supervised.exit_code == 0
            and supervised.tree_closed,
            "exit_code": supervised.exit_code,
            "timed_out": timed_out,
            "timeout_seconds": timeout,
            "duration_seconds": round(supervised.duration_seconds, 6),
            "stdout": supervised.stdout.text,
            "stderr": supervised.stderr.text,
            "process_tree_terminated": supervised.tree_closed,
            "termination": {
                "method": supervised.shutdown_mode,
                "errors": [] if supervised.tree_closed else ["process tree closure was not proven"],
                "receipt": supervised.receipt_path,
            }
            if supervised.status != "exited" or not supervised.tree_closed
            else None,
            "resource_id": supervised.resource_id,
            "supervision_receipt": supervised.receipt_path,
            "supervision_status": supervised.status,
            "disk_consumption_limit_bytes": budgets.disk_consumption_limit_bytes,
        }
        if timed_out:
            result["errors"] = [f"test profile exceeded {timeout:g} seconds"]
        elif supervised.status == "owner_lost":
            result["errors"] = [
                "test launcher exited before its supervised process tree"
            ]
        elif supervised.status == "disk_budget_exceeded":
            result["errors"] = [
                "test process exceeded its "
                f"{budgets.disk_consumption_limit_bytes} byte disk-consumption ceiling"
            ]
    except BaseException:
        if workspace_path is not None and workspace_record is not None:
            resource_manager.update(
                workspace_record.resource_id,
                active=False,
                run_state=RunState.FAILED.value,
                status=ResourceStatus.RECLAIMABLE.value,
            )
            resource_manager.reclaim(
                workspace_record.resource_id,
                reason="managed_process_spawn_failed",
                apply=True,
            )
        raise
    finally:
        if workspace_path is not None:
            cleanup_errors: list[str] = []
            cleanup_id = None
            reclaimed = False
            if workspace_record is not None:
                resource_manager.update(
                    workspace_record.resource_id,
                    active=False,
                    run_state=(
                        RunState.COMPLETED.value
                        if result.get("exit_code") == 0
                        else RunState.FAILED.value
                    ),
                    status=ResourceStatus.RECLAIMABLE.value,
                )
                cleanup = resource_manager.reclaim(
                    workspace_record.resource_id,
                    reason="managed_process_temp_scope_closed",
                    apply=True,
                )
                cleanup_id = cleanup.cleanup_id
                cleanup_errors.extend(cleanup.errors)
                reclaimed = cleanup.resources_reclaimed == 1
            result["test_workspace"] = {
                "kind": workspace_kind,
                "path": str(workspace_path),
                "resource_id": (
                    workspace_record.resource_id if workspace_record else None
                ),
                "cleanup_id": cleanup_id,
                "reclaimed": reclaimed,
                "errors": cleanup_errors,
            }
            if not reclaimed:
                result["valid"] = False
                result.setdefault("errors", []).append(
                    "managed pytest workspace was not reclaimed"
                )
    return result
