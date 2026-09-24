import sys
import pytest

from runtime.semantic_lsp_client import LspInitializationError, LspClient
from runtime.semantic_lsp_transport import LspRequestTimeout
from runtime.semantic_lsp_adapters import PYRIGHT
from runtime.semantic_lsp_types import ServerSpec, ServerState
from runtime.semantic_lsp_uri import path_to_file_uri
from tests.semantic_lsp_test_support import FAKE_SERVER, fake_spec, start_fake_client, wait_until


def test_client_initializes_handles_server_request_and_shuts_down(tmp_path):
    client = start_fake_client(tmp_path, configuration={"python": {"analysis": {"typeCheckingMode": "strict"}}})
    try:
        assert client.capabilities.document_symbols
        assert client.request("px/test/serverRequest", {}) == [{"typeCheckingMode": "strict"}]
    finally:
        client.shutdown()
    assert client.health.snapshot().state == ServerState.STOPPED


def test_partial_initialization_failure_cleans_process(tmp_path):
    client = LspClient(fake_spec(tmp_path, "--bad-initialize"), PYRIGHT)
    with pytest.raises(LspInitializationError):
        client.start()
    assert client._transport is not None
    assert not client._transport.process.is_running()


def test_unexpected_crash_marks_health_degraded(tmp_path):
    client = start_fake_client(tmp_path, "--crash-after-initialize")
    assert wait_until(lambda: not client.is_running())
    assert client.health.snapshot().state in {ServerState.DEGRADED, ServerState.QUARANTINED}
    client.shutdown()


def test_client_honors_per_method_timeout_override(tmp_path):
    spec = ServerSpec(
        server_id="fake-timeout",
        language="python",
        argv=(sys.executable, str(FAKE_SERVER)),
        root_uri=path_to_file_uri(tmp_path),
        request_timeout_seconds=2.0,
        request_timeout_overrides={"px/test/sleep": 0.03},
        startup_timeout_seconds=2.0,
        shutdown_timeout_seconds=1.0,
    )
    client = LspClient(spec, PYRIGHT)
    client.start()
    try:
        with pytest.raises(LspRequestTimeout):
            client.request("px/test/sleep", {"seconds": 0.2})
        assert client.request("px/test/echo", {"ok": True}) == {"ok": True}
    finally:
        client.shutdown()


def test_client_uses_spec_content_modified_retry_policy(tmp_path):
    spec = ServerSpec(
        server_id="fake-retry",
        language="python",
        argv=(sys.executable, str(FAKE_SERVER), "--content-modified-once", "px/test/echo"),
        root_uri=path_to_file_uri(tmp_path),
        content_modified_retry_methods=("px/test/echo",),
        content_modified_max_attempts=2,
        startup_timeout_seconds=2.0,
        shutdown_timeout_seconds=1.0,
    )
    client = LspClient(spec, PYRIGHT)
    client.start()
    try:
        assert client.request("px/test/echo", {"retry": True}) == {"retry": True}
    finally:
        client.shutdown()
