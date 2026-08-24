from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from runtime.file_lock import _process_exists, _process_start_fingerprint
from runtime.process_supervisor import ProcessSupervisor, _BoundedCapture
from runtime.resource_lifecycle import ResourceManager, ResourceStatus


def _calibrated_python_startup_timeout() -> float:
    """Give semantic tests a measured interpreter-start margin on this host."""
    samples: list[float] = []
    for _ in range(2):
        started = time.monotonic()
        subprocess.run(
            [sys.executable, "-c", "pass"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        samples.append(time.monotonic() - started)
    return max(2.0, max(samples) * 4.0)


PYTHON_STARTUP_TIMEOUT = _calibrated_python_startup_timeout()


def _budget(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "startup_timeout_seconds": PYTHON_STARTUP_TIMEOUT,
        "idle_timeout_seconds": 0.5,
        "total_timeout_seconds": PYTHON_STARTUP_TIMEOUT + 1.0,
        "graceful_shutdown_seconds": 0.15,
        "force_shutdown_seconds": 4.0,
        "stdout_limit_bytes": 128,
        "stderr_limit_bytes": 128,
    }
    value.update(changes)
    return value


def _action(root: Path, **budget_changes: object) -> dict[str, object]:
    budget = _budget(**budget_changes)
    limits = _budget(
        startup_timeout_seconds=max(5.0, PYTHON_STARTUP_TIMEOUT),
        idle_timeout_seconds=max(5.0, PYTHON_STARTUP_TIMEOUT),
        total_timeout_seconds=max(15.0, PYTHON_STARTUP_TIMEOUT * 3),
        graceful_shutdown_seconds=max(10.0, PYTHON_STARTUP_TIMEOUT * 2),
        force_shutdown_seconds=max(15.0, PYTHON_STARTUP_TIMEOUT * 3),
        stdout_limit_bytes=4096,
        stderr_limit_bytes=4096,
        poll_interval_seconds=2.0,
    )
    return {
        "action_id": "test-process",
        "effects": ["process"],
        "allowed_effects": ["process"],
        "target_paths": [str(root)],
        "owned_paths": [str(root)],
        "budget": budget,
        "limits": limits,
        "approval": True,
        "policy_override_requested": False,
    }


def _set_event_when_path_exists(
    event: threading.Event,
    path: Path,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if path.exists():
        event.set()


@pytest.fixture
def harness() -> tuple[Path, ResourceManager, ProcessSupervisor]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        manager = ResourceManager(root / "state" / "resources.json")
        yield root, manager, ProcessSupervisor(manager)


def _run(
    harness: tuple[Path, ResourceManager, ProcessSupervisor],
    code: str,
    *,
    action: dict[str, object] | None = None,
    cancel_event: threading.Event | None = None,
):
    root, _, supervisor = harness
    return supervisor.run(
        [sys.executable, "-c", code],
        cwd=root,
        action=action or _action(root),
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        cancel_event=cancel_event,
    )


def test_command_plans_are_argv_only_for_windows_and_posix() -> None:
    for platform, boundary in (
        ("windows", "job_object"),
        ("posix", "new_session_process_group"),
    ):
        plan = ProcessSupervisor.command_plan(["tool", "argument"], platform=platform)
        assert plan == {
            "platform": platform,
            "argv_count": 2,
            "shell": False,
            "tree_boundary": boundary,
        }


def test_missing_supplied_authority_fails_before_spawn(harness) -> None:
    root, _, supervisor = harness
    action = _action(root)
    action["approval"] = False
    with pytest.raises(PermissionError, match="supplied"):
        supervisor.run(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=root,
            action=action,
            project_id="project",
            run_id="run",
            lane_id="lane",
            creator="test",
        )


def test_output_is_byte_bounded_and_decode_errors_are_counted(harness) -> None:
    code = (
        "import sys,time;"
        "sys.stdout.buffer.write(b'good\\xffend');sys.stdout.buffer.flush();"
        "sys.stderr.buffer.write(b'err\\xfe');sys.stderr.buffer.flush();time.sleep(.08)"
    )
    result = _run(harness, code)
    assert result.status == "exited"
    assert result.stdout.decode_error_count == 1
    assert result.stderr.decode_error_count == 1
    assert "good" in result.stdout.text
    receipt = json.loads(Path(result.receipt_path or "").read_text(encoding="utf-8"))
    assert "text" not in receipt["stdout"]
    assert "good" not in json.dumps(receipt)


@pytest.mark.parametrize(
    ("chunks", "limit", "total", "retained", "dropped", "truncated"),
    [
        ((b"abc",), 8, 3, 3, 0, False),
        ((b"12345678",), 8, 8, 8, 0, False),
        ((b"abc", b"1234567"), 8, 10, 8, 2, True),
    ],
)
def test_capture_receipt_conserves_bytes_below_at_and_above_limit(
    chunks, limit, total, retained, dropped, truncated
) -> None:
    capture = _BoundedCapture(limit, lambda: None)
    for chunk in chunks:
        capture.feed(chunk)
    result = capture.result()
    assert (result.total_bytes, result.retained_bytes, result.dropped_bytes) == (
        total,
        retained,
        dropped,
    )
    assert result.dropped_bytes == result.total_bytes - result.retained_bytes
    assert result.truncated is truncated


def test_endless_output_hits_total_timeout_and_records_drops(harness) -> None:
    action = _action(
        harness[0],
        startup_timeout_seconds=0.2,
        idle_timeout_seconds=0.3,
        total_timeout_seconds=0.45,
        stdout_limit_bytes=64,
    )
    result = _run(
        harness,
        "import sys; b=b'x'*8192\nwhile True: sys.stdout.buffer.write(b);sys.stdout.buffer.flush()",
        action=action,
    )
    assert result.status == "total_timeout"
    assert result.tree_closed
    assert result.stdout.retained_bytes == 64
    assert result.stdout.dropped_bytes > 0
    assert result.stdout.truncated


def test_hung_no_output_hits_startup_timeout(harness) -> None:
    result = _run(harness, "import time;time.sleep(30)")
    assert result.status == "startup_timeout"
    assert result.tree_closed


def test_idle_output_producer_hits_idle_timeout(harness) -> None:
    result = _run(
        harness,
        "import sys,time;print('ready',flush=True);time.sleep(30)",
    )
    assert result.status == "idle_timeout"
    assert result.tree_closed


def test_cancellation_closes_process(harness) -> None:
    cancel = threading.Event()
    ready = harness[0] / "cancellation.ready"

    worker = threading.Thread(
        target=_set_event_when_path_exists,
        args=(cancel, ready),
        kwargs={"timeout_seconds": 15.0},
    )
    worker.start()
    try:
        result = _run(
            harness,
            f"import pathlib,sys,time;pathlib.Path({str(ready)!r}).write_text('ready');print('ready',flush=True);time.sleep(30)",
            cancel_event=cancel,
        )
    finally:
        worker.join(timeout=5)
    assert result.status == "cancelled"
    assert result.tree_closed
    assert result.shutdown_mode in {"graceful", "forced"}


def test_signal_aware_process_exits_gracefully(harness) -> None:
    if os.name == "nt":
        setup = "signal.signal(signal.SIGBREAK,lambda *_:sys.exit(0))"
    else:
        setup = "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))"
    cancel = threading.Event()
    ready = harness[0] / "signal-aware.ready"

    canceller = threading.Thread(
        target=_set_event_when_path_exists,
        args=(cancel, ready),
        kwargs={"timeout_seconds": 15.0},
    )
    canceller.start()
    try:
        result = _run(
            harness,
            f"import pathlib,signal,sys,time;{setup};pathlib.Path({str(ready)!r}).write_text('ready');print('ready',flush=True);time.sleep(30)",
            action=_action(
                harness[0],
                graceful_shutdown_seconds=max(5.0, PYTHON_STARTUP_TIMEOUT),
                force_shutdown_seconds=max(8.0, PYTHON_STARTUP_TIMEOUT * 2),
            ),
            cancel_event=cancel,
        )
    finally:
        canceller.join(timeout=16)
    assert result.status == "cancelled"
    if os.name == "nt":
        # Windows services and detached hosts do not always expose a console
        # that can deliver CTRL_BREAK; the owned Job Object is the required
        # bounded fallback and must still close the complete tree.
        assert result.shutdown_mode in {"graceful", "forced"}
    else:
        assert result.shutdown_mode == "graceful"
    assert result.tree_closed


def test_exit_observed_after_cancellation_remains_cancelled(harness) -> None:
    cancel = threading.Event()
    timer = threading.Timer(0.03, cancel.set)
    timer.start()
    try:
        result = _run(
            harness,
            "import time;time.sleep(.1)",
            action=_action(
                harness[0],
                poll_interval_seconds=0.2,
            ),
            cancel_event=cancel,
        )
    finally:
        timer.cancel()
    assert result.status == "cancelled"
    assert result.tree_closed


def test_exit_observed_after_hard_total_budget_remains_timeout(harness) -> None:
    result = _run(
        harness,
        "import time;time.sleep(1)",
        action=_action(
            harness[0],
            startup_timeout_seconds=0.2,
            idle_timeout_seconds=0.2,
            total_timeout_seconds=0.2,
            poll_interval_seconds=1.5,
        ),
    )
    assert result.status == "total_timeout"
    assert result.tree_closed


def test_signal_resistant_process_uses_forced_shutdown(harness) -> None:
    if os.name == "nt":
        setup = "signal.signal(signal.SIGBREAK,signal.SIG_IGN)"
    else:
        setup = "signal.signal(signal.SIGTERM,signal.SIG_IGN)"
    ready = harness[0] / "signal-resistant.ready"
    cancel = threading.Event()

    canceller = threading.Thread(
        target=_set_event_when_path_exists,
        args=(cancel, ready),
        kwargs={"timeout_seconds": 5.0},
    )
    canceller.start()
    try:
        result = _run(
            harness,
            f"import pathlib,signal,sys,time;{setup};pathlib.Path({str(ready)!r}).write_text('ready');print('ready',flush=True);time.sleep(30)",
            cancel_event=cancel,
        )
    finally:
        canceller.join(timeout=6)
    assert result.status == "cancelled"
    assert result.shutdown_mode == "forced"
    assert result.tree_closed


def test_descendant_cannot_survive_parent_cancellation(harness) -> None:
    root = harness[0]
    pid_file = root / "descendant.pid"
    child = "import time;time.sleep(30)"
    parent = (
        "import pathlib,subprocess,sys,time;"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
        "print('ready',flush=True);time.sleep(30)"
    )
    cancel = threading.Event()

    def cancel_after_child() -> None:
        deadline = time.monotonic() + 3
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()

    worker = threading.Thread(target=cancel_after_child)
    worker.start()
    result = _run(harness, parent, cancel_event=cancel)
    worker.join(timeout=3)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while _process_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert result.tree_closed
    assert not _process_exists(child_pid)


def test_spawn_failure_is_sanitized_and_receipted(harness) -> None:
    root, _, supervisor = harness
    result = supervisor.run(
        [str(root / "missing-executable-secret-name")],
        cwd=root,
        action=_action(root),
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        environment={"TOP_SECRET": "never-persist-this"},
    )
    assert result.status == "spawn_failed"
    receipt = Path(result.receipt_path or "").read_text(encoding="utf-8")
    assert "never-persist-this" not in receipt
    assert "missing-executable-secret-name" not in receipt


def test_live_handle_remains_authoritative_when_birth_fingerprint_is_unavailable(
    harness, monkeypatch
) -> None:
    monkeypatch.setattr(
        "runtime.process_supervisor._process_start_fingerprint", lambda _pid: None
    )
    result = _run(harness, "print('ok')")
    assert result.status == "exited"
    _, manager, _ = harness
    record = manager.ledger.get(str(result.resource_id))
    assert str(record.process_identity).startswith("owned-handle:")
    assert record.active is False


def test_restart_reconciliation_refuses_unproven_identity(harness) -> None:
    root, manager, _ = harness
    record, process = manager.spawn_owned_process(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        cwd=root,
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        text=False,
    )
    manager.update(record.resource_id, process_identity="process-start:" + "0" * 64)
    restarted = ProcessSupervisor(ResourceManager(manager.ledger.path))
    result = restarted.reconcile_persisted(record.resource_id, supplied_authority=True)
    assert result["status"] == "retained_unproven"
    assert process.poll() is None
    manager.terminate_owned_process(record.resource_id, graceful_timeout_seconds=0.1)


def test_restart_reconciliation_reaps_proven_identity(harness, monkeypatch) -> None:
    root, manager, _ = harness
    record, process = manager.spawn_owned_process(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        cwd=root,
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        text=False,
    )
    fingerprint = _process_start_fingerprint(process.pid)
    assert fingerprint
    manager.update(record.resource_id, process_identity=f"process-start:{fingerprint}")
    restarted = ProcessSupervisor(ResourceManager(manager.ledger.path))
    if os.name == "nt":
        def admitted_tree_kill(*_args, **_kwargs):
            process.kill()
            return subprocess.CompletedProcess(_args[0], 0, "SUCCESS", "")

        monkeypatch.setattr(
            "runtime.process_supervisor.subprocess.run", admitted_tree_kill
        )
    waiter = threading.Thread(target=process.wait)
    waiter.start()
    result = restarted.reconcile_persisted(record.resource_id, supplied_authority=True)
    waiter.join(timeout=5)
    assert result["status"] == "reaped", result
    assert result["tree_closed"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill authority boundary")
def test_restart_reconciliation_fails_closed_when_host_denies_tree_kill(
    harness, monkeypatch
) -> None:
    root, manager, _ = harness
    record, process = manager.spawn_owned_process(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        cwd=root,
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        text=False,
    )
    fingerprint = _process_start_fingerprint(process.pid)
    assert fingerprint
    manager.update(record.resource_id, process_identity=f"process-start:{fingerprint}")
    monkeypatch.setattr(
        "runtime.process_supervisor.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            _args[0], 1, "", "ERROR: Access denied"
        ),
    )
    restarted = ProcessSupervisor(ResourceManager(manager.ledger.path))
    try:
        result = restarted.reconcile_persisted(
            record.resource_id, supplied_authority=True
        )
        assert result["status"] == "reconcile_failed"
        assert result["tree_closed"] is False
        assert result["failure_type"] == "OSError"
        retained = restarted.manager.ledger.get(record.resource_id)
        assert retained.active is True
        assert retained.status == ResourceStatus.CLEANUP_FAILED.value
    finally:
        manager.terminate_owned_process(
            record.resource_id, graceful_timeout_seconds=0.1
        )
        process.wait(timeout=5)


def test_restart_reconciliation_requires_new_supplied_authority(harness) -> None:
    root, manager, supervisor = harness
    record, process = manager.spawn_owned_process(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        cwd=root,
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
        text=False,
    )
    try:
        with pytest.raises(PermissionError, match="supplied"):
            supervisor.reconcile_persisted(record.resource_id, supplied_authority=False)
    finally:
        manager.terminate_owned_process(
            record.resource_id, graceful_timeout_seconds=0.1
        )
        process.wait(timeout=5)
