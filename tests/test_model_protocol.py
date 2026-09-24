from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from runtime.model_attachment import (
    build_model_attachment,
    build_model_protocol_binding,
    validate_model_protocol_binding,
)
from runtime.model_protocol import (
    CanonicalModelEvent,
    CanonicalModelRequest,
    CanonicalStreamState,
    CanonicalTool,
    canonical_request_from_mapping,
    validate_event_order,
)


def _request(**changes: object) -> CanonicalModelRequest:
    base: dict[str, object] = {
        "request_id": "invocation-1",
        "session_id": "session-1",
        "client_id": "px-internal-operator",
        "operation_id": "knowledge.lookup",
        "privacy": "local",
        "route": "llama-cpp-stream",
        "messages": ({"role": "user", "content": "Find the relevant skill."},),
        "tools": (
            CanonicalTool(
                "knowledge_lookup",
                "Read admitted knowledge by query.",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            ),
        ),
        "max_output_tokens": 256,
        "deadline_ms": 30_000,
        "response_schema": None,
        "metadata": {"context_receipt_sha256": "a" * 64},
    }
    base.update(changes)
    return CanonicalModelRequest(**base)  # type: ignore[arg-type]


def test_request_round_trip_is_exact_and_rejects_bool_numeric_fields() -> None:
    request = _request()
    decoded = canonical_request_from_mapping(request.as_dict())
    assert decoded == request
    assert decoded.request_sha256 == request.request_sha256

    with pytest.raises(ValueError, match="max_output_tokens"):
        _request(max_output_tokens=True)
    with pytest.raises(ValueError, match="deadline_ms"):
        _request(deadline_ms=True)
    with pytest.raises(ValueError, match="tool names must be unique"):
        _request(tools=(request.tools[0], request.tools[0]))

    payload = request.as_dict()
    payload["extra"] = True
    with pytest.raises(ValueError, match="exact declared fields"):
        canonical_request_from_mapping(payload)


def _events(chunks: tuple[str, ...]) -> list[CanonicalModelEvent]:
    events: list[CanonicalModelEvent] = []
    seq = 0
    for chunk in chunks:
        events.append(CanonicalModelEvent("r", "a", "m", seq, "text_delta", {"text": chunk}))
        seq += 1
    events.extend(
        [
            CanonicalModelEvent("r", "a", "m", seq, "usage", {"input_tokens": 3, "output_tokens": 2}),
            CanonicalModelEvent("r", "a", "m", seq + 1, "finish", {"reason": "stop"}),
        ]
    )
    return events


def test_stream_hash_is_independent_of_backend_text_chunk_boundaries() -> None:
    one = CanonicalStreamState("r", "a", "m")
    for event in _events(("hello",)):
        one.accept(event)
    one.assert_complete()

    many = CanonicalStreamState("r", "a", "m")
    for event in _events(("he", "ll", "o")):
        many.accept(event)
    many.assert_complete()

    assert one.normalized_output() == many.normalized_output()
    assert one.output_sha256 == many.output_sha256


def test_stream_state_enforces_tool_lifecycle_usage_and_terminal_order() -> None:
    events = [
        CanonicalModelEvent("r", "a", "m", 0, "tool_call_start", {"call_id": "c1", "name": "lookup"}),
        CanonicalModelEvent("r", "a", "m", 1, "tool_call_delta", {"call_id": "c1", "arguments_delta": '{"q":"x"}'}),
        CanonicalModelEvent("r", "a", "m", 2, "tool_call_end", {"call_id": "c1", "name": "lookup", "arguments": {"q": "x"}}),
        CanonicalModelEvent("r", "a", "m", 3, "usage", {"input_tokens": 8, "output_tokens": 4}),
        CanonicalModelEvent("r", "a", "m", 4, "finish", {"reason": "tool_calls"}),
    ]
    validate_event_order(events)

    broken = CanonicalStreamState("r", "a", "m")
    with pytest.raises(ValueError, match="before tool-call start"):
        broken.accept(CanonicalModelEvent("r", "a", "m", 0, "tool_call_delta", {"call_id": "c1", "arguments_delta": "{}"}))

    missing_usage = CanonicalStreamState("r", "a", "m")
    missing_usage.accept(CanonicalModelEvent("r", "a", "m", 0, "finish", {"reason": "stop"}))
    with pytest.raises(ValueError, match="lacks exact usage"):
        missing_usage.assert_complete()

    after_terminal = CanonicalStreamState("r", "a", "m")
    after_terminal.accept(CanonicalModelEvent("r", "a", "m", 0, "error", {"code": "x", "retryable": False}))
    with pytest.raises(ValueError, match="after its terminal"):
        after_terminal.accept(CanonicalModelEvent("r", "a", "m", 1, "text_delta", {"text": "late"}))


def test_model_protocol_binding_is_versioned_exact_and_cannot_invent_tool_support() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        attachment = build_model_attachment(
            root,
            model_id="qwen-control",
            model_revision="qwen-control-v1",
            artifact_sha256="b" * 64,
            runtime="llama.cpp",
            context_tokens=32768,
            modalities=["text"],
            supports_tools=True,
            privacy="local",
            authority_class="contained",
            benchmark_revision="c" * 64,
            hardware_requirements={"cpu": "required"},
        )
        binding = build_model_protocol_binding(
            attachment,
            adapter_id="llama-cpp-stream",
            provider_protocols_sha256="d" * 64,
            surfaces=["openai_chat"],
            streaming=True,
            tools=True,
            structured_output=True,
            exact_token_count=True,
            cancellation=True,
        )
        assert validate_model_protocol_binding(binding, attachment=attachment)["valid"] is True
        changed = replace(binding, adapter_id="other")
        assert validate_model_protocol_binding(changed, attachment=attachment)["valid"] is False

        no_tools = build_model_attachment(
            root,
            model_id="qwen-control-no-tools",
            model_revision="qwen-control-v1",
            artifact_sha256="e" * 64,
            runtime="llama.cpp",
            context_tokens=32768,
            modalities=["text"],
            supports_tools=False,
            privacy="local",
            authority_class="contained",
            benchmark_revision="f" * 64,
            hardware_requirements={"cpu": "required"},
        )
        with pytest.raises(ValueError, match="cannot add tool support"):
            build_model_protocol_binding(
                no_tools,
                adapter_id="llama-cpp-stream",
                provider_protocols_sha256="d" * 64,
                surfaces=["openai_chat"],
                streaming=True,
                tools=True,
                structured_output=False,
                exact_token_count=True,
                cancellation=True,
            )


def test_request_mapping_does_not_coerce_identity_fields_and_tool_end_must_match_deltas() -> None:
    payload = _request().as_dict()
    payload["request_id"] = 7
    with pytest.raises(ValueError, match="request_id"):
        canonical_request_from_mapping(payload)

    state = CanonicalStreamState("r", "a", "m")
    state.accept(CanonicalModelEvent("r", "a", "m", 0, "tool_call_start", {"call_id": "c", "name": "lookup"}))
    state.accept(CanonicalModelEvent("r", "a", "m", 1, "tool_call_delta", {"call_id": "c", "arguments_delta": '{"q":"x"}'}))
    with pytest.raises(ValueError, match="differ"):
        state.accept(CanonicalModelEvent("r", "a", "m", 2, "tool_call_end", {"call_id": "c", "name": "lookup", "arguments": {"q": "y"}}))


def test_stream_state_bounds_total_tool_output_and_tool_count() -> None:
    state = CanonicalStreamState("r", "a", "m")
    # Reusing a completed tool id is forbidden even when the first call was valid.
    state.accept(CanonicalModelEvent("r", "a", "m", 0, "tool_call_start", {"call_id": "c", "name": "lookup"}))
    state.accept(CanonicalModelEvent("r", "a", "m", 1, "tool_call_end", {"call_id": "c", "name": "lookup", "arguments": {}}))
    with pytest.raises(ValueError, match="identity was reused"):
        state.accept(CanonicalModelEvent("r", "a", "m", 2, "tool_call_start", {"call_id": "c", "name": "lookup"}))
