"""Pytest isolation and shutdown invariants for governed and direct runs."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import threading
import time

import pytest


_INITIAL_NON_DAEMON_THREADS: set[int] = set()
_MANAGED_PROCESS_TEMP_ENV = "PACIFY_X_PYTEST_PROCESS_TEMP_ROOT"
_TEMP_RECLAIM_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.15, 0.35, 0.75, 1.25)


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


def _retry_owned_writable_removal(
    function: object, path: str, exc_info: tuple[type[BaseException], BaseException, object]
) -> None:
    """Make only an owned read-only child writable, then retry its operation."""

    error = exc_info[1]
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    function(path)  # type: ignore[operator]


def _remove_owned_child(path: Path) -> None:
    """Remove one owned child with bounded transient-access-denied retries."""

    last_error: PermissionError | None = None
    for delay in _TEMP_RECLAIM_RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, onerror=_retry_owned_writable_removal)
            elif path.exists():
                raise OSError(f"unsupported managed temporary entry: {path}")
            return
        except PermissionError as error:
            last_error = error
            if not path.exists():
                return
    assert last_error is not None
    raise last_error


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
