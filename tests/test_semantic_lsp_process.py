import os
from pathlib import Path
import sys
import time
import pytest

from runtime.semantic_lsp_process import LanguageServerProcessError, ManagedLanguageServerProcess
from runtime.semantic_lsp_types import ServerSpec
from runtime.semantic_lsp_uri import path_to_file_uri
from tests.semantic_lsp_test_support import SPAWN_TREE, wait_until


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_process_tree_termination_kills_descendant(tmp_path):
    pid_file = tmp_path / "child.pid"
    spec = ServerSpec("tree", "python", (sys.executable, str(SPAWN_TREE), str(pid_file)), path_to_file_uri(tmp_path), shutdown_timeout_seconds=2)
    managed = ManagedLanguageServerProcess(spec)
    managed.start()
    assert wait_until(pid_file.exists)
    child_pid = int(pid_file.read_text())
    assert _pid_exists(child_pid)
    managed.terminate_tree(timeout=2)
    assert not managed.is_running()
    assert wait_until(lambda: not _pid_exists(child_pid), timeout=2)


def test_stderr_tail_is_bounded(tmp_path):
    script = tmp_path / "noise.py"
    script.write_text("import sys,time; sys.stderr.write('x'*10000); sys.stderr.flush(); time.sleep(.1)", encoding="utf-8")
    spec = ServerSpec("noise", "python", (sys.executable, str(script)), path_to_file_uri(tmp_path), stderr_tail_bytes=1024)
    managed = ManagedLanguageServerProcess(spec); managed.start(); managed.wait(timeout=2)
    time.sleep(.05)
    assert len(managed.stderr_tail().encode()) <= 1024
    managed.close_streams()


def test_process_rejects_nonabsolute_unadmitted_executable(tmp_path):
    spec = ServerSpec("relative", "python", ("python", "-V"), path_to_file_uri(tmp_path))
    process = ManagedLanguageServerProcess(spec)
    with pytest.raises(LanguageServerProcessError, match="absolute file path"):
        process.start()
