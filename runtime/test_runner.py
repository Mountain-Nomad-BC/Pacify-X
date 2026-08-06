"""Bounded test-process execution with partial evidence and tree termination."""

from __future__ import annotations

import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from .resource_lifecycle import ResourceManager


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
) -> dict[str, object]:
    timeout = validate_timeout(timeout_seconds)
    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    resource_id = None
    if resource_manager is None:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
    else:
        record, raw_process = resource_manager.spawn_owned_process(
            command,
            cwd=cwd,
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator="runtime.test_runner",
            environment=environment,
        )
        resource_id = record.resource_id
        process = raw_process
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if resource_id:
            resource_manager.complete_process(resource_id)
        return {
            "valid": process.returncode == 0,
            "exit_code": process.returncode,
            "timed_out": False,
            "timeout_seconds": timeout,
            "duration_seconds": round(time.monotonic() - started, 6),
            "pid": process.pid,
            "stdout": stdout,
            "stderr": stderr,
            "process_tree_terminated": False,
            "termination": None,
            "resource_id": resource_id,
        }
    except subprocess.TimeoutExpired as error:
        if resource_id:
            receipt = resource_manager.terminate_owned_process(resource_id)
            termination = {
                "method": "owned_resource_manager",
                "errors": list(receipt.errors),
                "cleanup_id": receipt.cleanup_id,
            }
        else:
            termination = _terminate_tree(process)
        stdout, stderr = process.communicate(timeout=30)
        partial_stdout = stdout or error.stdout or ""
        partial_stderr = stderr or error.stderr or ""
        return {
            "valid": False,
            "exit_code": process.returncode,
            "timed_out": True,
            "timeout_seconds": timeout,
            "duration_seconds": round(time.monotonic() - started, 6),
            "pid": process.pid,
            "stdout": partial_stdout,
            "stderr": partial_stderr,
            "process_tree_terminated": process.poll() is not None,
            "termination": termination,
            "resource_id": resource_id,
            "errors": [f"test profile exceeded {timeout:g} seconds"],
        }
