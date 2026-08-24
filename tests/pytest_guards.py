"""Pytest isolation and shutdown invariants for governed and direct runs."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest


_INITIAL_NON_DAEMON_THREADS: set[int] = set()


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
