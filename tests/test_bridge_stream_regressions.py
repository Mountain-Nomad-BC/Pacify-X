"""Regression tests for the two integration defects found by the Stage 3 bridge proof.

Both were real, both broke a healthy generation, and both were only visible by executing the
system rather than inspecting it. A repair without a regression test can silently return.

S3-1 — the gateway sent the model's SHA-256 where the llama.cpp router needs its preset key.
S3-2 — a whitespace-only reasoning delta terminated a healthy stream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from runtime.model_protocol_translate import WireStreamTranslator  # noqa: E402
from runtime.provider_gateway import LlamaCppStreamingHttpAdapter  # noqa: E402


def _translator() -> WireStreamTranslator:
    return WireStreamTranslator(
        surface="openai_chat", request_id="r", adapter_id="llama-cpp-stream", model_id="m"
    )


def _frame(payload: dict) -> str:
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# S3-2 — whitespace-only deltas must not terminate the stream
# ---------------------------------------------------------------------------


def test_whitespace_only_reasoning_delta_does_not_terminate_the_stream() -> None:
    translator = _translator()
    # This is the exact frame captured from the live router that killed the stream.
    frame = _frame({"choices": [{"finish_reason": None, "index": 0,
                                 "delta": {"reasoning_content": "\n\n"}}]})
    events = translator.feed_sse("", frame)
    assert events == []  # non-substantive, skipped rather than fatal


@pytest.mark.parametrize("blank", ["\n", "\n\n", " ", "   ", "\t", "\r\n  "])
def test_all_whitespace_variants_are_non_substantive(blank: str) -> None:
    translator = _translator()
    frame = _frame({"choices": [{"finish_reason": None, "index": 0,
                                 "delta": {"reasoning_content": blank}}]})
    assert translator.feed_sse("", frame) == []


def test_substantive_reasoning_delta_is_still_emitted() -> None:
    translator = _translator()
    frame = _frame({"choices": [{"finish_reason": None, "index": 0,
                                 "delta": {"reasoning_content": "Thinking"}}]})
    events = translator.feed_sse("", frame)
    assert len(events) == 1
    assert events[0].kind == "reasoning_delta"


def test_whitespace_only_content_delta_is_non_substantive() -> None:
    translator = _translator()
    frame = _frame({"choices": [{"finish_reason": None, "index": 0,
                                 "delta": {"content": "\n"}}]})
    assert translator.feed_sse("", frame) == []


def test_substantive_content_delta_is_still_emitted() -> None:
    translator = _translator()
    frame = _frame({"choices": [{"finish_reason": None, "index": 0,
                                 "delta": {"content": "PACIFY"}}]})
    events = translator.feed_sse("", frame)
    assert len(events) == 1
    assert events[0].kind == "text_delta"


def test_full_thinking_mode_sequence_completes() -> None:
    """A realistic Qwen3.5 sequence must run to termination without raising."""

    translator = _translator()
    sequence = [
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"role": "assistant", "content": None}}]},
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"reasoning_content": "\n\n"}}]},
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"reasoning_content": "Thinking"}}]},
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"reasoning_content": " Process"}}]},
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"content": "\n"}}]},
        {"choices": [{"finish_reason": None, "index": 0,
                      "delta": {"content": "PACIFY"}}]},
        {"choices": [{"finish_reason": "stop", "index": 0, "delta": {}}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
    ]
    emitted = []
    for payload in sequence:
        emitted.extend(translator.feed_sse("", _frame(payload)))
    terminal = translator.feed_sse("", "[DONE]")
    kinds = [event.kind for event in emitted + terminal]
    assert "reasoning_delta" in kinds
    assert "text_delta" in kinds
    assert "finish" in kinds or "usage" in kinds


def test_stream_still_rejects_out_of_contract_frames() -> None:
    """Skipping non-substantive deltas must not make the translator permissive."""

    translator = _translator()
    with pytest.raises(ValueError):
        translator.feed_sse("", "not json at all")
    with pytest.raises(ValueError):
        translator.feed_sse("", json.dumps({"choices": "not-a-list"}))
    with pytest.raises(ValueError):
        translator.feed_sse("", json.dumps({"choices": [{"delta": {}}, {"delta": {}}]}))


# ---------------------------------------------------------------------------
# S3-1 — wire model name is the preset key, identity remains the digest
# ---------------------------------------------------------------------------

DIGEST = "a" * 64


def test_wire_model_name_defaults_to_the_digest_when_not_supplied() -> None:
    adapter = LlamaCppStreamingHttpAdapter(
        "http://127.0.0.1:18090",
        adapter_id="llama-cpp-stream",
        session_id="local-model-session-test",
        model_sha256=DIGEST,
    )
    assert adapter.model_sha256 == DIGEST
    assert adapter.wire_model_name == DIGEST


def test_wire_model_name_can_be_the_preset_key_while_identity_stays_the_digest() -> None:
    adapter = LlamaCppStreamingHttpAdapter(
        "http://127.0.0.1:18090",
        adapter_id="llama-cpp-stream",
        session_id="local-model-session-test",
        model_sha256=DIGEST,
        wire_model_name="qwen35-4b-operator",
    )
    # Identity is the digest; the wire carries the router's preset key.
    assert adapter.model_sha256 == DIGEST
    assert adapter.wire_model_name == "qwen35-4b-operator"


@pytest.mark.parametrize("bad", ["", "has space", "x" * 300, 12345])
def test_invalid_wire_model_name_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        LlamaCppStreamingHttpAdapter(
            "http://127.0.0.1:18090",
            adapter_id="llama-cpp-stream",
            session_id="local-model-session-test",
            model_sha256=DIGEST,
            wire_model_name=bad,  # type: ignore[arg-type]
        )


def test_omitted_wire_model_name_means_use_the_digest() -> None:
    # `None` is the documented default meaning "no separate preset key", so it is not an error.
    # A *supplied* invalid value is rejected (see the test above).
    adapter = LlamaCppStreamingHttpAdapter(
        "http://127.0.0.1:18090",
        adapter_id="llama-cpp-stream",
        session_id="local-model-session-test",
        model_sha256=DIGEST,
        wire_model_name=None,
    )
    assert adapter.wire_model_name == DIGEST


def test_bridge_supplies_the_preset_key_as_the_wire_model_name() -> None:
    """The bridge must pass the preset key, or the router rejects the request."""

    source = (ROOT / "runtime/vscode_model_bridge.py").read_text(encoding="utf-8-sig")
    assert "wire_model_name=" in source, (
        "the bridge must supply the router's preset key as the wire model name; sending the "
        "content digest makes the router reject the request with HTTP 400"
    )


def test_adapter_still_asserts_identity_against_the_digest() -> None:
    """Changing the wire name must not weaken the identity assertion."""

    source = (ROOT / "runtime/provider_gateway.py").read_text(encoding="utf-8-sig")
    assert "model_id != self.model_sha256" in source, (
        "the adapter must still refuse a request whose model identity differs from the admitted "
        "digest"
    )