from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import tempfile
import time

import pytest

from runtime.test_profiles import resolve_test_profile
from runtime.test_runner import run_test_command, validate_timeout


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan"), "10", None])
def test_invalid_timeout_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        validate_timeout(value)


def test_timeout_kills_process_tree() -> None:
    with tempfile.TemporaryDirectory() as directory:
        pid_file = Path(directory) / "child.pid"
        child_code = "import time; time.sleep(60)"
        parent_code = f"import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); print('parent-ready',flush=True); time.sleep(60)"
        result = run_test_command(
            [sys.executable, "-c", parent_code],
            cwd=ROOT,
            environment=os.environ,
            timeout_seconds=0.5,
        )
        assert result["timed_out"] and result["process_tree_terminated"]
        child_pid = int(pid_file.read_text())
        time.sleep(0.1)
        try:
            os.kill(child_pid, 0)
        except OSError:
            pass
        else:
            pytest.fail("timed-out test child process remains alive")


def test_timeout_preserves_partial_output() -> None:
    result = run_test_command(
        [
            sys.executable,
            "-c",
            "import sys,time; print('partial-out',flush=True); print('partial-err',file=sys.stderr,flush=True); time.sleep(60)",
        ],
        cwd=ROOT,
        environment=os.environ,
        timeout_seconds=0.25,
    )
    assert result["timed_out"]
    assert "partial-out" in result["stdout"] and "partial-err" in result["stderr"]


def test_fast_profile_excludes_release_duration_tests() -> None:
    profile = resolve_test_profile(ROOT, "fast")
    expected = {
        "tests/test_exact_tool_certification.py",
        "tests/test_installed_wheel_e2e.py",
        "tests/test_release_certification.py",
        "tests/test_release_audit.py",
    }
    assert expected.issubset(set(profile["excluded"]))
    assert not expected.intersection(profile["members"])


def test_profile_budget_is_reported_in_evidence() -> None:
    for name in ("fast", "full", "release"):
        profile = resolve_test_profile(ROOT, name)
        assert math.isfinite(profile["profile_budget_seconds"])
        assert profile["profile_budget_seconds"] == profile["timeout_seconds"] > 0
        assert "--durations=50" in profile["command"]
