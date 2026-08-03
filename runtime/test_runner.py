"""Bounded test-process execution with partial evidence and tree termination."""
from __future__ import annotations

import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Mapping, Sequence


def validate_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
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
                text=True, capture_output=True, timeout=15, check=False,
            )
            if result.returncode not in {0, 128}:
                errors.append(result.stderr.strip() or f"taskkill exit {result.returncode}")
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
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str], timeout_seconds: object,
) -> dict[str, object]:
    timeout = validate_timeout(timeout_seconds)
    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        list(command), cwd=cwd, env=dict(environment), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name != "nt", creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return {
            "valid": process.returncode == 0, "exit_code": process.returncode, "timed_out": False,
            "timeout_seconds": timeout, "duration_seconds": round(time.monotonic() - started, 6),
            "pid": process.pid, "stdout": stdout, "stderr": stderr,
            "process_tree_terminated": False, "termination": None,
        }
    except subprocess.TimeoutExpired as error:
        termination = _terminate_tree(process)
        stdout, stderr = process.communicate(timeout=30)
        partial_stdout = stdout or error.stdout or ""
        partial_stderr = stderr or error.stderr or ""
        return {
            "valid": False, "exit_code": process.returncode, "timed_out": True,
            "timeout_seconds": timeout, "duration_seconds": round(time.monotonic() - started, 6),
            "pid": process.pid, "stdout": partial_stdout, "stderr": partial_stderr,
            "process_tree_terminated": process.poll() is not None, "termination": termination,
            "errors": [f"test profile exceeded {timeout:g} seconds"],
        }
