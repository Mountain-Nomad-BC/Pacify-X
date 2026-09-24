from __future__ import annotations

from pathlib import Path
import sys
import time

from runtime.semantic_lsp_adapters import PYRIGHT
from runtime.semantic_lsp_client import LspClient
from runtime.semantic_lsp_types import ServerSpec
from runtime.semantic_lsp_uri import path_to_file_uri


FAKE_SERVER = Path(__file__).parent / "fixtures" / "semantic_lsp" / "fake_lsp_server.py"
SPAWN_TREE = Path(__file__).parent / "fixtures" / "semantic_lsp" / "spawn_tree.py"


def fake_spec(root: Path, *args: str, max_pending_requests: int = 128) -> ServerSpec:
    return ServerSpec(
        server_id="fake-lsp",
        language="python",
        argv=(sys.executable, str(FAKE_SERVER), *args),
        root_uri=path_to_file_uri(root),
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        shutdown_timeout_seconds=1.0,
        max_pending_requests=max_pending_requests,
    )


def start_fake_client(root: Path, *args: str, configuration=None) -> LspClient:
    client = LspClient(fake_spec(root, *args), PYRIGHT, configuration=configuration)
    client.start()
    return client


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())
