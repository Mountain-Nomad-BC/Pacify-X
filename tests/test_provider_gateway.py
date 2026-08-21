from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

import pytest

from runtime.operational_event_bus import OperationalEventBus
from runtime.provider_budget import ProviderBudgetLedger, ProviderUsage
from runtime.provider_gateway import (
    OllamaHttpAdapter,
    ProviderInvocationError,
    ProviderInvocationGateway,
    ProviderRequest,
    ProviderResponse,
    build_provider_route_index,
    load_provider_registry,
    scan_direct_provider_routes,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeAdapter:
    def __init__(
        self,
        adapter_id: str,
        *,
        billing_state: str = "actual",
        failure: Exception | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.billing_state = billing_state
        self.failure = failure
        self.calls = 0

    def invoke(self, model_id: str, payload: dict[str, object]) -> object:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        charge = 0 if self.billing_state == "local_non_billable" else 10
        if self.billing_state == "unknown":
            charge = None
        return ProviderResponse(
            {"model": model_id, "answer": payload["prompt"]},
            ProviderUsage(self.billing_state, 2, 3, charge, "provider-request-secret"),
        )


class _FakeHttpResponse:
    def __init__(self, value: object) -> None:
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _FakeOpener:
    def __init__(self, value: object) -> None:
        self.value = value
        self.requests: list[object] = []

    def open(self, request: object, *, timeout: float) -> _FakeHttpResponse:
        self.requests.append((request, timeout))
        return _FakeHttpResponse(self.value)


def test_ollama_adapter_is_loopback_only_bounded_and_usage_explicit() -> None:
    with pytest.raises(ValueError, match="literal loopback"):
        OllamaHttpAdapter("http://localhost:11434")
    with pytest.raises(ValueError, match="literal loopback"):
        OllamaHttpAdapter("https://127.0.0.1:11434")
    opener = _FakeOpener({
        "response": "ready",
        "prompt_eval_count": 4,
        "eval_count": 2,
    })
    adapter = OllamaHttpAdapter(opener=opener)
    result = adapter.invoke("qwen2.5-coder:3b", {"prompt": "reply ready"})
    assert result.value == "ready"
    assert result.usage == ProviderUsage("local_non_billable", 4, 2, 0)
    request, timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert json.loads(request.data) == {
        "model": "qwen2.5-coder:3b",
        "prompt": "reply ready",
        "stream": False,
    }
    assert timeout == 120.0


def test_ollama_adapter_rejects_gateway_owned_and_malformed_results() -> None:
    adapter = OllamaHttpAdapter(opener=_FakeOpener({"response": "ok"}))
    with pytest.raises(ValueError, match="gateway-owned"):
        adapter.invoke("model", {"prompt": "x", "stream": True})
    with pytest.raises(ValueError, match="exactly one"):
        adapter.invoke("model", {"prompt": "x", "messages": []})
    malformed = OllamaHttpAdapter(opener=_FakeOpener({"error": "secret provider detail"}))
    with pytest.raises(ValueError, match="invalid terminal") as raised:
        malformed.invoke("model", {"prompt": "x"})
    assert "secret provider detail" not in str(raised.value)


def _project(directory: str, *, mode: str, billing_state: str) -> Path:
    root = Path(directory) / "engine"
    (root / "contracts/operations").mkdir(parents=True)
    (root / "registry").mkdir()
    for name in (
        "operation-event.schema.json",
        "route-observer-registry.schema.json",
        "provider-adapter-registry.schema.json",
        "provider-budget-policy.schema.json",
    ):
        shutil.copyfile(
            ROOT / "contracts/operations" / name, root / "contracts/operations" / name
        )
    routes = json.loads(
        (ROOT / "registry/operation_route_registry.json").read_text(encoding="utf-8")
    )
    (root / "registry/operation_route_registry.json").write_text(
        json.dumps(routes), encoding="utf-8"
    )
    registry = {
        "schema_version": "px.provider-adapter-registry/1.0",
        "policy": "test registry",
        "adapters": [
            {
                "adapter_id": "fixture-adapter",
                "provider_id": "fixture-provider",
                "mode": mode,
                "implementation": "tests/test_provider_gateway.py",
                "admitted": True,
                "status": "ready",
                "billing_state": billing_state,
            }
        ],
    }
    (root / "registry/provider_adapters.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    budget_policy = {
        "schema_version": "px.provider-budget-policy/1.0",
        "policy": "test policy",
        "budgets": [
            {
                "budget_id": "budget-1",
                "actor_id": "agent-1",
                "provider_id": "fixture-provider",
                "currency": "USD",
                "enabled": True,
                "hard_limit_microunits": 1000,
                "warning_threshold_microunits": 800,
                "max_requests": 10,
                "max_input_tokens": 100,
                "max_output_tokens": 100,
                "max_charge_per_request_microunits": 100,
                "unknown_billing": "allow_conservative_burn",
                "unknown_charge_microunits": 100,
                "fallback_adapter_ids": [],
            }
        ],
    }
    (root / "registry/provider_budget_policy.json").write_text(
        json.dumps(budget_policy), encoding="utf-8"
    )
    return root


def _gateway(root: Path, allowed: Path) -> ProviderInvocationGateway:
    return ProviderInvocationGateway(
        root,
        OperationalEventBus(root, allowed / "bus", allowed),
        ProviderBudgetLedger(root, allowed / "budget", allowed),
    )


def _request(*, secret: str = "never-retain-this") -> ProviderRequest:
    return ProviderRequest(
        invocation_id="invocation-1",
        correlation_id="correlation-1",
        project_id="project-1",
        adapter_id="fixture-adapter",
        model_id="fixture-model",
        actor_id="agent-1",
        accountable_owner="owner-1",
        payload={"prompt": "hello", "secret": secret},
        task_id="task-1",
        claim_id="claim-1",
        orchestration_id="orchestration-1",
        session_id="session-1",
        budget_id="budget-1",
        max_input_tokens=10,
        max_output_tokens=10,
    )


def test_remote_invocation_is_mediated_correlated_and_payload_free() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="remote", billing_state="actual")
        allowed = Path(directory) / "state"
        allowed.mkdir()
        gateway = _gateway(root, allowed)
        adapter = FakeAdapter("fixture-adapter")
        response, receipt = gateway.invoke(_request(), adapter)
        assert response == {"model": "fixture-model", "answer": "hello"}
        assert receipt["billing_state"] == "actual"
        assert receipt["payload_retained"] is False
        assert adapter.calls == 1
        replay = gateway.event_bus.replay()
        assert replay["valid"] is True
        assert [row["event"]["operation"]["lifecycle"] for row in replay["events"]] == [
            "started",
            "completed",
        ]
        assert all(
            row["event"]["source"]["coverage_tier"] == "A" for row in replay["events"]
        )
        assert all(
            row["event"]["work"]["claim_id"] == "claim-1" for row in replay["events"]
        )
        serialized = json.dumps(replay)
        assert "never-retain-this" not in serialized
        assert "hello" not in serialized


def test_local_invocation_is_non_billable_and_has_no_network_effect() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="local", billing_state="local_non_billable")
        allowed = Path(directory) / "state"
        allowed.mkdir()
        bus = OperationalEventBus(root, allowed / "bus", allowed)
        ledger = ProviderBudgetLedger(root, allowed / "budget", allowed)
        _, receipt = ProviderInvocationGateway(root, bus, ledger).invoke(
            _request(),
            FakeAdapter("fixture-adapter", billing_state="local_non_billable"),
        )
        assert receipt["billing_state"] == "local_non_billable"
        event = bus.replay()["events"][0]["event"]
        assert event["effects"]["observed"] == ["model"]


def test_unregistered_unready_or_mismatched_adapter_never_executes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="remote", billing_state="estimated")
        registry_path = root / "registry/provider_adapters.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["adapters"][0]["admitted"] = False
        registry["adapters"][0]["status"] = "unconfigured"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        allowed = Path(directory) / "state"
        allowed.mkdir()
        adapter = FakeAdapter("fixture-adapter")
        gateway = _gateway(root, allowed)
        with pytest.raises(PermissionError, match="not admitted and ready"):
            gateway.invoke(_request(), adapter)
        assert adapter.calls == 0
        adapter.adapter_id = "spoofed-adapter"
        with pytest.raises(PermissionError, match="differs"):
            gateway.invoke(_request(), adapter)
        assert adapter.calls == 0


def test_failure_emits_sanitized_terminal_event() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="remote", billing_state="unknown")
        allowed = Path(directory) / "state"
        allowed.mkdir()
        bus = OperationalEventBus(root, allowed / "bus", allowed)
        gateway = ProviderInvocationGateway(
            root, bus, ProviderBudgetLedger(root, allowed / "budget", allowed)
        )
        with pytest.raises(ProviderInvocationError) as raised:
            gateway.invoke(
                _request(secret="credential-value"),
                FakeAdapter(
                    "fixture-adapter",
                    billing_state="unknown",
                    failure=RuntimeError("credential-value"),
                ),
            )
        assert "credential-value" not in str(raised.value)
        replay = bus.replay()
        assert [row["event"]["operation"]["lifecycle"] for row in replay["events"]] == [
            "started",
            "failed",
        ]
        assert "credential-value" not in json.dumps(replay)


def test_registry_refuses_duplicate_and_inconsistent_local_billing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="local", billing_state="actual")
        with pytest.raises(ValueError, match="local adapter billing"):
            load_provider_registry(root)
        registry_path = root / "registry/provider_adapters.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["adapters"][0]["billing_state"] = "local_non_billable"
        registry["adapters"].append(dict(registry["adapters"][0]))
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            load_provider_registry(root)


def test_reachability_scan_detects_direct_provider_bypass() -> None:
    live = scan_direct_provider_routes(ROOT)
    assert live["valid"] is True
    assert live["index_used"] is True
    assert live["index_current"] is True
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        (root / "scripts").mkdir()
        (root / "runtime/bypass.py").write_text(
            "import openai\nclient.responses.create(model='x')\n", encoding="utf-8"
        )
        report = scan_direct_provider_routes(root)
        assert report["valid"] is False
        assert {row["kind"] for row in report["violations"]} == {
            "provider_import",
            "provider_call",
        }


def test_provider_route_index_is_content_authoritative_not_mtime_authoritative() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        (root / "scripts").mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        source = root / "runtime/example.py"
        source.write_text("VALUE = 1\n", encoding="utf-8")
        index = build_provider_route_index(root)
        index_path = root / "registry/provider_route_scan.json"
        index_path.parent.mkdir()
        index_path.write_text(json.dumps(index), encoding="utf-8")

        original = source.stat()
        # Windows filesystems may coalesce an immediate touch into the original
        # timestamp.  Set a deliberate nanosecond value so this test measures
        # content authority rather than filesystem clock granularity.
        os.utime(
            source,
            ns=(original.st_atime_ns, original.st_mtime_ns + 2_000_000_000),
        )
        assert source.stat().st_mtime_ns != original.st_mtime_ns
        report = scan_direct_provider_routes(root)
        assert report["valid"] is True
        assert report["index_current"] is True

        source.write_text("import openai\n", encoding="utf-8")
        report = scan_direct_provider_routes(root)
        assert report["valid"] is False
        assert report["violations"][0]["kind"] == "index_stale"


def test_request_size_bound_fails_before_adapter_or_event() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = _project(directory, mode="remote", billing_state="estimated")
        allowed = Path(directory) / "state"
        allowed.mkdir()
        adapter = FakeAdapter("fixture-adapter")
        gateway = _gateway(root, allowed)
        request = _request(secret="x" * 1_048_576)
        with pytest.raises(ValueError, match="byte bound"):
            gateway.invoke(request, adapter)
        assert adapter.calls == 0
        assert gateway.event_bus.replay()["revision"] == 0
