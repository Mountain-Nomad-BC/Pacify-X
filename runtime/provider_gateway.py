"""Single fail-closed invocation boundary for admitted model providers."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Callable, Iterable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .contracts import ContractValidationError, validate_instance
from .instrumentation_sdk import SDK_VERSION, build_operation_event
from .operational_event_bus import OperationalEventBus
from .provider_budget import ProviderBudgetLedger, ProviderUsage
from .model_protocol import (
    CanonicalModelEvent,
    CanonicalModelRequest,
    CanonicalStreamState,
    TOKEN_COUNT_SCHEMA_VERSION,
    TokenCount,
    canonical_json_bytes,
    canonical_request_from_mapping,
    canonical_sha256,
    validate_protocol_surface,
)
from .model_protocol_translate import (
    WireStreamTranslator,
    canonical_request_to_wire,
    iter_sse_frames,
)


REGISTRY_PATH = Path("registry/provider_adapters.json")
REGISTRY_SCHEMA = Path("contracts/operations/provider-adapter-registry.schema.json")
PROTOCOLS_PATH = Path("models/provider-protocols.json")
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 4_194_304
_DIRECT_PROVIDER_IMPORTS = {
    "anthropic",
    "google.generativeai",
    "google.genai",
    "ollama",
    "openai",
}
_DIRECT_CALL_SUFFIXES = {
    "chat.completions.create",
    "responses.create",
    "generate_content",
    "generateContent",
}


class ProviderInvocationError(RuntimeError):
    """Typed failure that does not retain provider exception text."""

    def __init__(self, adapter_id: str, failure_type: str) -> None:
        super().__init__(f"provider invocation failed: {adapter_id} ({failure_type})")
        self.adapter_id = adapter_id
        self.failure_type = failure_type


class ProviderAdapter(Protocol):
    """The only executable adapter shape accepted by the gateway."""

    adapter_id: str

    def invoke(
        self, model_id: str, payload: Mapping[str, object]
    ) -> ProviderResponse: ...


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Provider output paired with mandatory metadata-only usage."""

    value: object
    usage: ProviderUsage


class ProviderStreamControlError(RuntimeError):
    """Cooperative stream cancellation/deadline signal without provider detail."""

    def __init__(self, reason: str) -> None:
        if reason not in {"cancelled", "deadline_exceeded"}:
            raise ValueError("invalid stream-control reason")
        super().__init__(reason)
        self.reason = reason


class ProviderStreamControl:
    """Bounded cancellation/deadline view passed into an admitted stream adapter."""

    def __init__(
        self,
        deadline_ms: int,
        *,
        cancel_requested: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 600_000:
            raise ValueError("provider stream deadline_ms must be a bounded positive integer")
        self._cancel_requested = cancel_requested or (lambda: False)
        self._monotonic = monotonic
        now = monotonic()
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(float(now)):
            raise ValueError("provider stream monotonic clock must be finite")
        self._deadline_at = float(now) + (deadline_ms / 1000.0)

    def _checked_now(self) -> float:
        if self._cancel_requested():
            raise ProviderStreamControlError("cancelled")
        now = self._monotonic()
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(float(now)):
            raise ProviderStreamControlError("deadline_exceeded")
        current = float(now)
        if current >= self._deadline_at:
            raise ProviderStreamControlError("deadline_exceeded")
        return current

    def check(self) -> None:
        self._checked_now()

    def remaining_seconds(self, *, cap: float | None = None) -> float:
        remaining = max(0.001, self._deadline_at - self._checked_now())
        if cap is not None:
            if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not math.isfinite(float(cap)) or cap <= 0:
                raise ValueError("provider stream timeout cap must be finite and positive")
            remaining = min(remaining, float(cap))
        return remaining


class StreamingProviderAdapter(Protocol):
    """Exact streaming provider shape admitted by ProviderInvocationGateway."""

    adapter_id: str
    protocol_surface: str

    def stream(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> Iterable[CanonicalModelEvent]: ...

    def count_tokens(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> TokenCount: ...

    def provider_usage(self, usage: Mapping[str, object]) -> ProviderUsage: ...


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    invocation_id: str
    correlation_id: str
    project_id: str
    adapter_id: str
    model_id: str
    actor_id: str
    accountable_owner: str
    payload: Mapping[str, object]
    task_id: str | None = None
    claim_id: str | None = None
    orchestration_id: str | None = None
    session_id: str | None = None
    harness: str | None = None
    budget_id: str | None = None
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    task_plan_sha256: str | None = None
    model_revision: str | None = None
    model_attachment_sha256: str | None = None
    authority_revision: str | None = None
    requested_egress: str = "deny"
    expected_charge_microunits: int = 0


PROVIDER_POLICY_VIOLATION_IDS = (
    "PX-PROVIDER-SCHEMA",
    "PX-PROVIDER-POLICY-HASH",
    "PX-PROVIDER-PLAN-BINDING",
    "PX-PROVIDER-MODEL-BINDING",
    "PX-PROVIDER-AUTHORITY",
    "PX-PROVIDER-EGRESS",
    "PX-PROVIDER-COST",
    "PX-PROVIDER-FALLBACK",
    "PX-PROVIDER-RECEIPT",
)


def _sha(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def build_provider_execution_policy(**values: object) -> dict[str, object]:
    base = {
        "schema_version": "px.provider-execution-policy/1.0",
        **values,
    }
    base.pop("policy_sha256", None)
    return {**base, "policy_sha256": _digest(base, limit=MAX_REQUEST_BYTES)}


def provider_execution_policy_report(
    policy: Mapping[str, object], request: Mapping[str, object]
) -> dict[str, object]:
    """Language-neutral fail-closed policy semantics and stable violation IDs."""
    violations: list[str] = []
    if policy.get("schema_version") != "px.provider-execution-policy/1.0":
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[0])
    unsigned = {key: value for key, value in policy.items() if key != "policy_sha256"}
    if policy.get("policy_sha256") != _digest(unsigned, limit=MAX_REQUEST_BYTES):
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[1])
    if (
        not _sha(policy.get("task_plan_sha256"))
        or policy.get("task_plan_sha256") != request.get("task_plan_sha256")
    ):
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[2])
    model = policy.get("model")
    if not isinstance(model, Mapping) or any(
        (
            not str(model.get(field, "")).strip()
            if field in {"provider_id", "adapter_id", "model_id", "model_revision"}
            else not _sha(model.get(field))
        )
        for field in (
            "provider_id",
            "adapter_id",
            "model_id",
            "model_revision",
            "attachment_sha256",
        )
    ) or any(
        model.get(field) != request.get(request_field)
        for field, request_field in (
            ("adapter_id", "adapter_id"),
            ("model_id", "model_id"),
            ("model_revision", "model_revision"),
            ("attachment_sha256", "model_attachment_sha256"),
        )
    ):
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[3])
    authority = policy.get("authority")
    if (
        not isinstance(authority, Mapping)
        or not _sha(authority.get("revision"))
        or authority.get("revision") != request.get("authority_revision")
        or authority.get("provider_effect") is not True
    ):
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[4])
    egress = policy.get("egress")
    egress_valid = False
    if isinstance(egress, Mapping):
        mode = egress.get("mode")
        requested = request.get("requested_egress")
        destinations = egress.get("allowed_destinations", ())
        egress_valid = bool(
            (mode == "deny" and requested == "deny")
            or (mode == "loopback_only" and requested == "loopback")
            or (
                mode == "allowlist"
                and isinstance(destinations, Sequence)
                and not isinstance(destinations, (str, bytes))
                and requested in destinations
            )
        )
    if not egress_valid:
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[5])
    cost = policy.get("cost")
    if (
        not isinstance(cost, Mapping)
        or cost.get("budget_id") != request.get("budget_id")
        or not isinstance(cost.get("max_charge_microunits"), int)
        or int(cost.get("max_charge_microunits", -1)) < 0
        or int(request.get("expected_charge_microunits", -1))
        > int(cost.get("max_charge_microunits", -1))
    ):
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[6])
    privacy = {"policy_gated": 0, "isolated": 1, "local": 2}
    authority_levels = {"contained": 0, "installed_host": 1, "external_authority": 2}
    fallback_valid = isinstance(model, Mapping)
    for fallback in policy.get("fallbacks", ()):
        if not isinstance(fallback, Mapping) or any(
            not str(fallback.get(field, "")).strip()
            for field in ("provider_id", "adapter_id", "model_id", "model_revision")
        ) or not _sha(fallback.get("artifact_sha256")):
            fallback_valid = False
            continue
        if (
            privacy.get(str(fallback.get("privacy")), -1)
            < privacy.get(str(model.get("privacy")), -1)
            or authority_levels.get(str(fallback.get("authority_class")), -1)
            < authority_levels.get(str(model.get("authority_class")), -1)
        ):
            fallback_valid = False
    if not fallback_valid:
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[7])
    if policy.get("exact_receipt_required") is not True:
        violations.append(PROVIDER_POLICY_VIOLATION_IDS[8])
    ordered = [item for item in PROVIDER_POLICY_VIOLATION_IDS if item in violations]
    return {
        "schema_version": "px.provider-execution-policy-conformance/1.0",
        "valid": not ordered,
        "violation_ids": ordered,
    }


def load_provider_protocols(root: Path) -> dict[str, object]:
    """Load and cross-check exact adapter protocol capabilities."""
    path = root / PROTOCOLS_PATH
    if not path.is_file():
        raise ValueError("provider protocol matrix is missing")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("provider protocol matrix is unreadable") from error
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("provider protocol matrix exceeds its byte bound")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("provider protocol matrix is invalid JSON") from error
    if type(payload) is not dict or set(payload) != {
        "schema_version", "policy", "canonical_events", "adapters", "rules"
    }:
        raise ValueError("provider protocol matrix requires the exact declared fields")
    if payload.get("schema_version") != "px.provider-protocols/1.0":
        raise ValueError("provider protocol matrix schema_version is unsupported")
    if type(payload.get("policy")) is not str or not str(payload["policy"]).strip():
        raise ValueError("provider protocol matrix policy is invalid")
    expected_events = [
        "text_delta", "reasoning_delta", "tool_call_start", "tool_call_delta",
        "tool_call_end", "usage", "finish", "error",
    ]
    if payload.get("canonical_events") != expected_events:
        raise ValueError("provider protocol canonical event list differs from runtime authority")
    rows = payload.get("adapters")
    if type(rows) is not list or not rows:
        raise ValueError("provider protocol matrix requires adapter records")
    exact_fields = {
        "adapter_id", "surfaces", "implemented", "streaming", "tools",
        "structured_output", "images", "embeddings", "rerank",
        "exact_token_count", "cancellation", "load_unload_status",
    }
    seen: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != exact_fields:
            raise ValueError("provider protocol adapter requires the exact declared fields")
        adapter_id = row.get("adapter_id")
        if type(adapter_id) is not str or not adapter_id.strip() or len(adapter_id) > 128:
            raise ValueError("provider protocol adapter_id is invalid")
        if adapter_id in seen:
            raise ValueError("provider protocol adapter_id is duplicated")
        seen.add(adapter_id)
        surfaces = row.get("surfaces")
        if type(surfaces) is not list or not surfaces or surfaces != sorted(set(surfaces)):
            raise ValueError("provider protocol surfaces must be unique and canonically ordered")
        for surface in surfaces:
            validate_protocol_surface(surface)
        for field in exact_fields - {"adapter_id", "surfaces"}:
            if type(row.get(field)) is not bool:
                raise ValueError(f"provider protocol capability {field} must be boolean")
        if row["cancellation"] and not row["streaming"]:
            raise ValueError("provider protocol cancellation requires streaming")
        if row["streaming"] and "terminal" in surfaces:
            raise ValueError("streaming adapters cannot use the terminal protocol surface")
        if not row["streaming"] and any(surface != "terminal" for surface in surfaces):
            raise ValueError("non-streaming adapters must use the terminal protocol surface")
    rules = payload.get("rules")
    if type(rules) is not dict or not rules or any(type(value) is not bool for value in rules.values()):
        raise ValueError("provider protocol rules must be a nonempty boolean object")
    registry = load_provider_registry(root)
    registry_ids = {str(row["adapter_id"]) for row in registry["adapters"]}
    if registry_ids != seen:
        missing = sorted(registry_ids - seen)
        extra = sorted(seen - registry_ids)
        raise ValueError(f"provider protocol/adapter registry identities differ: missing={missing}; extra={extra}")
    canonical_json_bytes(payload, limit=MAX_REQUEST_BYTES)
    return payload


def provider_protocols_sha256(root: Path) -> str:
    return canonical_sha256(load_provider_protocols(root), limit=MAX_REQUEST_BYTES)


def classify_provider_retry(
    *,
    request_accepted: bool,
    operation_mutates: bool,
    billable_effect_possible: bool,
    receipt_proves_no_side_effect: bool,
) -> str:
    """Classify retry safety; this function never performs the retry itself."""
    for name, value in (
        ("request_accepted", request_accepted),
        ("operation_mutates", operation_mutates),
        ("billable_effect_possible", billable_effect_possible),
        ("receipt_proves_no_side_effect", receipt_proves_no_side_effect),
    ):
        if type(value) is not bool:
            raise ValueError(f"{name} must be boolean")
    if not request_accepted:
        return "safe_before_accept"
    if receipt_proves_no_side_effect:
        return "safe_receipted_no_effect"
    if not operation_mutates and not billable_effect_possible:
        return "safe_idempotent"
    return "unsafe_unreceipted_effect"


class OllamaHttpAdapter:
    """Bounded loopback-only Ollama adapter for the governed gateway."""

    adapter_id = "ollama-http"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout_seconds: float = 120.0,
        opener: object | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Ollama adapter requires a literal loopback HTTP origin")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("Ollama timeout must be between 1 and 300 seconds")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        # Ignore ambient proxy configuration so a local model request cannot be
        # redirected through a network proxy.
        self._opener = opener or build_opener(ProxyHandler({}))

    def invoke(
        self, model_id: str, payload: Mapping[str, object]
    ) -> ProviderResponse:
        model = model_id.strip()
        if not model or len(model) > 160 or any(character.isspace() for character in model):
            raise ValueError("Ollama model identity is invalid")
        if "model" in payload or "stream" in payload:
            raise ValueError("Ollama model and stream mode are gateway-owned")
        has_messages = isinstance(payload.get("messages"), list)
        has_prompt = isinstance(payload.get("prompt"), str)
        if has_messages == has_prompt:
            raise ValueError("Ollama payload requires exactly one prompt or messages input")
        request_payload = dict(payload)
        request_payload.update({"model": model, "stream": False})
        encoded = _canonical(request_payload, limit=MAX_REQUEST_BYTES)
        endpoint = "/api/chat" if has_messages else "/api/generate"
        request = Request(
            f"{self.base_url}{endpoint}",
            data=encoded,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Ollama response exceeds the configured byte bound")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Ollama returned invalid JSON") from error
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Ollama returned an invalid terminal response")
        value = (
            result.get("message", {}).get("content")
            if has_messages and isinstance(result.get("message"), dict)
            else result.get("response")
        )
        if not isinstance(value, str):
            raise ValueError("Ollama terminal response omitted model output")
        input_tokens = result.get("prompt_eval_count", 0)
        output_tokens = result.get("eval_count", 0)
        if (
            not isinstance(input_tokens, int)
            or isinstance(input_tokens, bool)
            or input_tokens < 0
            or not isinstance(output_tokens, int)
            or isinstance(output_tokens, bool)
            or output_tokens < 0
        ):
            raise ValueError("Ollama terminal response has invalid usage metadata")
        return ProviderResponse(
            value=value,
            usage=ProviderUsage(
                billing_state="local_non_billable",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                charge_microunits=0,
            ),
        )


class ColdRuntimeHttpAdapter:
    """Loopback terminal adapter for an already-started governed cold runtime.

    The adapter never starts, pulls, prepares, unloads, or routes a model.  It
    only carries an exact runtime receipt into the provider gateway so the
    invocation remains bound to the lifecycle event that created the endpoint.
    """

    def __init__(
        self,
        adapter_id: str,
        base_url: str,
        *,
        endpoint_path: str,
        session_id: str,
        model_identity: str,
        runtime_receipt_sha256: str,
        timeout_seconds: float = 300.0,
        opener: object | None = None,
    ) -> None:
        if type(adapter_id) is not str or adapter_id not in {"docker-model-runner-http", "airllm-http"}:
            raise ValueError("cold runtime adapter identity is unsupported")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        ):
            raise ValueError("cold runtime adapter requires a literal loopback HTTP origin")
        if endpoint_path not in {"/v1/chat/completions", "/engines/v1/chat/completions"}:
            raise ValueError("cold runtime adapter endpoint is unsupported")
        if type(session_id) is not str or not session_id or len(session_id) > 192:
            raise ValueError("cold runtime session identity is invalid")
        if type(model_identity) is not str or not model_identity or len(model_identity) > 512:
            raise ValueError("cold runtime model identity is invalid")
        if (
            type(runtime_receipt_sha256) is not str or len(runtime_receipt_sha256) != 64
            or any(c not in "0123456789abcdef" for c in runtime_receipt_sha256)
        ):
            raise ValueError("cold runtime receipt digest is invalid")
        if type(timeout_seconds) not in (int, float) or type(timeout_seconds) is bool or not math.isfinite(float(timeout_seconds)) or not 1 <= float(timeout_seconds) <= 3600:
            raise ValueError("cold runtime timeout must be finite and bounded")
        self.adapter_id = adapter_id
        self.base_url = base_url.rstrip("/")
        self.endpoint_path = endpoint_path
        self.session_id = session_id
        self.model_identity = model_identity
        self.runtime_receipt_sha256 = runtime_receipt_sha256
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(ProxyHandler({}))

    def invoke(self, model_id: str, payload: Mapping[str, object]) -> ProviderResponse:
        if model_id != self.model_identity:
            raise ValueError("cold runtime request model differs from its lifecycle identity")
        if "model" in payload or "stream" in payload:
            raise ValueError("cold runtime model and stream mode are gateway-owned")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("cold runtime payload requires non-empty messages")
        request_payload = dict(payload)
        request_payload.update({"model": model_id, "stream": False})
        encoded = _canonical(request_payload, limit=MAX_REQUEST_BYTES)
        request = Request(
            f"{self.base_url}{self.endpoint_path}", data=encoded,
            headers={
                "Content-Type": "application/json", "Accept": "application/json",
                "X-Pacify-Local-Session": self.session_id,
                "X-Pacify-Cold-Runtime-Receipt": self.runtime_receipt_sha256,
            }, method="POST",
        )
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("cold runtime response exceeds the configured byte bound")
        try:
            result = json.loads(raw.decode("utf-8"))
            value = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise ValueError("cold runtime returned an invalid terminal response") from error
        if not isinstance(value, str) or any(
            type(count) is not int or count < 0 for count in (input_tokens, output_tokens)
        ):
            raise ValueError("cold runtime terminal response has invalid output or usage")
        return ProviderResponse(value, ProviderUsage("local_non_billable", input_tokens, output_tokens, 0))


class LlamaCppHttpAdapter:
    """Bounded loopback-only adapter for an owned llama.cpp server session."""

    adapter_id = "llama-cpp-http"

    def __init__(
        self,
        base_url: str,
        *,
        session_id: str,
        model_sha256: str,
        timeout_seconds: float = 120.0,
        opener: object | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("llama.cpp adapter requires a literal loopback HTTP origin")
        if not session_id.startswith("local-model-session-"):
            raise ValueError("llama.cpp session identity is invalid")
        if len(model_sha256) != 64 or any(character not in "0123456789abcdef" for character in model_sha256):
            raise ValueError("llama.cpp model digest is invalid")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("llama.cpp timeout must be between 1 and 300 seconds")
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.model_sha256 = model_sha256
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(ProxyHandler({}))

    def invoke(self, model_id: str, payload: Mapping[str, object]) -> ProviderResponse:
        if model_id != self.model_sha256:
            raise ValueError("llama.cpp request model does not match the admitted digest")
        if "model" in payload or "stream" in payload:
            raise ValueError("llama.cpp model and stream mode are gateway-owned")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("llama.cpp payload requires non-empty messages")
        request_payload = dict(payload)
        request_payload.update({"model": self.model_sha256, "stream": False})
        raw_request = _canonical(request_payload, limit=MAX_REQUEST_BYTES)
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=raw_request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Pacify-Local-Session": self.session_id,
            },
            method="POST",
        )
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("llama.cpp response exceeds the configured byte bound")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("llama.cpp returned invalid JSON") from error
        try:
            value = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ValueError("llama.cpp returned an invalid terminal response") from error
        if not isinstance(value, str) or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in (input_tokens, output_tokens)
        ):
            raise ValueError("llama.cpp terminal response has invalid output or usage")
        return ProviderResponse(
            value=value,
            usage=ProviderUsage("local_non_billable", input_tokens, output_tokens, 0),
        )


class LlamaCppStreamingHttpAdapter:
    """Unadmitted-by-default llama.cpp streaming protocol adapter.

    The adapter is executable only when its exact adapter_id is admitted by
    registry/provider_adapters.json.  It never treats generic localhost as authority.
    """

    _SURFACES = {
        "llama-cpp-stream": ("openai_chat", "/v1/chat/completions", "/v1/chat/completions/input_tokens"),
        "llama-cpp-responses": ("openai_responses", "/v1/responses", "/v1/responses/input_tokens"),
        "llama-cpp-anthropic": ("anthropic_messages", "/v1/messages", "/v1/messages/count_tokens"),
    }

    def __init__(
        self,
        base_url: str,
        *,
        adapter_id: str,
        session_id: str,
        model_sha256: str,
        wire_model_name: str | None = None,
        timeout_seconds: float = 120.0,
        opener: object | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("llama.cpp streaming adapter requires a literal loopback HTTP origin")
        if adapter_id not in self._SURFACES:
            raise ValueError("llama.cpp streaming adapter_id is not an exact supported façade")
        if not session_id.startswith("local-model-session-"):
            raise ValueError("llama.cpp streaming session identity is invalid")
        if len(model_sha256) != 64 or any(character not in "0123456789abcdef" for character in model_sha256):
            raise ValueError("llama.cpp streaming model digest is invalid")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 1 <= float(timeout_seconds) <= 300
        ):
            raise ValueError("llama.cpp streaming timeout must be finite and between 1 and 300 seconds")
        self.base_url = base_url.rstrip("/")
        self.adapter_id = adapter_id
        self.protocol_surface = self._SURFACES[adapter_id][0]
        self.session_id = session_id
        self.model_sha256 = model_sha256
        # The llama.cpp router identifies a model by its PRESET key, while PX identifies it by its
        # content digest. Identity assertions use the digest; the wire request must carry the key,
        # or the router rejects the request even though the model is loaded.
        if wire_model_name is None:
            wire_model_name = model_sha256
        if (
            not isinstance(wire_model_name, str)
            or not wire_model_name
            or len(wire_model_name) > 256
            or any(character.isspace() for character in wire_model_name)
        ):
            raise ValueError("llama.cpp wire model name is invalid")
        self.wire_model_name = wire_model_name
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(ProxyHandler({}))

    def _assert_request(self, model_id: str, request: CanonicalModelRequest) -> None:
        if model_id != self.model_sha256:
            raise ValueError("llama.cpp streaming request model differs from the admitted digest")
        if request.route not in {self.adapter_id, "local", "local-model"}:
            raise ValueError("canonical request route does not identify this llama.cpp adapter")

    def stream(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> Iterable[CanonicalModelEvent]:
        self._assert_request(model_id, request)
        _, endpoint, _ = self._SURFACES[self.adapter_id]
        payload = canonical_request_to_wire(
            request,
            surface=self.protocol_surface,
            model_id=self.wire_model_name,
            stream=True,
        )
        raw_request = _canonical(payload, limit=MAX_REQUEST_BYTES)
        http_request = Request(
            f"{self.base_url}{endpoint}",
            data=raw_request,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Pacify-Local-Session": self.session_id,
            },
            method="POST",
        )
        translator = WireStreamTranslator(
            surface=self.protocol_surface,
            request_id=request.request_id,
            adapter_id=self.adapter_id,
            model_id=self.model_sha256,
        )
        control.check()
        with self._opener.open(
            http_request,
            timeout=control.remaining_seconds(cap=self.timeout_seconds),
        ) as response:
            def lines() -> Iterable[bytes]:
                total = 0
                while True:
                    control.check()
                    line = response.readline(MAX_RESPONSE_BYTES + 1)
                    if not isinstance(line, (bytes, bytearray)):
                        raise ValueError("llama.cpp streaming response must yield bytes")
                    if not line:
                        break
                    total += len(line)
                    if total > MAX_RESPONSE_BYTES * 4:
                        raise ValueError("llama.cpp normalized stream transport exceeds its byte bound")
                    yield bytes(line)

            for event_name, data in iter_sse_frames(lines()):
                control.check()
                for event in translator.feed_sse(event_name, data):
                    yield event
        if not translator.finished:
            raise ValueError("llama.cpp stream ended before a terminal provider event")

    def count_tokens(
        self,
        model_id: str,
        request: CanonicalModelRequest,
        control: ProviderStreamControl,
    ) -> TokenCount:
        self._assert_request(model_id, request)
        _, _, endpoint = self._SURFACES[self.adapter_id]
        payload = canonical_request_to_wire(
            request,
            surface=self.protocol_surface,
            model_id=self.model_sha256,
            stream=False,
        )
        raw_request = _canonical(payload, limit=MAX_REQUEST_BYTES)
        http_request = Request(
            f"{self.base_url}{endpoint}",
            data=raw_request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Pacify-Local-Session": self.session_id,
            },
            method="POST",
        )
        control.check()
        with self._opener.open(
            http_request,
            timeout=control.remaining_seconds(cap=self.timeout_seconds),
        ) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("llama.cpp token-count response exceeds its byte bound")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("llama.cpp token-count response is invalid JSON") from error
        if type(payload) is not dict or type(payload.get("input_tokens")) is not int or isinstance(payload.get("input_tokens"), bool) or payload["input_tokens"] < 0:
            raise ValueError("llama.cpp token-count response omitted exact input_tokens")
        return TokenCount(
            TOKEN_COUNT_SCHEMA_VERSION,
            request.request_id,
            self.adapter_id,
            self.model_sha256,
            int(payload["input_tokens"]),
            True,
        )

    def provider_usage(self, usage: Mapping[str, object]) -> ProviderUsage:
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if any(
            type(value) is not int or isinstance(value, bool) or value < 0
            for value in (input_tokens, output_tokens)
        ):
            raise ValueError("llama.cpp canonical stream usage is invalid")
        provider_request_id = usage.get("provider_request_id")
        if provider_request_id is not None and not isinstance(provider_request_id, str):
            raise ValueError("llama.cpp provider request id is invalid")
        return ProviderUsage(
            "local_non_billable",
            int(input_tokens),
            int(output_tokens),
            0,
            provider_request_id,
        )


def _canonical(value: object, *, limit: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("provider value must be canonical JSON") from error
    if len(encoded) > limit:
        raise ValueError("provider value exceeds the configured byte bound")
    return encoded


def _digest(value: object, *, limit: int) -> str:
    return hashlib.sha256(_canonical(value, limit=limit)).hexdigest()


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def load_provider_registry(root: Path) -> dict[str, object]:
    """Load the adapter allow-list as hostile data and enforce semantic rules."""
    try:
        value = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
        validate_instance(value, root / REGISTRY_SCHEMA)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ContractValidationError,
    ) as error:
        raise ValueError("provider adapter registry is invalid") from error
    seen: set[str] = set()
    for row in value["adapters"]:
        adapter_id = str(row["adapter_id"])
        if adapter_id in seen:
            raise ValueError(f"duplicate provider adapter: {adapter_id}")
        seen.add(adapter_id)
        if row["admitted"] is True and row["status"] != "ready":
            raise ValueError(f"admitted provider adapter is not ready: {adapter_id}")
        if row["mode"] == "local" and row["billing_state"] != "local_non_billable":
            raise ValueError(f"local adapter billing state is invalid: {adapter_id}")
    return value


def _attribute_name(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _scan_provider_file(path: Path, relative: str) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as error:
        return [{"path": relative, "line": None, "kind": "unscannable", "detail": type(error).__name__}]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == name or alias.name.startswith(name + ".") for name in _DIRECT_PROVIDER_IMPORTS):
                    violations.append({"path": relative, "line": node.lineno, "kind": "provider_import", "detail": alias.name})
        elif isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module == name or node.module.startswith(name + ".") for name in _DIRECT_PROVIDER_IMPORTS):
                violations.append({"path": relative, "line": node.lineno, "kind": "provider_import", "detail": node.module})
        elif isinstance(node, ast.Call):
            name = _attribute_name(node.func)
            if any(name == suffix or name.endswith("." + suffix) for suffix in _DIRECT_CALL_SUFFIXES):
                violations.append({"path": relative, "line": node.lineno, "kind": "provider_call", "detail": name})
    return violations


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _provider_source_paths(root: Path) -> list[Path]:
    return sorted(
        (path for base in (root / "runtime", root / "scripts") if base.is_dir() for path in base.rglob("*.py") if "__pycache__" not in path.parts),
        key=lambda item: item.as_posix(),
    )


def _scan_direct_provider_routes(root: Path) -> dict[str, object]:
    """Find obvious model-client bypasses without importing repository code."""
    violations: list[dict[str, object]] = []
    for path in _provider_source_paths(root):
        relative = path.relative_to(root).as_posix()
        if relative != "runtime/provider_gateway.py":
            violations.extend(_scan_provider_file(path, relative))
    return {
        "schema_version": "px.provider-reachability/1.0",
        "valid": not violations,
        "scanned_roots": ["runtime", "scripts"],
        "allowed_gateway": "runtime/provider_gateway.py",
        "violation_count": len(violations),
        "violations": violations,
    }


def build_provider_route_index(root: Path) -> dict[str, object]:
    root = root.resolve()
    index_path = root / "registry/provider_route_scan.json"
    try:
        previous = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    prior = {str(item.get("path")): item for item in previous.get("records", ()) if isinstance(item, dict)}
    records = []
    violations: list[dict[str, object]] = []
    for path in _provider_source_paths(root):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        content_sha256 = _file_sha256(path)
        old = prior.get(relative, {})
        unchanged = (
            old.get("bytes") == stat.st_size
            and old.get("sha256") == content_sha256
            and isinstance(old.get("violations"), list)
        )
        if unchanged:
            file_violations = list(old["violations"])
        else:
            file_violations = [] if relative == "runtime/provider_gateway.py" else _scan_provider_file(path, relative)
        violations.extend(file_violations)
        records.append({
            "path": relative,
            "bytes": stat.st_size,
            "sha256": content_sha256,
            "scan_state": "verified",
            "violations": file_violations,
        })
    report = {
        "schema_version": "px.provider-reachability/1.0",
        "valid": not violations,
        "scanned_roots": ["runtime", "scripts"],
        "allowed_gateway": "runtime/provider_gateway.py",
        "violation_count": len(violations),
        "violations": violations,
    }
    return {
        "schema_version": "px.provider-route-index/1.3",
        "records": records,
        "report": report,
        "verified_file_count": len(records),
    }


def scan_direct_provider_routes(root: Path) -> dict[str, object]:
    """Use the native source index when current; never silently rediscover it."""
    root = root.resolve()
    index_path = root / "registry/provider_route_scan.json"
    if (root / "pyproject.toml").is_file() and index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            expected = {str(item["path"]): item for item in index.get("records", ())}
            current: dict[str, dict[str, object]] = {}
            for path in _provider_source_paths(root):
                stat = path.stat()
                current[path.relative_to(root).as_posix()] = {
                    "bytes": stat.st_size,
                    "sha256": _file_sha256(path),
                }
            fresh = set(current) == set(expected) and all(
                current[path]["bytes"] == int(record["bytes"])
                and current[path]["sha256"] == str(record["sha256"])
                for path, record in expected.items()
            )
            if fresh:
                return {**dict(index["report"]), "index_used": True, "index_current": True}
            return {
                "schema_version": "1.0",
                "valid": False,
                "violation_count": 1,
                "violations": [{"path": "registry/provider_route_scan.json", "line": None, "kind": "index_stale", "detail": "run python scripts/build_provider_route_index.py"}],
                "index_used": True,
                "index_current": False,
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return {
                "schema_version": "1.0",
                "valid": False,
                "violation_count": 1,
                "violations": [{"path": "registry/provider_route_scan.json", "line": None, "kind": "index_invalid", "detail": "run python scripts/build_provider_route_index.py"}],
                "index_used": True,
                "index_current": False,
            }
    return {**_scan_direct_provider_routes(root), "index_used": False, "index_current": False}


class ProviderInvocationGateway:
    """Invoke an admitted adapter while emitting metadata-only durable lifecycles."""

    def __init__(
        self,
        engine_root: Path,
        event_bus: OperationalEventBus,
        budget_ledger: ProviderBudgetLedger,
        *,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.engine_root = engine_root.resolve(strict=True)
        if event_bus.engine_root != self.engine_root:
            raise ValueError("provider event bus belongs to a different engine root")
        if budget_ledger.engine_root != self.engine_root:
            raise ValueError("provider budget ledger belongs to a different engine root")
        if budget_ledger.allowed_root != event_bus.allowed_root:
            raise ValueError("provider event and budget authorities must share custody")
        self.event_bus = event_bus
        self.budget_ledger = budget_ledger
        self.clock = clock

    def _adapter_record(self, adapter_id: str) -> dict[str, object]:
        registry = load_provider_registry(self.engine_root)
        matches = [
            row for row in registry["adapters"] if row["adapter_id"] == adapter_id
        ]
        if not matches:
            raise PermissionError(f"provider adapter is not registered: {adapter_id}")
        row = dict(matches[0])
        if row["admitted"] is not True or row["status"] != "ready":
            raise PermissionError(
                f"provider adapter is not admitted and ready: {adapter_id}"
            )
        return row

    def _event(
        self,
        request: ProviderRequest,
        record: Mapping[str, object],
        *,
        lifecycle: str,
        result: str,
        observed_at: str,
        input_sha256: str,
        output_sha256: str | None,
        operation_name: str | None = None,
    ) -> dict[str, object]:
        head = self.event_bus.head()
        if not head["valid"]:
            raise ValueError("provider event ancestry is degraded")
        previous = head["event_sha256"]
        route_id = (
            "provider.local-model"
            if record["mode"] == "local"
            else "provider.remote-model"
        )
        payload = {
            "sdk_version": SDK_VERSION,
            "event_id": f"{request.invocation_id}-{lifecycle}",
            "correlation_id": request.correlation_id,
            "parent_correlation_id": request.invocation_id,
            "actor": {
                "actor_id": request.actor_id,
                "actor_kind": "agent",
                "session_id": request.session_id,
                "harness": request.harness,
                "accountable_owner": request.accountable_owner,
            },
            "work": {
                "project_id": request.project_id,
                "task_id": request.task_id,
                "claim_id": request.claim_id,
                "orchestration_id": request.orchestration_id,
            },
            "source": {
                "route_id": route_id,
                "component": "runtime/provider_gateway.py",
                "host_id": None,
                "coverage_tier": "A",
            },
            "operation": {
                "name": operation_name or f"provider.invoke:{record['provider_id']}:{request.model_id}",
                "lifecycle": lifecycle,
                "result": result,
            },
            "effects": {
                "declared": ["model"]
                if record["mode"] == "local"
                else ["network", "model"],
                "observed": ["model"]
                if record["mode"] == "local"
                else ["network", "model"],
                "scope_refs": [
                    f"adapter:{request.adapter_id}",
                    f"model:{request.model_id}",
                ],
            },
            "provider": {
                "provider_id": record["provider_id"],
                "request_id": request.invocation_id,
                "budget_id": request.budget_id,
                "billing_state": record["billing_state"],
            },
            "time": {
                "observed_at": observed_at,
                "started_at": observed_at if lifecycle == "started" else None,
                "duration_ms": None,
                "freshness": "live",
            },
            "integrity": {
                "input_sha256": input_sha256,
                "output_sha256": output_sha256,
                "previous_event_sha256": previous,
            },
            "capture": {"classification": "metadata_only", "payload_included": False},
        }
        return build_operation_event(self.engine_root, payload)

    def _invoke_once(
        self,
        request: ProviderRequest,
        adapter: ProviderAdapter,
        *,
        fallback_from: str | None = None,
    ) -> tuple[object, dict[str, object]]:
        """Reserve, invoke once, and durably settle the exact adapter attempt."""
        if not request.invocation_id.strip() or not request.correlation_id.strip():
            raise ValueError("invocation and correlation identities are required")
        if not request.budget_id:
            raise PermissionError("a provider budget identity is required")
        if adapter.adapter_id != request.adapter_id:
            raise PermissionError("adapter identity differs from the request")
        adapter_binding_receipt_sha256 = getattr(adapter, "runtime_receipt_sha256", None)
        if adapter_binding_receipt_sha256 is not None and (
            type(adapter_binding_receipt_sha256) is not str
            or len(adapter_binding_receipt_sha256) != 64
            or any(c not in "0123456789abcdef" for c in adapter_binding_receipt_sha256)
        ):
            raise ValueError("provider adapter runtime binding receipt digest is invalid")
        record = self._adapter_record(request.adapter_id)
        input_sha256 = _digest(request.payload, limit=MAX_REQUEST_BYTES)
        reservation = self.budget_ledger.reserve(
            invocation_id=request.invocation_id,
            correlation_id=request.correlation_id,
            budget_id=request.budget_id,
            actor_id=request.actor_id,
            provider_id=str(record["provider_id"]),
            adapter_id=request.adapter_id,
            billing_state=str(record["billing_state"]),
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            fallback_from=fallback_from,
        )
        started_at = self.clock()
        try:
            started = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="started",
                    result="pending",
                    observed_at=started_at,
                    input_sha256=input_sha256,
                    output_sha256=None,
                )
            )
        except BaseException:
            self.budget_ledger.settle(
                request.invocation_id, outcome="failure", usage=None
            )
            raise
        try:
            response = adapter.invoke(request.model_id, request.payload)
            if not isinstance(response, ProviderResponse):
                raise TypeError("provider adapter omitted explicit usage metadata")
            output_sha256 = _digest(response.value, limit=MAX_RESPONSE_BYTES)
        except BaseException as error:
            budget_receipt = self.budget_ledger.settle(
                request.invocation_id, outcome="failure", usage=None
            )
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=None,
                )
            )
            failure = ProviderInvocationError(request.adapter_id, type(error).__name__)
            failure.add_note(f"durable_event_revision={failed['revision']}")
            failure.add_note(
                f"budget_receipt_sha256={budget_receipt['receipt_sha256']}"
            )
            raise failure from None
        try:
            budget_receipt = self.budget_ledger.settle(
                request.invocation_id, outcome="success", usage=response.usage
            )
        except BaseException:
            # The provider was called but accounting did not certify its usage. The
            # same reservation is conservatively burned before returning failure.
            try:
                self.budget_ledger.settle(
                    request.invocation_id, outcome="failure", usage=None
                )
            except BaseException:
                pass
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                )
            )
            error = ProviderInvocationError(request.adapter_id, "AccountingFailure")
            error.add_note(f"durable_event_revision={failed['revision']}")
            raise error from None
        if budget_receipt["policy_overrun"] is True:
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                )
            )
            error = ProviderInvocationError(request.adapter_id, "BudgetOverrun")
            error.add_note(f"durable_event_revision={failed['revision']}")
            error.add_note(
                f"budget_receipt_sha256={budget_receipt['receipt_sha256']}"
            )
            raise error from None
        completed = self.event_bus.publish(
            self._event(
                request,
                record,
                lifecycle="completed",
                result="success",
                observed_at=self.clock(),
                input_sha256=input_sha256,
                output_sha256=output_sha256,
            )
        )
        receipt = {
            "schema_version": "px.provider-invocation-receipt/1.0",
            "invocation_id": request.invocation_id,
            "correlation_id": request.correlation_id,
            "adapter_id": request.adapter_id,
            "provider_id": record["provider_id"],
            "model_id": request.model_id,
            "billing_state": record["billing_state"],
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "started_revision": started["revision"],
            "completed_revision": completed["revision"],
            "budget_receipt_sha256": budget_receipt["receipt_sha256"],
            "budget_reservation_receipt_sha256": reservation["receipt_sha256"],
            "currency": budget_receipt["currency"],
            "charge_microunits": budget_receipt["charge_microunits"],
            "input_tokens": budget_receipt["input_tokens"],
            "output_tokens": budget_receipt["output_tokens"],
            "payload_retained": False,
        }
        if adapter_binding_receipt_sha256 is not None:
            receipt["adapter_binding_receipt_sha256"] = adapter_binding_receipt_sha256
        return response.value, receipt

    def _protocol_record(self, adapter_id: str) -> tuple[dict[str, object], str]:
        protocols = load_provider_protocols(self.engine_root)
        rows = [row for row in protocols["adapters"] if row["adapter_id"] == adapter_id]
        if len(rows) != 1:
            raise PermissionError(f"provider protocol capabilities are not exact for adapter: {adapter_id}")
        return dict(rows[0]), canonical_sha256(protocols, limit=MAX_REQUEST_BYTES)

    def _canonical_request(self, request: ProviderRequest) -> CanonicalModelRequest:
        canonical = canonical_request_from_mapping(request.payload)
        if canonical.request_id != request.invocation_id:
            raise ValueError("canonical model request_id differs from provider invocation_id")
        if request.session_id is not None and canonical.session_id != request.session_id:
            raise ValueError("canonical model session_id differs from provider session_id")
        return canonical

    def count_tokens(
        self,
        request: ProviderRequest,
        adapter: StreamingProviderAdapter,
        *,
        cancel_requested: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> tuple[TokenCount, dict[str, object]]:
        """Count tokens through an exact local admitted adapter without generation."""
        if adapter.adapter_id != request.adapter_id:
            raise PermissionError("adapter identity differs from the request")
        record = self._adapter_record(request.adapter_id)
        if record["mode"] != "local":
            raise PermissionError("remote token counting requires a separately budgeted network contract")
        protocol, protocols_sha256 = self._protocol_record(request.adapter_id)
        if protocol["implemented"] is not True or protocol["exact_token_count"] is not True:
            raise PermissionError("adapter does not have implemented exact token counting")
        surface = validate_protocol_surface(getattr(adapter, "protocol_surface", ""))
        if surface not in protocol["surfaces"]:
            raise PermissionError("adapter protocol surface differs from its exact capability record")
        canonical = self._canonical_request(request)
        control = ProviderStreamControl(
            canonical.deadline_ms,
            cancel_requested=cancel_requested,
            monotonic=monotonic,
        )
        input_sha256 = canonical.request_sha256
        started = self.event_bus.publish(
            self._event(
                request,
                record,
                lifecycle="started",
                result="pending",
                observed_at=self.clock(),
                input_sha256=input_sha256,
                output_sha256=None,
                operation_name=f"provider.count_tokens:{record['provider_id']}:{request.model_id}",
            )
        )
        try:
            result = adapter.count_tokens(request.model_id, canonical, control)
            if not isinstance(result, TokenCount) or result.exact is not True:
                raise TypeError("provider adapter omitted an exact token-count contract")
            if (result.request_id, result.adapter_id, result.model_id) != (
                request.invocation_id,
                request.adapter_id,
                request.model_id,
            ):
                raise ValueError("provider token-count identity differs from the request")
            output_sha256 = canonical_sha256(result.as_dict(), limit=MAX_RESPONSE_BYTES)
        except BaseException as error:
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=None,
                    operation_name=f"provider.count_tokens:{record['provider_id']}:{request.model_id}",
                )
            )
            failure = ProviderInvocationError(request.adapter_id, type(error).__name__)
            failure.add_note(f"durable_event_revision={failed['revision']}")
            raise failure from None
        completed = self.event_bus.publish(
            self._event(
                request,
                record,
                lifecycle="completed",
                result="success",
                observed_at=self.clock(),
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                operation_name=f"provider.count_tokens:{record['provider_id']}:{request.model_id}",
            )
        )
        receipt = {
            "schema_version": "px.provider-token-count-receipt/1.0",
            "invocation_id": request.invocation_id,
            "adapter_id": request.adapter_id,
            "model_id": request.model_id,
            "protocol_surface": surface,
            "provider_protocols_sha256": protocols_sha256,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "input_tokens": result.input_tokens,
            "exact": True,
            "started_revision": started["revision"],
            "completed_revision": completed["revision"],
            "payload_retained": False,
        }
        return result, {**receipt, "receipt_sha256": _digest(receipt, limit=MAX_RESPONSE_BYTES)}

    def stream(
        self,
        request: ProviderRequest,
        adapter: StreamingProviderAdapter,
        on_event: Callable[[CanonicalModelEvent], None],
        *,
        cancel_requested: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> dict[str, object]:
        """Stream normalized events and settle only after an exact terminal receipt.

        Raw backend SSE never leaves the adapter.  The callback receives only PX
        CanonicalModelEvent objects.  Any callback failure, malformed stream,
        cancellation, deadline, provider error, accounting failure, or budget
        overrun fails closed and conservatively burns the reservation.
        """
        if not callable(on_event):
            raise ValueError("stream on_event must be callable")
        if not request.invocation_id.strip() or not request.correlation_id.strip():
            raise ValueError("invocation and correlation identities are required")
        if not request.budget_id:
            raise PermissionError("a provider budget identity is required")
        if adapter.adapter_id != request.adapter_id:
            raise PermissionError("adapter identity differs from the request")
        record = self._adapter_record(request.adapter_id)
        protocol, protocols_sha256 = self._protocol_record(request.adapter_id)
        if protocol["implemented"] is not True or protocol["streaming"] is not True:
            raise PermissionError("provider adapter is not implemented for streaming")
        surface = validate_protocol_surface(getattr(adapter, "protocol_surface", ""))
        if surface not in protocol["surfaces"]:
            raise PermissionError("adapter protocol surface differs from its exact capability record")
        canonical = self._canonical_request(request)
        if canonical.tools and protocol["tools"] is not True:
            raise PermissionError("provider adapter is not certified for canonical tools")
        if canonical.response_schema is not None and protocol["structured_output"] is not True:
            raise PermissionError("provider adapter is not certified for structured output")
        if cancel_requested is not None and protocol["cancellation"] is not True:
            raise PermissionError("provider adapter is not certified for cancellation")
        if type(request.max_output_tokens) is not int or isinstance(request.max_output_tokens, bool) or request.max_output_tokens <= 0:
            raise ValueError("streaming provider output reservation must be a positive integer")
        if canonical.max_output_tokens > request.max_output_tokens:
            raise PermissionError("canonical max_output_tokens exceeds the reserved provider budget")
        control = ProviderStreamControl(
            canonical.deadline_ms,
            cancel_requested=cancel_requested,
            monotonic=monotonic,
        )
        input_sha256 = canonical.request_sha256
        reservation = self.budget_ledger.reserve(
            invocation_id=request.invocation_id,
            correlation_id=request.correlation_id,
            budget_id=request.budget_id,
            actor_id=request.actor_id,
            provider_id=str(record["provider_id"]),
            adapter_id=request.adapter_id,
            billing_state=str(record["billing_state"]),
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            fallback_from=None,
        )
        try:
            started = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="started",
                    result="pending",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=None,
                    operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
                )
            )
        except BaseException:
            self.budget_ledger.settle(request.invocation_id, outcome="failure", usage=None)
            raise
        state = CanonicalStreamState(request.invocation_id, request.adapter_id, request.model_id)
        request_accepted = False
        consumer_failed = False
        pending_finish: CanonicalModelEvent | None = None
        try:
            stream = adapter.stream(request.model_id, canonical, control)
            request_accepted = True
            for event in stream:
                control.check()
                if not isinstance(event, CanonicalModelEvent):
                    raise TypeError("streaming provider adapter emitted a non-canonical event")
                state.accept(event)
                if event.kind == "finish":
                    # Do not expose terminal success until usage has settled and
                    # the budget/accounting boundary has accepted the result.
                    pending_finish = event
                    continue
                try:
                    on_event(event)
                except BaseException:
                    consumer_failed = True
                    raise RuntimeError("stream consumer failed") from None
                if event.kind == "error":
                    raise RuntimeError("provider emitted a terminal canonical error")
            state.assert_complete(require_usage=True)
            if state.terminal_kind != "finish" or state.usage is None or pending_finish is None:
                raise ValueError("provider stream did not complete successfully")
            provider_usage = adapter.provider_usage(state.usage)
            if not isinstance(provider_usage, ProviderUsage):
                raise TypeError("streaming provider adapter omitted explicit usage metadata")
            output_sha256 = state.output_sha256
        except BaseException as error:
            control_reason = error.reason if isinstance(error, ProviderStreamControlError) else None
            if not consumer_failed:
                code = control_reason or "provider_stream_failure"
                retryable = False if control_reason is not None else classify_provider_retry(
                    request_accepted=request_accepted,
                    operation_mutates=False,
                    billable_effect_possible=record["billing_state"] != "local_non_billable",
                    receipt_proves_no_side_effect=False,
                ) != "unsafe_unreceipted_effect"
                try:
                    if pending_finish is not None:
                        # The client has not seen the withheld finish event, so an
                        # error at the same sequence preserves a contiguous stream.
                        generated = CanonicalModelEvent(
                            request.invocation_id, request.adapter_id, request.model_id,
                            pending_finish.seq, "error", {"code": code, "retryable": retryable}
                        )
                    elif state.terminal_kind is None:
                        generated = CanonicalModelEvent(
                            request.invocation_id, request.adapter_id, request.model_id,
                            state.next_seq, "error", {"code": code, "retryable": retryable}
                        )
                        state.accept(generated)
                    else:
                        generated = None
                    if generated is not None:
                        on_event(generated)
                except BaseException:
                    pass
            try:
                budget_receipt = self.budget_ledger.settle(
                    request.invocation_id, outcome="failure", usage=None
                )
            except BaseException:
                budget_receipt = None
            lifecycle = "cancelled" if control_reason == "cancelled" else "failed"
            result = "cancelled" if lifecycle == "cancelled" else "failure"
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle=lifecycle,
                    result=result,
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=None,
                    operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
                )
            )
            failure_type = (
                "Cancelled" if control_reason == "cancelled" else
                "DeadlineExceeded" if control_reason == "deadline_exceeded" else
                "ConsumerFailure" if consumer_failed else
                type(error).__name__
            )
            failure = ProviderInvocationError(request.adapter_id, failure_type)
            failure.add_note(f"durable_event_revision={failed['revision']}")
            if isinstance(budget_receipt, Mapping):
                failure.add_note(f"budget_receipt_sha256={budget_receipt['receipt_sha256']}")
            raise failure from None
        try:
            budget_receipt = self.budget_ledger.settle(
                request.invocation_id, outcome="success", usage=provider_usage
            )
        except BaseException:
            try:
                self.budget_ledger.settle(request.invocation_id, outcome="failure", usage=None)
            except BaseException:
                pass
            if pending_finish is not None:
                try:
                    on_event(CanonicalModelEvent(
                        request.invocation_id, request.adapter_id, request.model_id,
                        pending_finish.seq, "error", {"code": "accounting_failure", "retryable": False}
                    ))
                except BaseException:
                    pass
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                    operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
                )
            )
            failure = ProviderInvocationError(request.adapter_id, "AccountingFailure")
            failure.add_note(f"durable_event_revision={failed['revision']}")
            raise failure from None
        if budget_receipt["policy_overrun"] is True:
            if pending_finish is not None:
                try:
                    on_event(CanonicalModelEvent(
                        request.invocation_id, request.adapter_id, request.model_id,
                        pending_finish.seq, "error", {"code": "budget_overrun", "retryable": False}
                    ))
                except BaseException:
                    pass
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                    operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
                )
            )
            failure = ProviderInvocationError(request.adapter_id, "BudgetOverrun")
            failure.add_note(f"durable_event_revision={failed['revision']}")
            failure.add_note(f"budget_receipt_sha256={budget_receipt['receipt_sha256']}")
            raise failure from None
        assert pending_finish is not None
        try:
            on_event(pending_finish)
        except BaseException:
            failed = self.event_bus.publish(
                self._event(
                    request,
                    record,
                    lifecycle="failed",
                    result="failure",
                    observed_at=self.clock(),
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                    operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
                )
            )
            failure = ProviderInvocationError(request.adapter_id, "ConsumerFailure")
            failure.add_note(f"durable_event_revision={failed['revision']}")
            failure.add_note(f"budget_receipt_sha256={budget_receipt['receipt_sha256']}")
            raise failure from None
        completed = self.event_bus.publish(
            self._event(
                request,
                record,
                lifecycle="completed",
                result="success",
                observed_at=self.clock(),
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                operation_name=f"provider.stream:{record['provider_id']}:{request.model_id}",
            )
        )
        receipt = {
            "schema_version": "px.provider-stream-receipt/1.0",
            "invocation_id": request.invocation_id,
            "correlation_id": request.correlation_id,
            "adapter_id": request.adapter_id,
            "provider_id": record["provider_id"],
            "model_id": request.model_id,
            "protocol_surface": surface,
            "provider_protocols_sha256": protocols_sha256,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "stream_event_count": state.next_seq,
            "billing_state": record["billing_state"],
            "started_revision": started["revision"],
            "completed_revision": completed["revision"],
            "budget_receipt_sha256": budget_receipt["receipt_sha256"],
            "budget_reservation_receipt_sha256": reservation["receipt_sha256"],
            "currency": budget_receipt["currency"],
            "charge_microunits": budget_receipt["charge_microunits"],
            "input_tokens": budget_receipt["input_tokens"],
            "output_tokens": budget_receipt["output_tokens"],
            "payload_retained": False,
            "raw_backend_stream_retained": False,
        }
        return {**receipt, "receipt_sha256": _digest(receipt, limit=MAX_RESPONSE_BYTES)}

    def invoke(
        self,
        request: ProviderRequest,
        adapter: ProviderAdapter,
        *,
        fallback_adapter: ProviderAdapter | None = None,
    ) -> tuple[object, dict[str, object]]:
        """Invoke through the budgeted boundary with policy-controlled fallback."""
        try:
            return self._invoke_once(request, adapter)
        except ProviderInvocationError:
            if fallback_adapter is None:
                raise
            if not request.budget_id:
                raise PermissionError("a provider budget identity is required") from None
            primary = self._adapter_record(request.adapter_id)
            fallback = self._adapter_record(fallback_adapter.adapter_id)
            if fallback["provider_id"] != primary["provider_id"]:
                raise PermissionError(
                    "cross-provider fallback requires a distinct budget request"
                ) from None
            self.budget_ledger.assert_fallback_allowed(
                budget_id=request.budget_id,
                actor_id=request.actor_id,
                provider_id=str(primary["provider_id"]),
                fallback_adapter_id=fallback_adapter.adapter_id,
            )
            fallback_request = replace(
                request,
                invocation_id=f"{request.invocation_id}-fallback",
                adapter_id=fallback_adapter.adapter_id,
            )
            return self._invoke_once(
                fallback_request,
                fallback_adapter,
                fallback_from=request.invocation_id,
            )


def execute_provider_request(
    gateway: ProviderInvocationGateway,
    policy: Mapping[str, object],
    request: ProviderRequest,
    adapter: ProviderAdapter,
    *,
    fallback_adapter: ProviderAdapter | None = None,
) -> tuple[object, dict[str, object]]:
    """Execute only through an exact policy and return a policy-bound receipt."""
    request_view = {
        "task_plan_sha256": request.task_plan_sha256,
        "adapter_id": request.adapter_id,
        "model_id": request.model_id,
        "model_revision": request.model_revision,
        "model_attachment_sha256": request.model_attachment_sha256,
        "authority_revision": request.authority_revision,
        "requested_egress": request.requested_egress,
        "budget_id": request.budget_id,
        "expected_charge_microunits": request.expected_charge_microunits,
    }
    report = provider_execution_policy_report(policy, request_view)
    if not report["valid"]:
        raise PermissionError(
            "provider execution policy rejected request: "
            + ",".join(map(str, report["violation_ids"]))
        )
    allowed_fallbacks = {
        str(item.get("adapter_id")): item
        for item in policy.get("fallbacks", ())
        if isinstance(item, Mapping)
    }
    if fallback_adapter is not None and fallback_adapter.adapter_id not in allowed_fallbacks:
        raise PermissionError("provider fallback is outside the immutable policy")
    value, provider_receipt = gateway.invoke(
        request, adapter, fallback_adapter=fallback_adapter
    )
    if (
        provider_receipt.get("model_id") != request.model_id
        or provider_receipt.get("adapter_id")
        not in {request.adapter_id, getattr(fallback_adapter, "adapter_id", None)}
        or not _sha(provider_receipt.get("output_sha256"))
        or not _sha(provider_receipt.get("budget_receipt_sha256"))
    ):
        raise ProviderInvocationError(request.adapter_id, "ExactReceiptMissing")
    receipt = {
        "schema_version": "px.provider-execution-outcome/1.0",
        "policy_sha256": policy["policy_sha256"],
        "task_plan_sha256": request.task_plan_sha256,
        "model_attachment_sha256": request.model_attachment_sha256,
        "model_revision": request.model_revision,
        "authority_revision": request.authority_revision,
        "provider_receipt": provider_receipt,
        "exact_receipt": True,
    }
    return value, {**receipt, "outcome_sha256": _digest(receipt, limit=MAX_RESPONSE_BYTES)}
