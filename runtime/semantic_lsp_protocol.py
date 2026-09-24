"""Small JSON-RPC 2.0/LSP message layer with explicit error semantics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


JSONRPC_VERSION = "2.0"
REQUEST_CANCELLED = -32800
CONTENT_MODIFIED = -32801
VOID_METHODS = frozenset({"shutdown", "exit"})


class LspProtocolError(ValueError):
    pass


class LspRemoteError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = int(code)
        self.message = str(message)
        self.data = data
        super().__init__(f"LSP remote error {self.code}: {self.message}")


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    request_id: int | str
    result: Any = None
    error: LspRemoteError | None = None


def _validate_method(method: str) -> str:
    if not isinstance(method, str) or not method.strip() or "\x00" in method:
        raise LspProtocolError("JSON-RPC method must be non-empty text")
    return method


def make_request(method: str, request_id: int | str, params: Any = None) -> dict[str, Any]:
    method = _validate_method(method)
    if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
        raise LspProtocolError("request id must be an integer or string")
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method}
    if method not in VOID_METHODS:
        payload["params"] = {} if params is None else params
    return payload


def make_notification(method: str, params: Any = None) -> dict[str, Any]:
    method = _validate_method(method)
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if method not in VOID_METHODS:
        payload["params"] = {} if params is None else params
    return payload


def make_response(request_id: int | str, result: Any = None) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error_response(request_id: int | str | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def classify_message(payload: dict[str, Any]) -> str:
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise LspProtocolError("unsupported or missing JSON-RPC version")
    has_method = isinstance(payload.get("method"), str)
    has_id = "id" in payload
    if has_method and has_id:
        return "request"
    if has_method:
        return "notification"
    if has_id and ("result" in payload or "error" in payload):
        return "response"
    raise LspProtocolError("unrecognized JSON-RPC message shape")


def parse_response(payload: dict[str, Any]) -> ParsedResponse:
    if classify_message(payload) != "response":
        raise LspProtocolError("payload is not a JSON-RPC response")
    request_id = payload["id"]
    if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
        raise LspProtocolError("response id must be an integer or string")
    if "error" in payload:
        error = payload["error"]
        if not isinstance(error, dict) or not isinstance(error.get("code"), int) or not isinstance(error.get("message"), str):
            raise LspProtocolError("malformed JSON-RPC error response")
        return ParsedResponse(request_id, error=LspRemoteError(error["code"], error["message"], error.get("data")))
    return ParsedResponse(request_id, result=payload.get("result"))
