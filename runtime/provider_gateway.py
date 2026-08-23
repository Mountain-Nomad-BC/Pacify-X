"""Single fail-closed invocation boundary for admitted model providers."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .contracts import ContractValidationError, validate_instance
from .instrumentation_sdk import SDK_VERSION, build_operation_event
from .operational_event_bus import OperationalEventBus
from .provider_budget import ProviderBudgetLedger, ProviderUsage


REGISTRY_PATH = Path("registry/provider_adapters.json")
REGISTRY_SCHEMA = Path("contracts/operations/provider-adapter-registry.schema.json")
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
                "name": f"provider.invoke:{record['provider_id']}:{request.model_id}",
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
        return response.value, receipt

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
