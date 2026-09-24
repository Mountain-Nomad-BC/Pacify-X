import sys
import pytest

from runtime.semantic_lsp_protocol import LspProtocolError, LspRemoteError, classify_message, make_notification, make_request, parse_response


def test_void_methods_omit_params_but_normal_none_becomes_object():
    assert "params" not in make_request("shutdown", 1, None)
    assert "params" not in make_notification("exit", None)
    assert make_request("workspace/configuration", 2, None)["params"] == {}


def test_message_classification():
    assert classify_message({"jsonrpc": "2.0", "id": 1, "method": "x"}) == "request"
    assert classify_message({"jsonrpc": "2.0", "method": "x"}) == "notification"
    assert classify_message({"jsonrpc": "2.0", "id": 1, "result": None}) == "response"
    with pytest.raises(LspProtocolError):
        classify_message({"jsonrpc": "1.0", "method": "x"})


def test_remote_error_preserves_code_and_data():
    parsed = parse_response({"jsonrpc": "2.0", "id": 3, "error": {"code": -1, "message": "bad", "data": {"x": 1}}})
    assert isinstance(parsed.error, LspRemoteError)
    assert parsed.error.code == -1 and parsed.error.data == {"x": 1}


from runtime.semantic_lsp_types import ServerSpec
from runtime.semantic_lsp_uri import path_to_file_uri


def test_server_spec_rejects_nonfinite_and_boolean_timeouts(tmp_path):
    base = dict(server_id="x", language="python", argv=(sys.executable,), root_uri=path_to_file_uri(tmp_path))
    for bad in (float("nan"), float("inf"), True, 0.0):
        with pytest.raises(ValueError, match="timeouts"):
            ServerSpec(**base, request_timeout_seconds=bad)


def test_server_spec_validates_retry_and_timeout_override_contracts(tmp_path):
    base = dict(server_id="x", language="python", argv=(sys.executable,), root_uri=path_to_file_uri(tmp_path))
    with pytest.raises(ValueError, match="request timeout overrides"):
        ServerSpec(**base, request_timeout_overrides={"x": float("nan")})
    with pytest.raises(ValueError, match="content_modified_max_attempts"):
        ServerSpec(**base, content_modified_max_attempts=0)
    with pytest.raises(ValueError, match="retry_methods"):
        ServerSpec(**base, content_modified_retry_methods=("",))


def test_server_spec_rejects_ambiguous_container_types(tmp_path):
    base = dict(server_id="x", language="python", root_uri=path_to_file_uri(tmp_path))
    with pytest.raises(ValueError, match="argv"):
        ServerSpec(**base, argv="python")
    with pytest.raises(ValueError, match="environment"):
        ServerSpec(**base, argv=(sys.executable,), environment=None)
    with pytest.raises(ValueError, match="initialization_options"):
        ServerSpec(**base, argv=(sys.executable,), initialization_options=[])
    with pytest.raises(ValueError, match="retry_methods"):
        ServerSpec(**base, argv=(sys.executable,), content_modified_retry_methods=["x"])
