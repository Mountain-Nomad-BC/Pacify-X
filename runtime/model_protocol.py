"""Canonical, provider-neutral model request and stream contracts.

This module is deliberately pure: it owns validation and canonical identities, not
provider routing, network/process authority, tool execution, or persistence.
Provider wire formats are translated at the boundary by model_protocol_translate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Mapping, Sequence


REQUEST_SCHEMA_VERSION = "px.model-request/1.0"
EVENT_SCHEMA_VERSION = "px.model-event/1.0"
TOKEN_COUNT_SCHEMA_VERSION = "px.model-token-count/1.0"
PROTOCOL_BINDING_SCHEMA_VERSION = "px.model-protocol-binding/1.0"

MAX_REQUEST_BYTES = 1_048_576
MAX_EVENT_BYTES = 262_144
MAX_METADATA_BYTES = 65_536
MAX_SCHEMA_BYTES = 262_144
MAX_TOOL_COUNT = 128
MAX_MESSAGE_COUNT = 4096
MAX_STREAM_EVENTS = 100_000
MAX_STREAM_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 1 * 1024 * 1024
MAX_DEADLINE_MS = 600_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_KINDS = frozenset(
    {
        "text_delta",
        "reasoning_delta",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "usage",
        "finish",
        "error",
    }
)
_TERMINAL_KINDS = frozenset({"finish", "error"})
_ALLOWED_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
_ALLOWED_PRIVACY = frozenset({"policy_gated", "isolated", "local"})
_ALLOWED_SURFACES = frozenset(
    {"terminal", "openai_chat", "openai_responses", "anthropic_messages"}
)


def canonical_json_bytes(value: object, *, limit: int) -> bytes:
    """Encode canonical finite JSON and enforce its byte budget."""
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("model protocol value must be finite canonical JSON") from error
    if len(raw) > limit:
        raise ValueError("model protocol value exceeds its configured byte bound")
    return raw


def canonical_sha256(value: object, *, limit: int) -> str:
    return hashlib.sha256(canonical_json_bytes(value, limit=limit)).hexdigest()


def _text(value: object, field_name: str, *, limit: int = 512, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be nonempty text")
    if len(value) > limit or len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds its text bound")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _positive_int(value: object, field_name: str, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{field_name} must be a bounded positive integer")
    return value


def _nonnegative_int(value: object, field_name: str, *, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{field_name} must be a bounded nonnegative integer")
    return value


def _json_object(value: object, field_name: str, *, limit: int) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{field_name} must be an object")
    for key in value:
        _text(key, f"{field_name} key", limit=256)
    canonical_json_bytes(value, limit=limit)
    return dict(value)


def _validate_content(content: object) -> object:
    if type(content) is str:
        _text(content, "message content", limit=MAX_REQUEST_BYTES, allow_empty=True)
        return content
    if type(content) is not list or len(content) > 4096:
        raise ValueError("message content must be text or a bounded content-part list")
    for index, part in enumerate(content):
        if type(part) is not dict or not part:
            raise ValueError(f"message content part {index} must be a nonempty object")
        _json_object(part, f"message content part {index}", limit=MAX_METADATA_BYTES)
    return content


def _validate_message(message: object) -> dict[str, object]:
    if type(message) is not dict:
        raise ValueError("canonical message must be an object")
    if not {"role", "content"}.issubset(message):
        raise ValueError("canonical message requires role and content")
    if set(message) - {"role", "content", "name", "tool_call_id"}:
        raise ValueError("canonical message contains undeclared fields")
    role = _text(message["role"], "message role", limit=32)
    if role not in _ALLOWED_ROLES:
        raise ValueError("canonical message role is unsupported")
    _validate_content(message["content"])
    if "name" in message:
        _text(message["name"], "message name", limit=128)
    if "tool_call_id" in message:
        _text(message["tool_call_id"], "tool_call_id", limit=256)
    return dict(message)


@dataclass(frozen=True, slots=True)
class CanonicalTool:
    """Provider-neutral function tool declaration; declaration grants no authority."""

    name: str
    description: str
    input_schema: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.name, "tool name", limit=128)
        _text(self.description, "tool description", limit=4096, allow_empty=True)
        schema = _json_object(self.input_schema, "tool input schema", limit=MAX_SCHEMA_BYTES)
        if schema.get("type") not in {None, "object"}:
            raise ValueError("tool input schema root must be an object schema")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True, slots=True)
class CanonicalModelRequest:
    """Canonical model input after routing policy, before provider translation."""

    request_id: str
    session_id: str
    client_id: str
    operation_id: str
    privacy: str
    route: str
    messages: tuple[Mapping[str, object], ...]
    tools: tuple[CanonicalTool, ...] = ()
    max_output_tokens: int = 512
    deadline_ms: int = 300_000
    response_schema: Mapping[str, object] | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("request_id", self.request_id, 256),
            ("session_id", self.session_id, 256),
            ("client_id", self.client_id, 128),
            ("operation_id", self.operation_id, 256),
            ("route", self.route, 256),
        ):
            _text(value, name, limit=limit)
        if self.privacy not in _ALLOWED_PRIVACY:
            raise ValueError("request privacy class is invalid")
        if type(self.messages) is not tuple or not 1 <= len(self.messages) <= MAX_MESSAGE_COUNT:
            raise ValueError("messages require a bounded nonempty tuple")
        for message in self.messages:
            _validate_message(message)
        if type(self.tools) is not tuple or len(self.tools) > MAX_TOOL_COUNT:
            raise ValueError("tools require a bounded tuple")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        _positive_int(self.max_output_tokens, "max_output_tokens", maximum=2**31 - 1)
        _positive_int(self.deadline_ms, "deadline_ms", maximum=MAX_DEADLINE_MS)
        if self.response_schema is not None:
            _json_object(self.response_schema, "response_schema", limit=MAX_SCHEMA_BYTES)
        _json_object(self.metadata, "metadata", limit=MAX_METADATA_BYTES)
        canonical_json_bytes(self.as_dict(), limit=MAX_REQUEST_BYTES)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "client_id": self.client_id,
            "operation_id": self.operation_id,
            "privacy": self.privacy,
            "route": self.route,
            "messages": [dict(message) for message in self.messages],
            "tools": [tool.as_dict() for tool in self.tools],
            "max_output_tokens": self.max_output_tokens,
            "deadline_ms": self.deadline_ms,
            "response_schema": dict(self.response_schema) if self.response_schema is not None else None,
            "metadata": dict(self.metadata),
        }

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.as_dict(), limit=MAX_REQUEST_BYTES)


@dataclass(frozen=True, slots=True)
class CanonicalModelEvent:
    """A normalized model stream event with exact backend identity."""

    request_id: str
    adapter_id: str
    model_id: str
    seq: int
    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.request_id, "event request_id", limit=256)
        _text(self.adapter_id, "event adapter_id", limit=128)
        _text(self.model_id, "event model_id", limit=256)
        _nonnegative_int(self.seq, "event seq", maximum=MAX_STREAM_EVENTS - 1)
        if self.kind not in _EVENT_KINDS:
            raise ValueError("canonical model event kind is invalid")
        payload = _json_object(self.payload, "event payload", limit=MAX_EVENT_BYTES)
        self._validate_payload(payload)
        canonical_json_bytes(self.as_dict(), limit=MAX_EVENT_BYTES)

    def _validate_payload(self, payload: Mapping[str, object]) -> None:
        if self.kind in {"text_delta", "reasoning_delta"}:
            if set(payload) != {"text"}:
                raise ValueError(f"{self.kind} requires only text")
            _text(payload["text"], f"{self.kind} text", limit=MAX_EVENT_BYTES, allow_empty=False)
            return
        if self.kind == "tool_call_start":
            if set(payload) != {"call_id", "name"}:
                raise ValueError("tool_call_start requires call_id and name")
            _text(payload["call_id"], "tool call id", limit=256)
            _text(payload["name"], "tool name", limit=128)
            return
        if self.kind == "tool_call_delta":
            if set(payload) != {"call_id", "arguments_delta"}:
                raise ValueError("tool_call_delta requires call_id and arguments_delta")
            _text(payload["call_id"], "tool call id", limit=256)
            _text(payload["arguments_delta"], "tool arguments delta", limit=MAX_EVENT_BYTES, allow_empty=False)
            return
        if self.kind == "tool_call_end":
            if set(payload) != {"call_id", "name", "arguments"}:
                raise ValueError("tool_call_end requires call_id, name, and arguments")
            _text(payload["call_id"], "tool call id", limit=256)
            _text(payload["name"], "tool name", limit=128)
            _json_object(payload["arguments"], "tool arguments", limit=MAX_TOOL_ARGUMENT_BYTES)
            return
        if self.kind == "usage":
            allowed = {"input_tokens", "output_tokens", "provider_request_id"}
            if set(payload) - allowed or not {"input_tokens", "output_tokens"}.issubset(payload):
                raise ValueError("usage payload fields are invalid")
            _nonnegative_int(payload["input_tokens"], "input_tokens")
            _nonnegative_int(payload["output_tokens"], "output_tokens")
            if payload.get("provider_request_id") is not None:
                _text(payload["provider_request_id"], "provider_request_id", limit=512)
            return
        if self.kind == "finish":
            if set(payload) != {"reason"}:
                raise ValueError("finish requires only reason")
            _text(payload["reason"], "finish reason", limit=128)
            return
        if self.kind == "error":
            if set(payload) != {"code", "retryable"}:
                raise ValueError("error requires code and retryable")
            _text(payload["code"], "error code", limit=128)
            if type(payload["retryable"]) is not bool:
                raise ValueError("error retryable must be boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "request_id": self.request_id,
            "adapter_id": self.adapter_id,
            "model_id": self.model_id,
            "seq": self.seq,
            "kind": self.kind,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class TokenCount:
    schema_version: str
    request_id: str
    adapter_id: str
    model_id: str
    input_tokens: int
    exact: bool

    def __post_init__(self) -> None:
        if self.schema_version != TOKEN_COUNT_SCHEMA_VERSION:
            raise ValueError("unsupported token-count schema_version")
        _text(self.request_id, "token-count request_id", limit=256)
        _text(self.adapter_id, "token-count adapter_id", limit=128)
        _text(self.model_id, "token-count model_id", limit=256)
        _nonnegative_int(self.input_tokens, "token-count input_tokens")
        if type(self.exact) is not bool:
            raise ValueError("token-count exact must be boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "adapter_id": self.adapter_id,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "exact": self.exact,
        }


class CanonicalStreamState:
    """Incremental validator and chunk-boundary-independent output accumulator."""

    def __init__(self, request_id: str, adapter_id: str, model_id: str) -> None:
        self.request_id = _text(request_id, "stream request_id", limit=256)
        self.adapter_id = _text(adapter_id, "stream adapter_id", limit=128)
        self.model_id = _text(model_id, "stream model_id", limit=256)
        self.next_seq = 0
        self.terminal_kind: str | None = None
        self.usage: dict[str, object] | None = None
        self._open_tools: dict[str, dict[str, object]] = {}
        self._completed_tools: list[dict[str, object]] = []
        self._text_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._output_bytes = 0
        self._tool_output_bytes = 0

    def accept(self, event: CanonicalModelEvent) -> None:
        if self.terminal_kind is not None:
            raise ValueError("canonical stream contains events after its terminal event")
        if (event.request_id, event.adapter_id, event.model_id) != (
            self.request_id,
            self.adapter_id,
            self.model_id,
        ):
            raise ValueError("canonical stream identity changed")
        if event.seq != self.next_seq:
            raise ValueError("canonical stream sequence is not contiguous")
        self.next_seq += 1
        if self.next_seq > MAX_STREAM_EVENTS:
            raise ValueError("canonical stream exceeds its event-count bound")
        payload = dict(event.payload)
        if event.kind in {"text_delta", "reasoning_delta"}:
            text = str(payload["text"])
            self._output_bytes += len(text.encode("utf-8"))
            if self._output_bytes > MAX_STREAM_OUTPUT_BYTES:
                raise ValueError("canonical stream exceeds its output byte bound")
            (self._text_parts if event.kind == "text_delta" else self._reasoning_parts).append(text)
        elif event.kind == "tool_call_start":
            call_id = str(payload["call_id"])
            if len(self._open_tools) + len(self._completed_tools) >= MAX_TOOL_COUNT:
                raise ValueError("canonical stream exceeds its tool-call count bound")
            if call_id in self._open_tools or any(row["call_id"] == call_id for row in self._completed_tools):
                raise ValueError("tool-call identity was reused in one stream")
            self._open_tools[call_id] = {"call_id": call_id, "name": str(payload["name"]), "arguments_text": ""}
        elif event.kind == "tool_call_delta":
            call_id = str(payload["call_id"])
            opened = self._open_tools.get(call_id)
            if opened is None:
                raise ValueError("tool-call delta arrived before tool-call start")
            arguments_text = str(opened.get("arguments_text", "")) + str(payload["arguments_delta"])
            if len(arguments_text.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                raise ValueError("canonical tool-call argument stream exceeds its byte bound")
            opened["arguments_text"] = arguments_text
        elif event.kind == "tool_call_end":
            call_id = str(payload["call_id"])
            opened = self._open_tools.pop(call_id, None)
            if opened is None:
                raise ValueError("tool-call end arrived without a matching start")
            if opened["name"] != payload["name"]:
                raise ValueError("tool-call name changed during the stream")
            arguments_text = str(opened.get("arguments_text", ""))
            if arguments_text:
                try:
                    streamed_arguments = json.loads(arguments_text)
                except json.JSONDecodeError as error:
                    raise ValueError("canonical tool-call argument deltas are not valid JSON") from error
                if type(streamed_arguments) is not dict or streamed_arguments != payload["arguments"]:
                    raise ValueError("canonical tool-call end arguments differ from streamed deltas")
            row = {"call_id": call_id, "name": str(payload["name"]), "arguments": dict(payload["arguments"])}
            encoded = canonical_json_bytes(row, limit=MAX_TOOL_ARGUMENT_BYTES)
            self._tool_output_bytes += len(encoded)
            if self._output_bytes + self._tool_output_bytes > MAX_STREAM_OUTPUT_BYTES:
                raise ValueError("canonical stream exceeds its normalized output byte bound")
            self._completed_tools.append(row)
        elif event.kind == "usage":
            if self.usage is not None:
                raise ValueError("canonical stream contains duplicate usage")
            self.usage = payload
        elif event.kind in _TERMINAL_KINDS:
            if self._open_tools:
                raise ValueError("canonical stream terminated with incomplete tool calls")
            self.terminal_kind = event.kind

    def assert_complete(self, *, require_usage: bool = True) -> None:
        if self.terminal_kind is None:
            raise ValueError("canonical stream lacks a terminal event")
        if self._open_tools:
            raise ValueError("canonical stream has incomplete tool calls")
        if require_usage and self.terminal_kind == "finish" and self.usage is None:
            raise ValueError("successful canonical stream lacks exact usage")

    def normalized_output(self) -> dict[str, object]:
        if self.terminal_kind != "finish":
            raise ValueError("normalized output exists only for successful streams")
        return {
            "text": "".join(self._text_parts),
            "reasoning": "".join(self._reasoning_parts),
            "tool_calls": list(self._completed_tools),
        }

    @property
    def output_sha256(self) -> str:
        return canonical_sha256(self.normalized_output(), limit=MAX_STREAM_OUTPUT_BYTES + MAX_TOOL_ARGUMENT_BYTES)


def validate_event_order(events: Sequence[CanonicalModelEvent], *, require_usage: bool = True) -> None:
    if not events:
        raise ValueError("empty canonical model stream")
    first = events[0]
    state = CanonicalStreamState(first.request_id, first.adapter_id, first.model_id)
    for event in events:
        state.accept(event)
    state.assert_complete(require_usage=require_usage)


def canonical_request_from_mapping(payload: Mapping[str, object]) -> CanonicalModelRequest:
    if type(payload) is not dict:
        raise ValueError("canonical request payload must be an exact object")
    expected = {
        "schema_version", "request_id", "session_id", "client_id", "operation_id", "privacy", "route",
        "messages", "tools", "max_output_tokens", "deadline_ms", "response_schema", "metadata",
    }
    if set(payload) != expected or payload.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError("canonical request requires the exact declared fields")
    raw_tools = payload.get("tools")
    if type(raw_tools) is not list:
        raise ValueError("canonical request tools must be a list")
    tools: list[CanonicalTool] = []
    for item in raw_tools:
        if type(item) is not dict or set(item) != {"name", "description", "input_schema"}:
            raise ValueError("canonical tool requires the exact declared fields")
        tools.append(CanonicalTool(item["name"], item["description"], item["input_schema"]))  # type: ignore[arg-type]
    raw_messages = payload.get("messages")
    if type(raw_messages) is not list:
        raise ValueError("canonical request messages must be a list")
    return CanonicalModelRequest(
        request_id=payload["request_id"],  # type: ignore[arg-type]
        session_id=payload["session_id"],  # type: ignore[arg-type]
        client_id=payload["client_id"],  # type: ignore[arg-type]
        operation_id=payload["operation_id"],  # type: ignore[arg-type]
        privacy=payload["privacy"],  # type: ignore[arg-type]
        route=payload["route"],  # type: ignore[arg-type]
        messages=tuple(raw_messages),
        tools=tuple(tools),
        max_output_tokens=payload["max_output_tokens"],  # type: ignore[arg-type]
        deadline_ms=payload["deadline_ms"],  # type: ignore[arg-type]
        response_schema=payload["response_schema"],  # type: ignore[arg-type]
        metadata=payload["metadata"],  # type: ignore[arg-type]
    )


def validate_protocol_surface(value: object) -> str:
    surface = _text(value, "protocol surface", limit=64)
    if surface not in _ALLOWED_SURFACES:
        raise ValueError("protocol surface is unsupported")
    return surface


def validate_sha256(value: object, field_name: str = "sha256") -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value
