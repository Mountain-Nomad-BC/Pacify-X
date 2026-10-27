"""Actual Windows sharing violations and an owned process crash during staging."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from runtime import secure_publish
from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager

ROOT = Path(__file__).resolve().parents[1]


def hold_without_delete_share(path):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return api, handle


@pytest.mark.skipif(os.name != "nt", reason="actual Windows sharing semantics")
@pytest.mark.parametrize("release_reader", [True, False])
def test_real_reader_contention_never_reexecutes_producer(tmp_path, monkeypatch, release_reader):
    target = tmp_path / "state.bin"
    target.write_bytes(b"previous committed image")
    api, handle = hold_without_delete_share(target)
    timer = None
    attempts, failures, produced = [], [], []
    actual_replace = secure_publish.os.replace

    def replace(*args, **kwargs):
        attempts.append(args)
        try:
            return actual_replace(*args, **kwargs)
        except PermissionError as error:
            failures.append(error.winerror)
            raise

    def producer(stream):
        produced.append(True)
        stream.write(b"complete replacement image")
        if release_reader:
            nonlocal timer
            timer = threading.Timer(.06, lambda: api.CloseHandle(handle))
            timer.start()

    try:
        monkeypatch.setattr(secure_publish.os, "replace", replace)
        if release_reader:
            secure_publish.atomic_write_stream(target, producer)
            assert target.read_bytes() == b"complete replacement image"
        else:
            with pytest.raises(PermissionError):
                secure_publish.atomic_write_stream(target, producer)
            assert target.read_bytes() == b"previous committed image"
        assert produced == [True]
        assert len(attempts) > 1 and failures
        assert set(failures) <= {5, 32, 33}
        assert list(tmp_path.glob("*.prepared")) == []
    finally:
        if timer is not None:
            timer.join(2)
        else:
            api.CloseHandle(handle)


def test_owned_crash_retains_uncommitted_image_and_restart_does_not_adopt_it():
    owned = ROOT / ".tmp/secure-publish-operating"
    owned.mkdir(parents=True, exist_ok=True)
    manager = ResourceManager(owned / "resources.json")
    workspace_record = manager.create_workspace(owned, project_id="secure-publish",
        run_id="crash-restart", lane_id="operating-proof", creator="codex", retention_required=True)
    workspace = Path(workspace_record.path)
    target = workspace / "state.bin"
    target.write_bytes(b"previous committed image")
    worker = workspace / "crash_writer.py"
    worker.write_text("import os,sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from runtime.secure_publish import atomic_write_stream\n"
        "def writer(stream):\n"
        " stream.write(b'partial uncommitted image')\n"
        " stream.flush()\n os.fsync(stream.fileno())\n os._exit(23)\n"
        "atomic_write_stream(Path('state.bin'), writer)\n", encoding="utf-8")
    budget = dict(startup_timeout_seconds=10, idle_timeout_seconds=10,
        total_timeout_seconds=20, graceful_shutdown_seconds=1, force_shutdown_seconds=5,
        stdout_limit_bytes=4096, stderr_limit_bytes=4096)
    action = dict(action_id="secure-publish-crash-proof", effects=["process"], allowed_effects=["process"],
        target_paths=[str(workspace)], owned_paths=[str(workspace)], budget=budget,
        limits=budget, approval=True, policy_override_requested=False)
    result = ProcessSupervisor(manager).run([sys._base_executable, str(worker)], cwd=workspace,
        action=action, project_id="secure-publish", run_id="crash-restart",
        lane_id="operating-proof", creator="codex")
    assert result.exit_code == 23 and result.tree_closed is True
    assert not manager.ledger.get(result.resource_id).active
    assert target.read_bytes() == b"previous committed image"
    retained = list(workspace.glob("*.prepared"))
    assert len(retained) == 1
    before = retained[0].read_bytes()
    assert before == b"partial uncommitted image"
    secure_publish.atomic_write_bytes(target, b"new complete committed image")
    assert target.read_bytes() == b"new complete committed image"
    assert retained[0].read_bytes() == before
    assert list(workspace.glob("*.prepared")) == retained
    proof = {"schema_version":"px.secure-publish-operating-proof/1.0", "passed":True,
        "process_receipt":result.receipt_path, "resource_id":result.resource_id,
        "tree_closed":result.tree_closed, "retained_uncommitted_image":str(retained[0]),
        "retained_sha256":hashlib.sha256(before).hexdigest(),
        "source_sha256":hashlib.sha256((ROOT/"runtime/secure_publish.py").read_bytes()).hexdigest(),
        "certification":False}
    with (workspace / "operating-proof.json").open("x", encoding="utf-8") as stream:
        json.dump(proof, stream, indent=2)
