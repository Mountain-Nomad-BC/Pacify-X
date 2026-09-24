from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable, Mapping

import pytest

from runtime.model_protocol import (
    CanonicalModelEvent,
    CanonicalModelRequest,
    TOKEN_COUNT_SCHEMA_VERSION,
    TokenCount,
)
from runtime.operational_event_bus import OperationalEventBus
from runtime.provider_budget import ProviderBudgetLedger, ProviderUsage
from runtime.provider_gateway import (
    LlamaCppStreamingHttpAdapter,
    ProviderInvocationError,
    ProviderInvocationGateway,
    ProviderRequest,
    ProviderStreamControl,
    ProviderStreamControlError,
    classify_provider_retry,
    load_provider_protocols,
)


ROOT = Path(__file__).resolve().parents[1]


def _project(directory: str, *, admitted: bool = True, streaming: bool = True) -> Path:
    root = Path(directory) / "engine"
    (root / "contracts/operations").mkdir(parents=True)
    (root / "registry").mkdir()
    (root / "models").mkdir()
    for name in (
        "operation-event.schema.json",
        "route-observer-registry.schema.json",
        "provider-adapter-registry.schema.json",
        "provider-budget-policy.schema.json",
    ):
        shutil.copyfile(ROOT / "contracts/operations" / name, root / "contracts/operations" / name)
    shutil.copyfile(ROOT / "registry/operation_route_registry.json", root / "registry/operation_route_registry.json")
    registry = {
        "schema_version": "px.provider-adapter-registry/1.0",
        "policy": "fixture exact adapter",
        "adapters": [
            {
                "adapter_id": "fixture-stream",
                "provider_id": "fixture-local",
                "mode": "local",
                "implementation": "tests/test_provider_gateway_streaming.py",
                "admitted": admitted,
                "status": "ready" if admitted else "unconfigured",
                "billing_state": "local_non_billable",
            }
        ],
    }
    (root / "registry/provider_adapters.json").write_text(json.dumps(registry), encoding="utf-8")
    protocols = {
        "schema_version": "px.provider-protocols/1.0",
        "policy": "fixture protocol capabilities",
        "canonical_events": [
            "text_delta", "reasoning_delta", "tool_call_start", "tool_call_delta",
            "tool_call_end", "usage", "finish", "error",
        ],
        "adapters": [
            {
                "adapter_id": "fixture-stream",
                "surfaces": ["openai_chat"] if streaming else ["terminal"],
                "implemented": True,
                "streaming": streaming,
                "tools": True if streaming else False,
                "structured_output": True if streaming else False,
                "images": False,
                "embeddings": False,
                "rerank": False,
                "exact_token_count": True,
                "cancellation": True if streaming else False,
                "load_unload_status": False,
            }
        ],
        "rules": {
            "raw_backend_stream_passthrough": False,
            "tool_syntax_grants_authority": False,
            "retry_mutations_without_receipt": False,
            "successful_stream_requires_exact_usage": True,
            "output_receipt_hash_uses_normalized_content_not_backend_chunk_boundaries": True,
        },
    }
    (root / "models/provider-protocols.json").write_text(json.dumps(protocols), encoding="utf-8")
    budget = {
        "schema_version": "px.provider-budget-policy/1.0",
        "policy": "fixture budget",
        "budgets": [
            {
                "budget_id": "budget-1",
                "actor_id": "agent-1",
                "provider_id": "fixture-local",
                "currency": "USD",
                "enabled": True,
                "hard_limit_microunits": 1000,
                "warning_threshold_microunits": 800,
                "max_requests": 20,
                "max_input_tokens": 100,
                "max_output_tokens": 100,
                "max_charge_per_request_microunits": 100,
                "unknown_billing": "allow_conservative_burn",
                "unknown_charge_microunits": 100,
                "fallback_adapter_ids": [],
            }
        ],
    }
    (root / "registry/provider_budget_policy.json").write_text(json.dumps(budget), encoding="utf-8")
    return root


def _canonical(invocation_id: str = "inv-1", *, deadline_ms: int = 30_000) -> CanonicalModelRequest:
    return CanonicalModelRequest(
        request_id=invocation_id,
        session_id="session-1",
        client_id="px-internal-operator",
        operation_id="knowledge.lookup",
        privacy="local",
        route="fixture-stream",
        messages=({"role": "user", "content": "secret prompt that must not enter durable events"},),
        tools=(),
        max_output_tokens=20,
        deadline_ms=deadline_ms,
        metadata={},
    )


def _request(invocation_id: str = "inv-1", *, deadline_ms: int = 30_000) -> ProviderRequest:
    canonical = _canonical(invocation_id, deadline_ms=deadline_ms)
    return ProviderRequest(
        invocation_id=invocation_id,
        correlation_id=f"corr-{invocation_id}",
        project_id="project-1",
        adapter_id="fixture-stream",
        model_id="model-1",
        actor_id="agent-1",
        accountable_owner="owner-1",
        payload=canonical.as_dict(),
        session_id="session-1",
        budget_id="budget-1",
        max_input_tokens=50,
        max_output_tokens=50,
    )


class FakeStreamAdapter:
    adapter_id = "fixture-stream"
    protocol_surface = "openai_chat"

    def __init__(
        self,
        chunks: tuple[str, ...] = ("hello",),
        *,
        include_usage: bool = True,
        input_tokens: int = 6,
        output_tokens: int = 2,
    ) -> None:
        self.chunks = chunks
        self.include_usage = include_usage
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.stream_calls = 0
        self.count_calls = 0

    def stream(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> Iterable[CanonicalModelEvent]:
        self.stream_calls += 1
        seq = 0
        for chunk in self.chunks:
            control.check()
            yield CanonicalModelEvent(request.request_id, self.adapter_id, model_id, seq, "text_delta", {"text": chunk})
            seq += 1
        if self.include_usage:
            yield CanonicalModelEvent(request.request_id, self.adapter_id, model_id, seq, "usage", {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "provider_request_id": "local-req"})
            seq += 1
        yield CanonicalModelEvent(request.request_id, self.adapter_id, model_id, seq, "finish", {"reason": "stop"})

    def count_tokens(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> TokenCount:
        self.count_calls += 1
        control.check()
        return TokenCount(TOKEN_COUNT_SCHEMA_VERSION, request.request_id, self.adapter_id, model_id, 6, True)

    def provider_usage(self, usage: Mapping[str, object]) -> ProviderUsage:
        return ProviderUsage(
            "local_non_billable",
            int(usage["input_tokens"]),
            int(usage["output_tokens"]),
            0,
            str(usage.get("provider_request_id")) if usage.get("provider_request_id") else None,
        )


def _gateway(root: Path, state: Path) -> ProviderInvocationGateway:
    return ProviderInvocationGateway(
        root,
        OperationalEventBus(root, state / "bus", state),
        ProviderBudgetLedger(root, state / "budget", state),
    )


def test_streaming_gateway_emits_only_canonical_events_and_hashes_normalized_output() -> None:
    hashes: list[str] = []
    for index, chunks in enumerate((("hello",), ("he", "ll", "o"))):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(directory)
            state = Path(directory) / "state"
            state.mkdir()
            gateway = _gateway(root, state)
            seen: list[CanonicalModelEvent] = []
            receipt = gateway.stream(_request(f"inv-{index}"), FakeStreamAdapter(chunks), seen.append)
            assert [event.kind for event in seen][-2:] == ["usage", "finish"]
            assert receipt["raw_backend_stream_retained"] is False
            assert receipt["payload_retained"] is False
            assert receipt["input_tokens"] == 6
            assert receipt["output_tokens"] == 2
            hashes.append(str(receipt["output_sha256"]))
            replay = gateway.event_bus.replay()
            assert [row["event"]["operation"]["lifecycle"] for row in replay["events"]] == ["started", "completed"]
            assert "secret prompt" not in json.dumps(replay)
    assert hashes[0] == hashes[1]


def test_streaming_gateway_cancellation_is_terminal_conservative_and_receipted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)
        cancelled = False
        seen: list[CanonicalModelEvent] = []

        def consume(event: CanonicalModelEvent) -> None:
            nonlocal cancelled
            seen.append(event)
            if event.kind == "text_delta":
                cancelled = True

        with pytest.raises(ProviderInvocationError) as raised:
            gateway.stream(_request(), FakeStreamAdapter(("first", "second")), consume, cancel_requested=lambda: cancelled)
        assert raised.value.failure_type == "Cancelled"
        assert seen[-1].kind == "error"
        assert seen[-1].payload["code"] == "cancelled"
        replay = gateway.event_bus.replay()
        assert [row["event"]["operation"]["lifecycle"] for row in replay["events"]] == ["started", "cancelled"]


def test_stream_requires_exact_usage_and_fails_closed_on_consumer_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)
        with pytest.raises(ProviderInvocationError):
            gateway.stream(_request(), FakeStreamAdapter(include_usage=False), lambda _event: None)

    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)

        def broken(_event: CanonicalModelEvent) -> None:
            raise RuntimeError("secret callback detail")

        with pytest.raises(ProviderInvocationError) as raised:
            gateway.stream(_request(), FakeStreamAdapter(), broken)
        assert raised.value.failure_type == "ConsumerFailure"
        assert "secret callback detail" not in str(raised.value)
        assert "secret callback detail" not in json.dumps(gateway.event_bus.replay())


def test_exact_token_count_is_local_admitted_and_metadata_only() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)
        adapter = FakeStreamAdapter()
        count, receipt = gateway.count_tokens(_request(), adapter)
        assert count.input_tokens == 6 and count.exact is True
        assert receipt["input_tokens"] == 6
        assert receipt["payload_retained"] is False
        assert adapter.count_calls == 1
        replay = gateway.event_bus.replay()
        assert all(row["event"]["operation"]["name"].startswith("provider.count_tokens:") for row in replay["events"])


def test_unadmitted_or_nonstreaming_capability_never_executes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, admitted=False)
        state = Path(directory) / "state"
        state.mkdir()
        adapter = FakeStreamAdapter()
        with pytest.raises(PermissionError, match="not admitted and ready"):
            _gateway(root, state).stream(_request(), adapter, lambda _event: None)
        assert adapter.stream_calls == 0

    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, streaming=False)
        state = Path(directory) / "state"
        state.mkdir()
        adapter = FakeStreamAdapter()
        with pytest.raises(PermissionError, match="not implemented for streaming"):
            _gateway(root, state).stream(_request(), adapter, lambda _event: None)
        assert adapter.stream_calls == 0


def test_protocol_matrix_is_cross_bound_to_registry_and_retry_classification_is_conservative() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        assert load_provider_protocols(root)["schema_version"] == "px.provider-protocols/1.0"
        protocols = json.loads((root / "models/provider-protocols.json").read_text())
        protocols["adapters"][0]["adapter_id"] = "other"
        (root / "models/provider-protocols.json").write_text(json.dumps(protocols), encoding="utf-8")
        with pytest.raises(ValueError, match="identities differ"):
            load_provider_protocols(root)

    assert classify_provider_retry(
        request_accepted=False,
        operation_mutates=True,
        billable_effect_possible=True,
        receipt_proves_no_side_effect=False,
    ) == "safe_before_accept"
    assert classify_provider_retry(
        request_accepted=True,
        operation_mutates=False,
        billable_effect_possible=True,
        receipt_proves_no_side_effect=False,
    ) == "unsafe_unreceipted_effect"
    assert classify_provider_retry(
        request_accepted=True,
        operation_mutates=True,
        billable_effect_possible=True,
        receipt_proves_no_side_effect=True,
    ) == "safe_receipted_no_effect"


class _StreamHttpResponse:
    def __init__(self, *, lines: list[bytes] | None = None, body: bytes = b"") -> None:
        self.lines = list(lines or [])
        self.body = body

    def __enter__(self) -> "_StreamHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def readline(self, limit: int) -> bytes:
        if not self.lines:
            return b""
        value = self.lines.pop(0)
        return value[:limit]

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _QueueOpener:
    def __init__(self, responses: list[_StreamHttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float) -> _StreamHttpResponse:
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def test_llama_cpp_stream_adapter_translates_sse_and_exact_token_count() -> None:
    model = "a" * 64
    lines = [
        b'data: {"id":"req-x","choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n',
        b'\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b'\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n',
        b'\n',
        b'data: [DONE]\n',
        b'\n',
    ]
    opener = _QueueOpener([
        _StreamHttpResponse(lines=lines),
        _StreamHttpResponse(body=b'{"input_tokens":3}'),
    ])
    adapter = LlamaCppStreamingHttpAdapter(
        "http://127.0.0.1:8080",
        adapter_id="llama-cpp-stream",
        session_id="local-model-session-1",
        model_sha256=model,
        opener=opener,
    )
    request = CanonicalModelRequest(
        request_id="r",
        session_id="session-1",
        client_id="px",
        operation_id="op",
        privacy="local",
        route="llama-cpp-stream",
        messages=({"role": "user", "content": "hello"},),
        max_output_tokens=8,
        deadline_ms=10_000,
        metadata={},
    )
    control = ProviderStreamControl(10_000)
    events = list(adapter.stream(model, request, control))
    assert [event.kind for event in events] == ["text_delta", "usage", "finish"]
    assert events[1].payload == {"input_tokens": 3, "output_tokens": 1, "provider_request_id": "req-x"}
    count = adapter.count_tokens(model, request, ProviderStreamControl(10_000))
    assert count.input_tokens == 3 and count.exact is True
    stream_request = opener.requests[0][0]
    body = json.loads(stream_request.data)
    assert stream_request.full_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert body["model"] == model
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    count_request = opener.requests[1][0]
    assert count_request.full_url.endswith("/v1/chat/completions/input_tokens")


def test_terminal_success_is_withheld_until_budget_settlement_accepts_usage() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)
        seen: list[CanonicalModelEvent] = []
        # Request reserved at 50 output tokens; the provider reports 51.
        with pytest.raises(ProviderInvocationError) as raised:
            gateway.stream(
                _request(),
                FakeStreamAdapter(output_tokens=51),
                seen.append,
            )
        assert raised.value.failure_type == "BudgetOverrun"
        assert seen[-1].kind == "error"
        assert seen[-1].payload == {"code": "budget_overrun", "retryable": False}
        assert all(event.kind != "finish" for event in seen)
        replay = gateway.event_bus.replay()
        assert [row["event"]["operation"]["lifecycle"] for row in replay["events"]] == ["started", "failed"]


def test_stream_output_budget_and_control_clock_are_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory)
        state = Path(directory) / "state"
        state.mkdir()
        gateway = _gateway(root, state)
        request = _request()
        too_small = replace(request, max_output_tokens=1)
        with pytest.raises(PermissionError, match="exceeds the reserved provider budget"):
            gateway.stream(too_small, FakeStreamAdapter(), lambda _event: None)

    ticks = iter([0.0, float("nan")])
    control = ProviderStreamControl(1_000, monotonic=lambda: next(ticks))
    with pytest.raises(ProviderStreamControlError, match="deadline_exceeded"):
        control.remaining_seconds()
