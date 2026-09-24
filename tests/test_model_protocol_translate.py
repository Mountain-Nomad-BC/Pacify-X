from __future__ import annotations

import json

import pytest

from runtime.model_protocol import CanonicalModelEvent, CanonicalModelRequest, CanonicalTool, CanonicalStreamState
from runtime.model_protocol_translate import (
    WireStreamTranslator,
    canonical_event_to_wire,
    canonical_request_to_wire,
    iter_sse_frames,
)


def _request(*, response_schema: dict[str, object] | None = None) -> CanonicalModelRequest:
    return CanonicalModelRequest(
        request_id="r1",
        session_id="s1",
        client_id="px",
        operation_id="op",
        privacy="local",
        route="llama-cpp-stream",
        messages=(
            {"role": "system", "content": "Follow the contract."},
            {"role": "user", "content": "Look up x."},
        ),
        tools=(CanonicalTool("lookup", "lookup", {"type": "object", "properties": {"q": {"type": "string"}}}),),
        max_output_tokens=64,
        deadline_ms=5_000,
        response_schema=response_schema,
        metadata={},
    )


def test_canonical_request_translates_to_exact_supported_wire_shapes() -> None:
    request = _request(response_schema={"type": "object", "properties": {"answer": {"type": "string"}}})
    chat = canonical_request_to_wire(request, surface="openai_chat", model_id="m", stream=True)
    assert chat["stream_options"] == {"include_usage": True}
    assert chat["tools"][0]["function"]["name"] == "lookup"  # type: ignore[index]
    assert chat["response_format"]["type"] == "json_schema"  # type: ignore[index]

    responses = canonical_request_to_wire(request, surface="openai_responses", model_id="m", stream=True)
    assert responses["tools"][0]["type"] == "function"  # type: ignore[index]
    assert responses["text"]["format"]["strict"] is True  # type: ignore[index]

    with pytest.raises(ValueError, match="does not accept PX response_schema"):
        canonical_request_to_wire(request, surface="anthropic_messages", model_id="m", stream=True)

    anthropic = canonical_request_to_wire(_request(), surface="anthropic_messages", model_id="m", stream=True)
    assert anthropic["system"] == "Follow the contract."
    assert anthropic["messages"] == [{"role": "user", "content": "Look up x."}]
    assert anthropic["tools"][0]["input_schema"]["type"] == "object"  # type: ignore[index]


def test_sse_parser_is_chunk_boundary_independent_and_bounded() -> None:
    chunks = [
        b"event: response.output_text.delta\r\ndata: {\"delta\":\"he",
        b"llo\",\"type\":\"response.output_text.delta\"}\r\n\r\n",
        b": keepalive\n\ndata: [DONE]\n\n",
    ]
    assert list(iter_sse_frames(chunks)) == [
        ("response.output_text.delta", '{"delta":"hello","type":"response.output_text.delta"}'),
        (None, "[DONE]"),
    ]
    with pytest.raises(ValueError, match="incomplete frame"):
        list(iter_sse_frames(["event: x"]))


def test_openai_chat_stream_normalizes_tool_fragments_usage_and_terminal_order() -> None:
    tr = WireStreamTranslator(surface="openai_chat", request_id="r", adapter_id="a", model_id="m")
    events: list[CanonicalModelEvent] = []
    events += tr.feed_sse(None, json.dumps({"id": "req-1", "choices": [{"delta": {"content": "Hi "}, "finish_reason": None}]}))
    events += tr.feed_sse(None, json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "lookup", "arguments": '{"q":'}}]}, "finish_reason": None}]}))
    events += tr.feed_sse(None, json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}, "finish_reason": "tool_calls"}]}))
    # OpenAI-style include_usage may arrive after the finish_reason chunk.
    events += tr.feed_sse(None, json.dumps({"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}))
    events += tr.feed_sse(None, "[DONE]")
    assert [event.kind for event in events] == [
        "text_delta", "tool_call_start", "tool_call_delta", "tool_call_delta", "tool_call_end", "usage", "finish"
    ]
    assert events[-3].payload["arguments"] == {"q": "x"}
    assert events[-2].payload["provider_request_id"] == "req-1"
    state = CanonicalStreamState("r", "a", "m")
    for event in events:
        state.accept(event)
    state.assert_complete()


def test_responses_stream_tracks_item_id_alias_and_normalizes_completion() -> None:
    tr = WireStreamTranslator(surface="openai_responses", request_id="r", adapter_id="a", model_id="m")
    events: list[CanonicalModelEvent] = []
    events += tr.feed_sse("response.output_item.added", json.dumps({
        "type": "response.output_item.added", "output_index": 0,
        "item": {"type": "function_call", "id": "item-1", "call_id": "call-1", "name": "lookup"}
    }))
    events += tr.feed_sse("response.function_call_arguments.delta", json.dumps({
        "type": "response.function_call_arguments.delta", "item_id": "item-1", "delta": '{"q":"x"}'
    }))
    events += tr.feed_sse("response.output_text.delta", json.dumps({"type": "response.output_text.delta", "delta": "done"}))
    events += tr.feed_sse("response.completed", json.dumps({
        "type": "response.completed",
        "response": {"id": "resp-1", "status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
    }))
    assert [event.kind for event in events] == [
        "tool_call_start", "tool_call_delta", "text_delta", "tool_call_end", "usage", "finish"
    ]
    assert events[-3].payload["arguments"] == {"q": "x"}
    assert events[-2].payload["provider_request_id"] == "resp-1"


def test_anthropic_stream_normalizes_text_tool_json_and_usage() -> None:
    tr = WireStreamTranslator(surface="anthropic_messages", request_id="r", adapter_id="a", model_id="m")
    frames = [
        ("message_start", {"type": "message_start", "message": {"id": "msg-1", "usage": {"input_tokens": 7}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "Hi"}}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 3}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    events: list[CanonicalModelEvent] = []
    for name, payload in frames:
        events += tr.feed_sse(name, json.dumps(payload))
    assert [event.kind for event in events] == [
        "text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage", "finish"
    ]
    assert events[-3].payload["arguments"] == {"q": "x"}
    assert events[-2].payload == {"input_tokens": 7, "output_tokens": 3, "provider_request_id": "msg-1"}


def test_invalid_tool_json_fails_before_any_tool_can_be_executed() -> None:
    tr = WireStreamTranslator(surface="openai_chat", request_id="r", adapter_id="a", model_id="m")
    tr.feed_sse(None, json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "lookup", "arguments": "{"}}]}, "finish_reason": "tool_calls"}]}))
    tr.feed_sse(None, json.dumps({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    with pytest.raises(ValueError, match="not valid JSON"):
        tr.feed_sse(None, "[DONE]")


def test_safe_reverse_translation_refuses_stateless_tool_guessing() -> None:
    text = CanonicalModelEvent("r", "a", "m", 0, "text_delta", {"text": "x"})
    event_name, wire = canonical_event_to_wire("openai_responses", text)
    assert event_name == "response.output_text.delta"
    assert wire["delta"] == "x"  # type: ignore[index]

    tool = CanonicalModelEvent("r", "a", "m", 1, "tool_call_start", {"call_id": "c", "name": "lookup"})
    with pytest.raises(ValueError, match="stateful certified façade"):
        canonical_event_to_wire("openai_chat", tool)


def test_responses_done_event_can_supply_full_arguments_but_cannot_disagree_with_deltas() -> None:
    tr = WireStreamTranslator(surface="openai_responses", request_id="r", adapter_id="a", model_id="m")
    tr.feed_sse("response.output_item.added", json.dumps({
        "type": "response.output_item.added", "output_index": 0,
        "item": {"type": "function_call", "id": "item-1", "call_id": "call-1", "name": "lookup"}
    }))
    tr.feed_sse("response.function_call_arguments.done", json.dumps({
        "type": "response.function_call_arguments.done", "item_id": "item-1", "arguments": '{"q":"x"}'
    }))
    events = tr.feed_sse("response.completed", json.dumps({
        "type": "response.completed",
        "response": {"id": "resp-1", "status": "completed", "usage": {"input_tokens": 2, "output_tokens": 1}}
    }))
    assert events[0].kind == "tool_call_end"
    assert events[0].payload["arguments"] == {"q": "x"}

    bad = WireStreamTranslator(surface="openai_responses", request_id="r2", adapter_id="a", model_id="m")
    bad.feed_sse("response.output_item.added", json.dumps({
        "type": "response.output_item.added", "output_index": 0,
        "item": {"type": "function_call", "id": "item-2", "call_id": "call-2", "name": "lookup"}
    }))
    bad.feed_sse("response.function_call_arguments.delta", json.dumps({
        "type": "response.function_call_arguments.delta", "item_id": "item-2", "delta": '{"q":"x"}'
    }))
    with pytest.raises(ValueError, match="disagrees"):
        bad.feed_sse("response.function_call_arguments.done", json.dumps({
            "type": "response.function_call_arguments.done", "item_id": "item-2", "arguments": '{"q":"y"}'
        }))


def test_anthropic_complete_initial_tool_input_cannot_be_followed_by_json_deltas() -> None:
    tr = WireStreamTranslator(surface="anthropic_messages", request_id="r", adapter_id="a", model_id="m")
    tr.feed_sse("content_block_start", json.dumps({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {"q": "x"}}
    }))
    with pytest.raises(ValueError, match="already complete"):
        tr.feed_sse("content_block_delta", json.dumps({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"y"}'}
        }))


def test_translators_reject_duplicate_tool_identity_and_index_state() -> None:
    chat = WireStreamTranslator(surface="openai_chat", request_id="r", adapter_id="a", model_id="m")
    chat.feed_sse(None, json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "x", "arguments": "{"}}]}, "finish_reason": None}]}))
    with pytest.raises(ValueError, match="reused across indexes"):
        chat.feed_sse(None, json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c", "function": {"name": "x", "arguments": "}"}}]}, "finish_reason": None}]}))

    responses = WireStreamTranslator(surface="openai_responses", request_id="r", adapter_id="a", model_id="m")
    start = {"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "id": "i", "call_id": "c", "name": "x"}}
    responses.feed_sse("response.output_item.added", json.dumps(start))
    with pytest.raises(ValueError, match="identity was reused"):
        responses.feed_sse("response.output_item.added", json.dumps(start))

    anthropic = WireStreamTranslator(surface="anthropic_messages", request_id="r", adapter_id="a", model_id="m")
    block = {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "c", "name": "x", "input": {}}}
    anthropic.feed_sse("content_block_start", json.dumps(block))
    with pytest.raises(ValueError, match="identity was reused"):
        anthropic.feed_sse("content_block_start", json.dumps(block))
