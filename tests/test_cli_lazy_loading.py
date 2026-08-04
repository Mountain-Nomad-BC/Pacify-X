from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_importing_cli_does_not_hydrate_command_families() -> None:
    process = _run(
        "import json,sys; import runtime.cli; print(json.dumps(sorted(k for k in sys.modules if k.startswith('runtime.'))))"
    )
    assert process.returncode == 0, process.stderr
    loaded = set(json.loads(process.stdout))
    assert loaded <= {"runtime.cli", "runtime.version"}


def test_doctor_isolated_from_unrelated_command_import_failure() -> None:
    script = r"""
import builtins, json
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.endswith("admission_controller") or name.endswith("capability_scheduler"):
        raise ImportError("simulated unrelated command failure")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
from runtime.cli import main
raise SystemExit(main(["--root", ".", "doctor"]))
"""
    process = _run(script)
    assert process.returncode == 0, process.stderr + process.stdout
    assert json.loads(process.stdout)["valid"] is True


def test_help_and_unknown_command_keep_standard_exit_semantics() -> None:
    help_result = subprocess.run(
        [sys.executable, "-m", "runtime.cli", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    unknown = subprocess.run(
        [sys.executable, "-m", "runtime.cli", "not-a-command"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert help_result.returncode == 0 and "review-candidate" in help_result.stdout
    assert unknown.returncode == 2 and "invalid choice" in unknown.stderr
