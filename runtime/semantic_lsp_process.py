"""Contained language-server process launch and teardown.

No shell is involved.  POSIX servers get their own session/process group.  Windows
servers get a new process group and use ``taskkill /T`` as the tree-cleanup fallback.
The stderr reader retains only a bounded tail so a noisy server cannot consume memory.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import BinaryIO

from .semantic_lsp_types import ServerSpec
from .semantic_lsp_uri import file_uri_to_path


class LanguageServerProcessError(RuntimeError):
    pass


class ManagedLanguageServerProcess:
    def __init__(self, spec: ServerSpec):
        self.spec = spec
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None

    @property
    def process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise LanguageServerProcessError("language-server process is not started")
        return self._process

    @property
    def stdin(self) -> BinaryIO:
        stream = self.process.stdin
        if stream is None:
            raise LanguageServerProcessError("language-server stdin is unavailable")
        return stream

    @property
    def stdout(self) -> BinaryIO:
        stream = self.process.stdout
        if stream is None:
            raise LanguageServerProcessError("language-server stdout is unavailable")
        return stream

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running():
            raise LanguageServerProcessError("language-server process already running")
        root = file_uri_to_path(self.spec.root_uri)
        if not root.is_dir():
            raise LanguageServerProcessError("language-server root is unavailable")
        executable = Path(self.spec.argv[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file():
            raise LanguageServerProcessError(
                "language-server executable must be an admitted absolute file path"
            )
        env = os.environ.copy()
        env.update(self.spec.environment)
        kwargs: dict[str, object] = {}
        if os.name == "nt":
            kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            kwargs["start_new_session"] = True
        try:
            self._process = subprocess.Popen(
                list(self.spec.argv),
                cwd=root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=False,
                **kwargs,
            )
        except (OSError, ValueError) as exc:
            self._process = None
            raise LanguageServerProcessError(f"failed to launch language server: {exc}") from exc
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"px-lsp-stderr-{self.spec.server_id}",
            daemon=True,
        )
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        stream = self._process.stderr
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_tail.extend(chunk)
                    overflow = len(self._stderr_tail) - self.spec.stderr_tail_bytes
                    if overflow > 0:
                        del self._stderr_tail[:overflow]
        except OSError:
            return

    def stderr_tail(self) -> str:
        with self._stderr_lock:
            raw = bytes(self._stderr_tail)
        return raw.decode("utf-8", errors="replace")

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def _windows_tree_kill(self, *, force: bool, timeout: float) -> None:
        if self._process is None:
            return
        command = ["taskkill", "/PID", str(self._process.pid), "/T"]
        if force:
            command.append("/F")
        try:
            subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(0.1, min(timeout, 5.0)),
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                self._process.kill() if force else self._process.terminate()
            except OSError:
                pass

    def terminate_tree(self, *, timeout: float) -> None:
        if self._process is None:
            return
        process = self._process
        if process.poll() is not None:
            self.close_streams()
            return
        deadline = time.monotonic() + max(0.1, timeout)
        if os.name == "nt":
            self._windows_tree_kill(force=False, timeout=timeout)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.terminate()
                except OSError:
                    pass
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                self._windows_tree_kill(force=True, timeout=max(0.1, deadline - time.monotonic()))
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        process.kill()
                    except OSError:
                        pass
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                # Last-resort leader reap attempt. The caller receives the process state
                # through ``is_running``/stderr; never wait indefinitely here.
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired as exc:
                    raise LanguageServerProcessError(
                        f"language-server process tree did not terminate within bounded shutdown: pid={process.pid}"
                    ) from exc
        if process.poll() is None:
            raise LanguageServerProcessError(
                f"language-server process still running after bounded shutdown: pid={process.pid}"
            )
        self.close_streams()

    def close_streams(self) -> None:
        if self._process is None:
            return
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if self._stderr_thread is not None and self._stderr_thread is not threading.current_thread():
            self._stderr_thread.join(timeout=0.5)
