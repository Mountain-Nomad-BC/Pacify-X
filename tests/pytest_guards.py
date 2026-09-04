"""Pytest isolation and shutdown invariants for governed and direct runs."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import threading

import pytest


_INITIAL_NON_DAEMON_THREADS: set[int] = set()
_MANAGED_PROCESS_TEMP_ENV = "PACIFY_X_PYTEST_PROCESS_TEMP_ROOT"


def _non_daemon_threads() -> list[threading.Thread]:
    current = threading.current_thread()
    return [
        thread
        for thread in threading.enumerate()
        if thread is not current and thread.is_alive() and not thread.daemon
    ]


def pytest_sessionstart(session: pytest.Session) -> None:
    _INITIAL_NON_DAEMON_THREADS.clear()
    _INITIAL_NON_DAEMON_THREADS.update(
        id(thread) for thread in _non_daemon_threads()
    )


def _remove_owned_child(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        raise OSError(f"unsupported managed temporary entry: {path}")


@pytest.fixture(autouse=True)
def _reclaim_per_test_process_temp() -> object:
    """Bound direct tempfile growth inside a governed pytest session.

    The runner supplies an explicit owned root.  Snapshotting after wider
    scoped fixtures are established and reclaiming at function-fixture
    teardown preserves session baselines while removing only entries created
    for the completed test.  Direct pytest runs without the marker are inert.
    """

    configured = os.environ.get(_MANAGED_PROCESS_TEMP_ENV)
    if not configured:
        yield
        return
    root = Path(configured).resolve(strict=True)
    baseline = {entry.name for entry in root.iterdir()}
    yield
    if not root.is_dir():
        pytest.fail(f"test destroyed managed process temporary root: {root}")
    errors: list[str] = []
    for entry in root.iterdir():
        if entry.name in baseline:
            continue
        try:
            _remove_owned_child(entry)
        except OSError as error:
            errors.append(f"{entry.name}: {type(error).__name__}: {error}")
    if errors:
        pytest.fail("managed per-test temporary cleanup failed: " + "; ".join(errors))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    """Localize deletion of pytest's shared base before the next test starts."""

    factory = getattr(item.config, "_tmp_path_factory", None)
    base: Path | None = factory.getbasetemp() if factory is not None else None
    outcome = yield
    if base is not None and not base.is_dir():
        base.mkdir(parents=True, exist_ok=True)
        outcome.force_exception(
            AssertionError(f"test destroyed pytest's shared temporary root: {base}")
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    leaked = [
        thread
        for thread in _non_daemon_threads()
        if id(thread) not in _INITIAL_NON_DAEMON_THREADS
    ]
    if not leaked:
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    description = ", ".join(
        f"{thread.name}(ident={thread.ident})" for thread in leaked
    )
    if terminal is not None:
        terminal.write_line(
            "PX shutdown invariant failed; leaked non-daemon threads: " + description,
            red=True,
        )
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
