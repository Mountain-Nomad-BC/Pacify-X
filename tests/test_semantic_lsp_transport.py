import math
from concurrent.futures import ThreadPoolExecutor
import pytest

from runtime.semantic_lsp_transport import LspRequestTimeout, StdioJsonRpcTransport, TooManyPendingRequests
from tests.semantic_lsp_test_support import fake_spec


def test_real_stdio_echo_round_trip(tmp_path):
    transport = StdioJsonRpcTransport(fake_spec(tmp_path))
    transport.start()
    try:
        assert transport.request("px/test/echo", {"x": "😀"}) == {"x": "😀"}
    finally:
        transport.close(terminate_process=True)


def test_content_modified_retry_is_method_scoped(tmp_path):
    transport = StdioJsonRpcTransport(
        fake_spec(tmp_path, "--content-modified-once", "px/test/echo"),
        content_modified_retry_methods=frozenset({"px/test/echo"}),
    )
    transport.start()
    try:
        assert transport.request("px/test/echo", {"ok": True}) == {"ok": True}
    finally:
        transport.close(terminate_process=True)


def test_timeout_does_not_poison_later_requests(tmp_path):
    transport = StdioJsonRpcTransport(fake_spec(tmp_path))
    transport.start()
    try:
        # Warm the child first so this test measures timeout recovery rather than
        # platform-dependent Python process startup latency.
        assert transport.request("px/test/echo", {"warm": True}, timeout=2.0) == {"warm": True}
        with pytest.raises(LspRequestTimeout):
            transport.request("px/test/sleep", {"seconds": 0.2}, timeout=0.03)
        assert transport.request("px/test/echo", {"after": True}, timeout=1.0) == {"after": True}
    finally:
        transport.close(terminate_process=True)


def test_pending_request_budget_is_enforced(tmp_path):
    transport = StdioJsonRpcTransport(fake_spec(tmp_path, max_pending_requests=1))
    transport.start()
    try:
        # Exclude child-process startup jitter from the concurrency-budget assertion.
        assert transport.request("px/test/echo", {"warm": True}, timeout=2.0) == {"warm": True}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(transport.request, "px/test/sleep", {"seconds": 0.15})
            import time; time.sleep(.02)
            with pytest.raises(TooManyPendingRequests):
                transport.request("px/test/echo", {"x": 1})
            assert future.result(timeout=1) is True
    finally:
        transport.close(terminate_process=True)


def test_nonfinite_request_timeouts_are_rejected_before_send(tmp_path):
    transport = StdioJsonRpcTransport(fake_spec(tmp_path))
    for bad in (float("nan"), float("inf"), True, 0.0, -1.0):
        with pytest.raises(ValueError, match="request timeout"):
            transport.request("px/test/echo", {}, timeout=bad)
    transport.close()
