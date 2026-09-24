"""Pure wire/canonical translation for admitted model protocol surfaces.

No function in this module opens sockets, executes tools, mutates PX state, or grants
provider authority.  It translates already-admitted requests and normalizes backend
stream frames into validated canonical events.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Iterator, Mapping

from .model_protocol import (
    CanonicalModelEvent,
    CanonicalModelRequest,
    MAX_EVENT_BYTES,
    MAX_TOOL_ARGUMENT_BYTES,
    canonical_json_bytes,
    validate_protocol_surface,
)


MAX_SSE_BUFFER_BYTES = 1_048_576
MAX_SSE_EVENT_BYTES = 524_288


def canonical_request_to_wire(
    request: CanonicalModelRequest,
    *,
    surface: str,
    model_id: str,
    stream: bool,
) -> dict[str, object]:
    """Translate a canonical request into one exact provider-compatible wire shape."""
    surface = validate_protocol_surface(surface)
    if surface == "terminal":
        raise ValueError("terminal provider shape is owned by its terminal adapter")
    if not model_id or len(model_id) > 256 or any(character.isspace() for character in model_id):
        raise ValueError("model identity is invalid for provider translation")
    messages = [dict(message) for message in request.messages]
    if surface == "openai_chat":
        payload: dict[str, object] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "px_response", "strict": True, "schema": dict(request.response_schema)},
            }
    elif surface == "openai_responses":
        payload = {
            "model": model_id,
            "input": messages,
            "max_output_tokens": request.max_output_tokens,
            "stream": stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                    "strict": True,
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "px_response",
                    "strict": True,
                    "schema": dict(request.response_schema),
                }
            }
    elif surface == "anthropic_messages":
        system_parts: list[object] = []
        anthropic_messages: list[dict[str, object]] = []
        for message in messages:
            if message.get("role") in {"system", "developer"}:
                system_parts.append(message.get("content"))
                continue
            if message.get("role") not in {"user", "assistant"}:
                raise ValueError("Anthropic translation requires tool results to be represented as user content blocks")
            anthropic_messages.append({"role": message["role"], "content": message["content"]})
        payload = {
            "model": model_id,
            "messages": anthropic_messages,
            "max_tokens": request.max_output_tokens,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(str(part) for part in system_parts)
        if request.tools:
            payload["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": dict(tool.input_schema)}
                for tool in request.tools
            ]
        if request.response_schema is not None:
            # Anthropic-compatible endpoints do not share OpenAI response_format.
            # Preserve the schema as inert metadata for a certified adapter/template;
            # never pretend wire compatibility grants structured-output support.
            raise ValueError("anthropic_messages does not accept PX response_schema without an adapter-specific certified mapping")
    else:  # pragma: no cover - validate_protocol_surface is exhaustive
        raise ValueError("unsupported protocol surface")
    canonical_json_bytes(payload, limit=1_048_576)
    return payload


def iter_sse_frames(chunks: Iterable[bytes | str]) -> Iterator[tuple[str | None, str]]:
    """Parse bounded SSE frames independent of transport chunk boundaries."""
    buffer = ""
    event_name: str | None = None
    data_lines: list[str] = []
    event_bytes = 0

    def emit() -> tuple[str | None, str] | None:
        nonlocal event_name, data_lines, event_bytes
        if not data_lines:
            event_name = None
            event_bytes = 0
            return None
        data = "\n".join(data_lines)
        if len(data.encode("utf-8")) > MAX_SSE_EVENT_BYTES:
            raise ValueError("SSE event exceeds its byte bound")
        result = (event_name, data)
        event_name = None
        data_lines = []
        event_bytes = 0
        return result

    for chunk in chunks:
        if isinstance(chunk, bytes):
            try:
                text = chunk.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("SSE stream contains invalid UTF-8") from error
        elif isinstance(chunk, str):
            text = chunk
        else:
            raise ValueError("SSE chunks must be bytes or text")
        buffer += text
        if len(buffer.encode("utf-8")) > MAX_SSE_BUFFER_BYTES:
            raise ValueError("SSE parser buffer exceeds its byte bound")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            if line == "":
                result = emit()
                if result is not None:
                    yield result
                continue
            if line.startswith(":"):
                continue
            if ":" in line:
                field, value = line.split(":", 1)
                if value.startswith(" "):
                    value = value[1:]
            else:
                field, value = line, ""
            if field == "event":
                if len(value) > 256:
                    raise ValueError("SSE event name exceeds its bound")
                event_name = value
            elif field == "data":
                event_bytes += len(value.encode("utf-8"))
                if event_bytes > MAX_SSE_EVENT_BYTES:
                    raise ValueError("SSE event exceeds its byte bound")
                data_lines.append(value)
            # id/retry/unknown fields are intentionally ignored.
    if buffer:
        if buffer.endswith("\r"):
            buffer = buffer[:-1]
        if buffer:
            if buffer.startswith("data:"):
                value = buffer[5:].lstrip(" ")
                data_lines.append(value)
            elif not buffer.startswith(":"):
                raise ValueError("SSE stream ended with an incomplete frame")
    result = emit()
    if result is not None:
        yield result


@dataclass(slots=True)
class _ToolAssembly:
    call_id: str
    name: str
    arguments: str = ""
    complete_initial_arguments: bool = False

    def add(self, fragment: str) -> None:
        if self.complete_initial_arguments:
            raise ValueError("tool arguments were already complete at call start")
        self.arguments += fragment
        if len(self.arguments.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
            raise ValueError("streamed tool arguments exceed their byte bound")

    def parsed(self) -> dict[str, object]:
        try:
            value = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as error:
            raise ValueError("streamed tool arguments are not valid JSON") from error
        if type(value) is not dict:
            raise ValueError("streamed tool arguments must decode to an object")
        canonical_json_bytes(value, limit=MAX_TOOL_ARGUMENT_BYTES)
        return value


class WireStreamTranslator:
    """Stateful backend-frame normalizer for one exact request and surface."""

    def __init__(self, *, surface: str, request_id: str, adapter_id: str, model_id: str) -> None:
        self.surface = validate_protocol_surface(surface)
        if self.surface == "terminal":
            raise ValueError("terminal surface does not have an SSE translator")
        self.request_id = request_id
        self.adapter_id = adapter_id
        self.model_id = model_id
        self.seq = 0
        self.finished = False
        self._tools_by_index: dict[int, _ToolAssembly] = {}
        self._tools_by_id: dict[str, _ToolAssembly] = {}
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._provider_request_id: str | None = None
        self._anthropic_block_tool: dict[int, str] = {}
        self._pending_finish_reason: str | None = None

    def _event(self, kind: str, payload: Mapping[str, object]) -> CanonicalModelEvent:
        event = CanonicalModelEvent(self.request_id, self.adapter_id, self.model_id, self.seq, kind, payload)
        self.seq += 1
        return event

    def _usage_events(self) -> list[CanonicalModelEvent]:
        if self._input_tokens is None or self._output_tokens is None:
            return []
        payload: dict[str, object] = {"input_tokens": self._input_tokens, "output_tokens": self._output_tokens}
        if self._provider_request_id:
            payload["provider_request_id"] = self._provider_request_id
        # Emit only once.
        self._input_tokens = None
        self._output_tokens = None
        return [self._event("usage", payload)]

    def _finish_tools(self) -> list[CanonicalModelEvent]:
        out: list[CanonicalModelEvent] = []
        for key in sorted(self._tools_by_index):
            tool = self._tools_by_index[key]
            out.append(self._event("tool_call_end", {"call_id": tool.call_id, "name": tool.name, "arguments": tool.parsed()}))
        self._tools_by_index.clear()
        self._tools_by_id.clear()
        self._anthropic_block_tool.clear()
        return out

    def _terminal(self, reason: str) -> list[CanonicalModelEvent]:
        if self.finished:
            return []
        out = self._finish_tools()
        out.extend(self._usage_events())
        out.append(self._event("finish", {"reason": reason or "stop"}))
        self.finished = True
        return out

    def feed_sse(self, event_name: str | None, data: str) -> list[CanonicalModelEvent]:
        if data == "[DONE]":
            if self.finished:
                return []
            return self._terminal(self._pending_finish_reason or "stop")
        if self.finished:
            raise ValueError("provider stream produced data after terminal normalization")
        if len(data.encode("utf-8")) > MAX_SSE_EVENT_BYTES:
            raise ValueError("provider SSE data exceeds its byte bound")
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError("provider SSE data is not valid JSON") from error
        if type(payload) is not dict:
            raise ValueError("provider SSE data must decode to an object")
        canonical_json_bytes(payload, limit=MAX_SSE_EVENT_BYTES)
        if self.surface == "openai_chat":
            return self._feed_openai_chat(payload)
        if self.surface == "openai_responses":
            return self._feed_openai_responses(event_name, payload)
        if self.surface == "anthropic_messages":
            return self._feed_anthropic(event_name, payload)
        raise ValueError("unsupported stream surface")

    def _feed_openai_chat(self, payload: Mapping[str, object]) -> list[CanonicalModelEvent]:
        out: list[CanonicalModelEvent] = []
        if isinstance(payload.get("id"), str):
            self._provider_request_id = str(payload["id"])
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            inp = usage.get("prompt_tokens")
            outp = usage.get("completion_tokens")
            if type(inp) is int and inp >= 0 and type(outp) is int and outp >= 0:
                self._input_tokens, self._output_tokens = inp, outp
        choices = payload.get("choices")
        if choices in (None, []):
            return out
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ValueError("OpenAI chat stream requires exactly one choice")
        choice = choices[0]
        delta = choice.get("delta") or {}
        if type(delta) is not dict:
            raise ValueError("OpenAI chat delta must be an object")
        content = delta.get("content")
        if isinstance(content, str) and content.strip():
            out.append(self._event("text_delta", {"text": content}))
        elif isinstance(content, str) and content:
            # Whitespace-only content is not a substantive delta. A thinking-mode model emits
            # these between reasoning and answer; failing the stream on them would break a
            # perfectly healthy generation, so they are carried as a text delta only when they
            # are the literal payload the caller asked for. Here they are simply non-substantive.
            pass
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            out.append(self._event("reasoning_delta", {"text": reasoning}))
        tool_calls = delta.get("tool_calls")
        if tool_calls is not None:
            if type(tool_calls) is not list:
                raise ValueError("OpenAI chat tool_calls delta must be a list")
            for raw in tool_calls:
                if type(raw) is not dict or type(raw.get("index")) is not int or isinstance(raw.get("index"), bool):
                    raise ValueError("OpenAI chat tool-call delta requires integer index")
                index = int(raw["index"])
                if not 0 <= index < 1024:
                    raise ValueError("OpenAI chat tool-call index is out of range")
                fn = raw.get("function") or {}
                if type(fn) is not dict:
                    raise ValueError("OpenAI chat tool-call function delta must be an object")
                call_id = raw.get("id")
                name = fn.get("name")
                assembly = self._tools_by_index.get(index)
                if assembly is None:
                    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                        raise ValueError("first OpenAI tool-call delta requires id and name")
                    if call_id in self._tools_by_id:
                        raise ValueError("OpenAI tool-call id was reused across indexes")
                    assembly = _ToolAssembly(call_id, name)
                    self._tools_by_index[index] = assembly
                    self._tools_by_id[call_id] = assembly
                    out.append(self._event("tool_call_start", {"call_id": call_id, "name": name}))
                else:
                    if call_id not in (None, assembly.call_id) or name not in (None, assembly.name):
                        raise ValueError("OpenAI tool-call identity changed during streaming")
                fragment = fn.get("arguments")
                if isinstance(fragment, str) and fragment:
                    assembly.add(fragment)
                    out.append(self._event("tool_call_delta", {"call_id": assembly.call_id, "arguments_delta": fragment}))
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            self._pending_finish_reason = finish_reason
        return out

    def _feed_openai_responses(self, event_name: str | None, payload: Mapping[str, object]) -> list[CanonicalModelEvent]:
        kind = str(payload.get("type") or event_name or "")
        out: list[CanonicalModelEvent] = []
        response = payload.get("response")
        if isinstance(response, Mapping) and isinstance(response.get("id"), str):
            self._provider_request_id = str(response["id"])
        if kind == "response.output_text.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str) or not delta:
                raise ValueError("Responses text delta is invalid")
            return [self._event("text_delta", {"text": delta})]
        if kind in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}:
            delta = payload.get("delta")
            if not isinstance(delta, str) or not delta:
                raise ValueError("Responses reasoning delta is invalid")
            return [self._event("reasoning_delta", {"text": delta})]
        if kind == "response.output_item.added":
            item = payload.get("item")
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                item_id = item.get("id")
                call_id = item.get("call_id") or item_id
                name = item.get("name")
                output_index = payload.get("output_index", len(self._tools_by_index))
                if (
                    type(output_index) is not int
                    or isinstance(output_index, bool)
                    or not 0 <= output_index < 1024
                    or not isinstance(call_id, str)
                    or not call_id
                    or not isinstance(name, str)
                    or not name
                ):
                    raise ValueError("Responses function-call start is invalid")
                if output_index in self._tools_by_index or call_id in self._tools_by_id or (isinstance(item_id, str) and item_id in self._tools_by_id):
                    raise ValueError("Responses function-call identity was reused")
                assembly = _ToolAssembly(call_id, name)
                self._tools_by_index[output_index] = assembly
                self._tools_by_id[call_id] = assembly
                if isinstance(item_id, str):
                    self._tools_by_id[item_id] = assembly
                return [self._event("tool_call_start", {"call_id": call_id, "name": name})]
        if kind == "response.function_call_arguments.delta":
            call_id = payload.get("call_id") or payload.get("item_id")
            delta = payload.get("delta")
            assembly = self._tools_by_id.get(str(call_id))
            if assembly is None or not isinstance(delta, str) or not delta:
                raise ValueError("Responses function-call delta is invalid or out of order")
            assembly.add(delta)
            return [self._event("tool_call_delta", {"call_id": assembly.call_id, "arguments_delta": delta})]
        if kind == "response.function_call_arguments.done":
            call_id = payload.get("call_id") or payload.get("item_id")
            arguments = payload.get("arguments")
            assembly = self._tools_by_id.get(str(call_id))
            if assembly is None or not isinstance(arguments, str):
                raise ValueError("Responses function-call completion is invalid or out of order")
            if len(arguments.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                raise ValueError("streamed tool arguments exceed their byte bound")
            if assembly.arguments and assembly.arguments != arguments:
                raise ValueError("Responses function-call completion disagrees with streamed argument deltas")
            if not assembly.arguments:
                assembly.arguments = arguments
                assembly.complete_initial_arguments = True
            assembly.parsed()
            return []
        if kind == "response.output_item.done":
            item = payload.get("item")
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                item_id = item.get("id")
                call_id = item.get("call_id") or item_id
                arguments = item.get("arguments")
                assembly = self._tools_by_id.get(str(call_id)) or self._tools_by_id.get(str(item_id))
                if assembly is None or not isinstance(arguments, str):
                    raise ValueError("Responses function-call output completion is invalid or out of order")
                if len(arguments.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                    raise ValueError("streamed tool arguments exceed their byte bound")
                if assembly.arguments and assembly.arguments != arguments:
                    raise ValueError("Responses function-call output completion disagrees with streamed argument deltas")
                if not assembly.arguments:
                    assembly.arguments = arguments
                    assembly.complete_initial_arguments = True
                assembly.parsed()
            return []
        if kind == "response.completed":
            if not isinstance(response, Mapping):
                raise ValueError("Responses completed event omitted response")
            usage = response.get("usage")
            if isinstance(usage, Mapping):
                inp, outp = usage.get("input_tokens"), usage.get("output_tokens")
                if type(inp) is int and inp >= 0 and type(outp) is int and outp >= 0:
                    self._input_tokens, self._output_tokens = inp, outp
            status = response.get("status")
            return self._terminal(str(status or "completed"))
        if kind in {"response.failed", "error"}:
            self.finished = True
            return [self._event("error", {"code": "provider_error", "retryable": False})]
        return out

    def _feed_anthropic(self, event_name: str | None, payload: Mapping[str, object]) -> list[CanonicalModelEvent]:
        kind = str(payload.get("type") or event_name or "")
        out: list[CanonicalModelEvent] = []
        if kind == "message_start":
            message = payload.get("message")
            if isinstance(message, Mapping):
                if isinstance(message.get("id"), str):
                    self._provider_request_id = str(message["id"])
                usage = message.get("usage")
                if isinstance(usage, Mapping) and type(usage.get("input_tokens")) is int and usage["input_tokens"] >= 0:
                    self._input_tokens = int(usage["input_tokens"])
            return out
        if kind == "content_block_start":
            index, block = payload.get("index"), payload.get("content_block")
            if type(index) is not int or isinstance(index, bool) or type(block) is not dict:
                raise ValueError("Anthropic content_block_start is invalid")
            block_type = block.get("type")
            if block_type == "text" and isinstance(block.get("text"), str) and block["text"]:
                out.append(self._event("text_delta", {"text": block["text"]}))
            elif block_type in {"thinking", "reasoning"} and isinstance(block.get("thinking"), str) and block["thinking"]:
                out.append(self._event("reasoning_delta", {"text": block["thinking"]}))
            elif block_type == "tool_use":
                call_id, name = block.get("id"), block.get("name")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    raise ValueError("Anthropic tool_use start requires id and name")
                if not 0 <= index < 1024:
                    raise ValueError("Anthropic content block index is out of range")
                if index in self._tools_by_index or call_id in self._tools_by_id:
                    raise ValueError("Anthropic tool-call identity was reused")
                assembly = _ToolAssembly(call_id, name)
                self._tools_by_index[index] = assembly
                self._tools_by_id[call_id] = assembly
                self._anthropic_block_tool[index] = call_id
                initial = block.get("input")
                if initial is not None:
                    if not isinstance(initial, Mapping):
                        raise ValueError("Anthropic tool_use input must be an object")
                    if initial:
                        serialized = json.dumps(initial, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        if len(serialized.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                            raise ValueError("streamed tool arguments exceed their byte bound")
                        assembly.arguments = serialized
                        assembly.complete_initial_arguments = True
                out.append(self._event("tool_call_start", {"call_id": call_id, "name": name}))
            return out
        if kind == "content_block_delta":
            index, delta = payload.get("index"), payload.get("delta")
            if type(index) is not int or isinstance(index, bool) or type(delta) is not dict:
                raise ValueError("Anthropic content_block_delta is invalid")
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    out.append(self._event("text_delta", {"text": text}))
            elif delta_type in {"thinking_delta", "reasoning_delta"}:
                text = delta.get("thinking") or delta.get("text")
                if isinstance(text, str) and text:
                    out.append(self._event("reasoning_delta", {"text": text}))
            elif delta_type == "input_json_delta":
                partial = delta.get("partial_json")
                call_id = self._anthropic_block_tool.get(index)
                assembly = self._tools_by_id.get(call_id or "")
                if assembly is None or not isinstance(partial, str) or not partial:
                    raise ValueError("Anthropic tool JSON delta is invalid or out of order")
                assembly.add(partial)
                out.append(self._event("tool_call_delta", {"call_id": assembly.call_id, "arguments_delta": partial}))
            return out
        if kind == "content_block_stop":
            # Final tool_call_end is emitted at the terminal message to preserve
            # one deterministic closing order across provider chunking patterns.
            return out
        if kind == "message_delta":
            usage = payload.get("usage")
            if isinstance(usage, Mapping) and type(usage.get("output_tokens")) is int and usage["output_tokens"] >= 0:
                self._output_tokens = int(usage["output_tokens"])
            delta = payload.get("delta")
            if isinstance(delta, Mapping) and isinstance(delta.get("stop_reason"), str):
                # Do not terminalize until message_stop; usage can still update.
                pass
            return out
        if kind == "message_stop":
            return self._terminal("stop")
        if kind == "error":
            self.finished = True
            return [self._event("error", {"code": "provider_error", "retryable": False})]
        return out


def canonical_event_to_wire(surface: str, event: CanonicalModelEvent) -> tuple[str | None, dict[str, object] | str]:
    """Translate canonical events to a conservative client-facing wire event.

    This is a shape adapter only.  Client server endpoints remain separate PX owners.
    """
    surface = validate_protocol_surface(surface)
    if surface == "terminal":
        raise ValueError("terminal surface does not stream events")
    payload = dict(event.payload)
    if surface == "openai_chat":
        if event.kind == "text_delta":
            return None, {"choices": [{"index": 0, "delta": {"content": payload["text"]}, "finish_reason": None}]}
        if event.kind == "reasoning_delta":
            return None, {"choices": [{"index": 0, "delta": {"reasoning_content": payload["text"]}, "finish_reason": None}]}
        if event.kind == "usage":
            return None, {"choices": [], "usage": {"prompt_tokens": payload["input_tokens"], "completion_tokens": payload["output_tokens"]}}
        if event.kind == "finish":
            return None, {"choices": [{"index": 0, "delta": {}, "finish_reason": payload["reason"]}]}
        if event.kind == "error":
            return None, {"error": {"code": payload["code"]}}
    elif surface == "openai_responses":
        if event.kind == "text_delta":
            return "response.output_text.delta", {"type": "response.output_text.delta", "delta": payload["text"]}
        if event.kind == "reasoning_delta":
            return "response.reasoning_text.delta", {"type": "response.reasoning_text.delta", "delta": payload["text"]}
        if event.kind == "finish":
            return "response.completed", {"type": "response.completed", "response": {"status": payload["reason"]}}
        if event.kind == "error":
            return "error", {"type": "error", "error": {"code": payload["code"]}}
    elif surface == "anthropic_messages":
        if event.kind == "text_delta":
            return "content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": payload["text"]}}
        if event.kind == "reasoning_delta":
            return "content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": payload["text"]}}
        if event.kind == "usage":
            return "message_delta", {"type": "message_delta", "delta": {}, "usage": {"output_tokens": payload["output_tokens"]}}
        if event.kind == "finish":
            return "message_stop", {"type": "message_stop"}
        if event.kind == "error":
            return "error", {"type": "error", "error": {"type": payload["code"]}}
    # Tool-call reconstruction is intentionally not guessed here.  Client-facing
    # tool streaming needs call-index/block-index state and belongs to its façade.
    if event.kind.startswith("tool_call_"):
        raise ValueError("tool-call client wire translation requires a stateful certified façade")
    raise ValueError(f"canonical event kind {event.kind!r} has no safe {surface} wire mapping")
