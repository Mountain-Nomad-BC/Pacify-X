from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from runtime.resource_lifecycle import ResourceManager, ResourceStatus, _process_exists
from runtime.test_profiles import resolve_test_profile
from runtime.test_runner import run_test_command, validate_timeout
from tests import pytest_guards


ROOT = Path(__file__).parents[1]


def _successful_supervision(observed: dict[str, object]):
    def run(_self, command, **kwargs):
        observed["command"] = command
        observed["action"] = kwargs["action"]
        observed["environment"] = kwargs["environment"]
        empty = SimpleNamespace(text="")
        return SimpleNamespace(
            status="exited",
            exit_code=0,
            tree_closed=True,
            duration_seconds=0.01,
            stdout=empty,
            stderr=empty,
            shutdown_mode="natural",
            receipt_path="receipt.json",
            resource_id="process-test",
        )

    return run


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan"), "10", None])
def test_invalid_timeout_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        validate_timeout(value)


def test_per_test_temp_reclaim_retries_only_transient_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "payload").write_text("owned", encoding="utf-8")
    real_rmtree = pytest_guards.shutil.rmtree
    attempts = 0
    delays: list[float] = []

    def transient_rmtree(path: Path, **_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "simulated transient access denial", str(path))
        real_rmtree(path)

    monkeypatch.setattr(pytest_guards.shutil, "rmtree", transient_rmtree)
    monkeypatch.setattr(pytest_guards.time, "sleep", delays.append)

    pytest_guards._remove_owned_child(owned)

    assert attempts == 3
    assert delays == [0.05, 0.15]
    assert not owned.exists()


def test_per_test_temp_reclaim_does_not_retry_non_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    attempts = 0

    def invalid_rmtree(_path: Path, **_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("non-transient cleanup defect")

    monkeypatch.setattr(pytest_guards.shutil, "rmtree", invalid_rmtree)
    with pytest.raises(OSError, match="non-transient cleanup defect"):
        pytest_guards._remove_owned_child(owned)
    assert attempts == 1


def test_per_test_temp_reclaim_repairs_only_owned_read_only_entries(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    read_only = owned / "git-object"
    read_only.write_bytes(b"object")
    read_only.chmod(0o444)

    pytest_guards._remove_owned_child(owned)

    assert not owned.exists()


def test_pytest_disk_budget_is_bound_to_managed_and_explicit_owned_paths(
    tmp_path: Path, monkeypatch
) -> None:
    observed = {}
    output = tmp_path / "evidence" / "report.xml"
    output.parent.mkdir()
    manager = ResourceManager(
        tmp_path / "ledger.json", receipt_dir=tmp_path / "cleanup-receipts"
    )

    monkeypatch.setattr(
        "runtime.test_runner.ProcessSupervisor.run", _successful_supervision(observed)
    )
    result = run_test_command(
        [sys.executable, "-m", "pytest", "tests/test_example.py"],
        cwd=ROOT,
        environment=os.environ,
        timeout_seconds=30,
        resource_manager=manager,
        disk_consumption_paths=(output,),
    )

    accounting = [Path(path) for path in observed["action"]["disk_consumption_paths"]]
    assert output in accounting
    assert any(path.name.startswith("pacify-x-pytest-") for path in accounting)
    managed_temp = Path(
        observed["environment"]["PACIFY_X_PYTEST_PROCESS_TEMP_ROOT"]
    )
    assert managed_temp.name == "process-temp"
    assert managed_temp.parent == accounting[1]
    assert result["test_workspace"]["reclaimed"] is True


def test_nested_cli_disk_budget_uses_one_managed_temp_custody_root(
    tmp_path: Path, monkeypatch
) -> None:
    observed = {}
    manager = ResourceManager(
        tmp_path / "ledger.json", receipt_dir=tmp_path / "cleanup-receipts"
    )

    monkeypatch.setattr(
        "runtime.test_runner.ProcessSupervisor.run", _successful_supervision(observed)
    )
    result = run_test_command(
        [sys.executable, "-m", "runtime.cli", "test-group", "run-stale"],
        cwd=ROOT,
        environment=os.environ,
        timeout_seconds=30,
        resource_manager=manager,
        manage_process_temp=True,
    )

    accounting = [Path(path) for path in observed["action"]["disk_consumption_paths"]]
    assert len(accounting) == 1
    assert accounting[0].name.startswith("pacify-x-process-")
    for variable in ("TMP", "TEMP", "TMPDIR"):
        assert Path(observed["environment"][variable]).parent == accounting[0]
    assert result["test_workspace"]["kind"] == "managed_process_temp"
    assert result["test_workspace"]["reclaimed"] is True


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
        # A fresh Windows interpreter can take longer than 250 ms to start on
        # a loaded certification host. The child still blocks for 60 seconds,
        # so this remains a bounded timeout/partial-output assertion.
        timeout_seconds=2.0,
    )
    assert result["timed_out"]
    assert "partial-out" in result["stdout"] and "partial-err" in result["stderr"]


def test_pytest_uses_registered_isolated_basetemp_and_reclaims_it(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "test_nested.py"
    test_file.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import tempfile\n\n"
        "def test_uses_bound_temp_roots(tmp_path):\n"
        "    assert tmp_path.is_dir()\n"
        "    inherited = Path(tempfile.gettempdir()).resolve()\n"
        "    assert inherited == Path(os.environ['TEMP']).resolve()\n"
        "    assert os.environ['TMP'] == os.environ['TEMP'] == os.environ['TMPDIR']\n"
        "    assert inherited.name == 'process-temp'\n"
        "    key_root = Path(os.environ['PX_STUDIO_KEY_ROOT']).resolve()\n"
        "    assert key_root.name == 'authority-keys'\n"
        "    assert Path.cwd().resolve() not in key_root.parents\n"
        "    key_root.mkdir()\n"
        "    (key_root / 'prepared.key').write_text('test-only')\n"
        "    assert inherited in Path(tempfile.mkdtemp()).resolve().parents\n",
        encoding="utf-8",
    )
    manager = ResourceManager(
        tmp_path / "ledger.json", receipt_dir=tmp_path / "cleanup-receipts"
    )
    result = run_test_command(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        cwd=ROOT,
        environment=os.environ,
        timeout_seconds=30,
        resource_manager=manager,
        run_id="nested-pytest",
    )

    assert result["valid"] is True, json.dumps(result, indent=2, default=str)
    workspace = result["test_workspace"]
    assert workspace["kind"] == "managed_pytest_basetemp"
    assert workspace["reclaimed"] is True
    assert not Path(workspace["path"]).exists()
    assert ".pytest_cache" not in result["stderr"]
    assert "PermissionError" not in result["stdout"]
    assert workspace["cleanup_id"]
    record = manager.ledger.get(workspace["resource_id"])
    assert record.status == ResourceStatus.RECLAIMED.value


def test_governed_pytest_reclaims_direct_tempfile_children_after_each_test(
    tmp_path: Path,
) -> None:
    observation = tmp_path / "created-path.txt"
    test_file = tmp_path / "test_per_test_temp_cleanup.py"
    test_file.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import tempfile\n\n"
        "import pytest\n\n"
        "@pytest.mark.parametrize('index', range(12))\n"
        "def test_direct_temporary_tree_is_bounded_per_test(index):\n"
        "    observation = Path(os.environ['PX_TEMP_OBSERVATION'])\n"
        "    if observation.exists():\n"
        "        assert not Path(observation.read_text()).exists()\n"
        "    created = Path(tempfile.mkdtemp())\n"
        "    (created / 'payload.bin').write_bytes(b'x' * (16 * 1024 * 1024))\n"
        "    observation.write_text(str(created))\n"
        "    assert created.exists()\n",
        encoding="utf-8",
    )
    manager = ResourceManager(
        tmp_path / "disk-ledger.json", receipt_dir=tmp_path / "disk-receipts"
    )
    result = run_test_command(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        cwd=ROOT,
        environment={**os.environ, "PX_TEMP_OBSERVATION": str(observation)},
        timeout_seconds=30,
        resource_manager=manager,
        run_id="per-test-temp-cleanup",
    )

    assert result["valid"] is True, json.dumps(result, indent=2, default=str)
    assert "12 passed" in result["stdout"]
    created = Path(observation.read_text(encoding="utf-8"))
    assert not created.exists()
    workspace = result["test_workspace"]
    assert workspace["reclaimed"] is True
    record = manager.ledger.get(workspace["resource_id"])
    assert record.bytes < 32 * 1024 * 1024


def test_per_test_temp_cleanup_preserves_failure_and_junit_evidence(
    tmp_path: Path,
) -> None:
    observation = tmp_path / "failed-created-path.txt"
    junit = tmp_path / "nested.junit.xml"
    test_file = tmp_path / "test_failed_temp_cleanup.py"
    test_file.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import tempfile\n\n"
        "def test_fails_after_creating_direct_temp():\n"
        "    created = Path(tempfile.mkdtemp())\n"
        "    (created / 'payload.bin').write_bytes(b'x' * (2 * 1024 * 1024))\n"
        "    Path(os.environ['PX_FAILED_TEMP_OBSERVATION']).write_text(str(created))\n"
        "    assert False, 'intentional failure remains visible'\n\n"
        "def test_failure_temp_was_still_reclaimed():\n"
        "    created = Path(Path(os.environ['PX_FAILED_TEMP_OBSERVATION']).read_text())\n"
        "    assert not created.exists()\n",
        encoding="utf-8",
    )
    manager = ResourceManager(
        tmp_path / "failure-ledger.json",
        receipt_dir=tmp_path / "failure-receipts",
    )
    result = run_test_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(test_file),
            f"--junitxml={junit}",
        ],
        cwd=ROOT,
        environment={
            **os.environ,
            "PX_FAILED_TEMP_OBSERVATION": str(observation),
        },
        timeout_seconds=30,
        resource_manager=manager,
        run_id="failed-per-test-temp-cleanup",
    )

    assert result["valid"] is False
    assert result["exit_code"] == 1
    assert "intentional failure remains visible" in result["stdout"]
    assert "1 failed, 1 passed" in result["stdout"]
    assert junit.is_file()
    junit_text = junit.read_text(encoding="utf-8")
    assert "intentional failure remains visible" in junit_text
    assert 'failures="1"' in junit_text
    assert not Path(observation.read_text(encoding="utf-8")).exists()
    assert result["test_workspace"]["reclaimed"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object proof")
def test_abrupt_outer_owner_death_kills_tree_and_reconciles_workspace(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "resource-ledger.json"
    receipt_dir = tmp_path / "cleanup-receipts"
    child_pid_path = tmp_path / "governed-child.pid"
    nested_test = tmp_path / "test_abrupt_child.py"
    nested_test.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import time\n\n"
        "def test_waits_for_abrupt_owner_death():\n"
        "    Path(os.environ['PX_ABRUPT_CHILD_PID']).write_text(str(os.getpid()))\n"
        "    print('abrupt-child-ready', flush=True)\n"
        "    time.sleep(120)\n",
        encoding="utf-8",
    )
    outer_script = tmp_path / "abrupt_outer_owner.py"
    outer_script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "from runtime.resource_lifecycle import ResourceManager\n"
        "from runtime.test_runner import run_test_command\n\n"
        "manager = ResourceManager(Path(sys.argv[1]), receipt_dir=Path(sys.argv[2]))\n"
        "run_test_command(\n"
        "    [sys.executable, '-m', 'pytest', '-q', sys.argv[3]],\n"
        "    cwd=Path(sys.argv[4]),\n"
        "    environment=os.environ,\n"
        "    timeout_seconds=120,\n"
        "    resource_manager=manager,\n"
        "    run_id='abrupt-owner-drill',\n"
        "    lane_id='governed-section-chunk',\n"
        ")\n",
        encoding="utf-8",
    )
    outer = subprocess.Popen(
        [
            sys.executable,
            str(outer_script),
            str(ledger_path),
            str(receipt_dir),
            str(nested_test),
            str(ROOT),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(ROOT), os.environ.get("PYTHONPATH", "")))
            ),
            "PX_ABRUPT_CHILD_PID": str(child_pid_path),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not child_pid_path.exists():
            if outer.poll() is not None:
                stdout, stderr = outer.communicate()
                pytest.fail(f"outer owner exited before child readiness: {stdout} {stderr}")
            time.sleep(0.05)
        assert child_pid_path.exists(), "governed child did not become ready"
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        manager = ResourceManager(ledger_path, receipt_dir=receipt_dir)
        records = manager.ledger.load()
        workspaces = [
            item
            for item in records
            if item.resource_type == "path"
            and item.run_id == "abrupt-owner-drill"
            and item.lane_id == "governed-section-chunk"
        ]
        assert len(workspaces) == 1 and Path(workspaces[0].path or "").exists()

        killed = subprocess.run(
            ["taskkill", "/PID", str(outer.pid), "/F"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
        )
        assert killed.returncode in {0, 128}, killed.stderr
        outer.wait(timeout=15)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _process_exists(child_pid):
            time.sleep(0.05)
        assert not _process_exists(child_pid), "Job-contained child survived owner death"

        reconciled = manager.reconcile(apply=True)
        assert reconciled["valid"] is True, json.dumps(reconciled, indent=2)
        assert reconciled["owned_child_processes_active"] == 0
        assert reconciled["owned_ephemeral_unexplained"] == 0
        workspace = manager.ledger.get(workspaces[0].resource_id)
        assert workspace.run_state == "abandoned"
        assert workspace.status == ResourceStatus.RECLAIMED.value
        assert not Path(workspace.path or "").exists()
    finally:
        if outer.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(outer.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                shell=False,
            )
            outer.wait(timeout=15)


def test_pytest_shared_temp_corruption_fails_at_responsible_test(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "test_corrupts_shared_temp.py"
    test_file.write_text(
        "import shutil\n\n"
        "def test_corrupts_shared_temp(request):\n"
        "    base = request.config._tmp_path_factory.getbasetemp()\n"
        "    shutil.rmtree(base)\n",
        encoding="utf-8",
    )
    manager = ResourceManager(
        tmp_path / "guard-ledger.json", receipt_dir=tmp_path / "guard-receipts"
    )
    result = run_test_command(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        cwd=ROOT,
        environment=os.environ,
        timeout_seconds=30,
        resource_manager=manager,
        run_id="nested-pytest-corruption",
    )

    assert result["valid"] is False
    assert result["exit_code"] != 0
    assert "test destroyed pytest's shared temporary root" in result["stdout"]
    assert result["test_workspace"]["reclaimed"] is True


def test_green_assertions_with_lingering_thread_are_not_accepted(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "test_leaks_thread.py"
    test_file.write_text(
        "import threading\n\n"
        "def test_leaks_thread():\n"
        "    threading.Thread(target=threading.Event().wait, name='leaked-test-thread').start()\n",
        encoding="utf-8",
    )
    manager = ResourceManager(
        tmp_path / "thread-ledger.json", receipt_dir=tmp_path / "thread-receipts"
    )
    result = run_test_command(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        cwd=ROOT,
        environment=os.environ,
        # Allow a cold nested pytest interpreter to publish its green result;
        # the deliberately leaked non-daemon thread must then keep the process
        # alive until the governed owner terminates it at this bound.
        timeout_seconds=30,
        resource_manager=manager,
        run_id="nested-pytest-thread-leak",
    )

    assert result["valid"] is False
    assert result["timed_out"] is True
    assert "1 passed" in result["stdout"]
    assert "leaked non-daemon threads" in result["stdout"]
    assert result["process_tree_terminated"] is True
    assert result["test_workspace"]["reclaimed"] is True


def test_wrapped_pytest_command_is_detected() -> None:
    from runtime.test_runner import _is_pytest_command

    assert _is_pytest_command(
        [sys.executable, "-m", "coverage", "run", "-m", "pytest", "tests"]
    )


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
