"""Governed VS Code language-model bridge into the canonical PX provider gateway.

This module is intentionally a client adapter, not a routing or process authority.
It exposes only certified model profiles already bound to a currently-running
LocalModelRuntime router session.  It never starts/loads/unloads a model and never
accepts an arbitrary localhost endpoint from a caller.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable, Mapping
from uuid import uuid4

from .local_model_runtime import LocalModelRuntime
from .model_profile import ModelRuntimeProfile, load_runtime_profiles
from .model_protocol import CanonicalModelRequest, CanonicalTool
from .operational_event_bus import OperationalEventBus
from .provider_budget import ProviderBudgetLedger
from .provider_gateway import (
    LlamaCppStreamingHttpAdapter,
    ProviderInvocationGateway,
    ProviderRequest,
    load_provider_registry,
)

MAX_INPUT_BYTES = 1_048_576
MAX_EVENT_LOG_BYTES = 16 * 1024 * 1024
ADAPTER_ID = "llama-cpp-stream"
BUDGET_ID = "local-vscode-models"
ACTOR_ID = "pacify-x-vscode"


def _bounded_json_stdin() -> dict[str, object]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("VS Code model bridge request exceeds its byte bound")
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("VS Code model bridge request must be a JSON object")
    return value


def _event_rows(project_root: Path) -> list[dict[str, object]]:
    path = project_root / ".engineering-bootstrap" / "local-model-runtime" / "events.jsonl"
    if not path.is_file() or path.stat().st_size > MAX_EVENT_LOG_BYTES:
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if type(value) is not dict:
            raise ValueError("local-model runtime event log contains a non-object")
        rows.append(value)
    return rows


def _runtime_from_started(project_root: Path, event: Mapping[str, object]) -> tuple[LocalModelRuntime, str, dict[str, object]]:
    payload = event.get("payload")
    if type(payload) is not dict:
        raise ValueError("local-model start event payload is invalid")
    session_id = payload.get("session_id")
    plan = payload.get("plan")
    if type(session_id) is not str or not session_id.startswith("local-model-session-"):
        raise ValueError("local-model start event session identity is invalid")
    if type(plan) is not dict or plan.get("schema_version") != "px.local-model-router-pool-plan/1.0":
        raise ValueError("local-model start event is not a router-pool plan")
    command = plan.get("command")
    models = plan.get("models")
    if type(command) not in (list, tuple) or not command or type(command[0]) is not str:
        raise ValueError("router-pool executable identity is invalid")
    if type(models) not in (list, tuple) or not models:
        raise ValueError("router-pool model bindings are invalid")
    model_roots: set[Path] = set()
    for row in models:
        if type(row) is not dict or type(row.get("admission")) is not dict:
            raise ValueError("router-pool admission binding is invalid")
        model_path = row["admission"].get("model_path")
        if type(model_path) is not str:
            raise ValueError("router-pool model path is invalid")
        model_roots.add(Path(model_path).resolve(strict=True).parent)
    executable = Path(command[0]).resolve(strict=True)
    try:
        preset_index = command.index("--models-preset")
        preset = Path(command[preset_index + 1]).resolve(strict=True)
    except (ValueError, IndexError, TypeError) as error:
        raise ValueError("router-pool preset binding is invalid") from error
    runtime = LocalModelRuntime(
        project_root,
        allowed_model_roots=tuple(sorted(model_roots, key=str)),
        allowed_runtime_roots=(executable.parent,),
        allowed_config_roots=(preset.parent,),
    )
    if runtime.status(session_id)["state"] != "running":
        raise RuntimeError("local-model router session is not running")
    return runtime, session_id, plan


def _current_router(project_root: Path) -> tuple[LocalModelRuntime, str, dict[str, object]] | None:
    rows = _event_rows(project_root)
    for event in reversed(rows):
        if event.get("event_type") != "started":
            continue
        try:
            return _runtime_from_started(project_root, event)
        except (OSError, KeyError, ValueError, RuntimeError):
            continue
    return None


def _adapter_ready(engine_root: Path) -> bool:
    registry = load_provider_registry(engine_root)
    row = next((item for item in registry["adapters"] if item["adapter_id"] == ADAPTER_ID), None)
    return bool(row and row.get("admitted") is True and row.get("status") == "ready")


def _available(engine_root: Path, project_root: Path) -> list[dict[str, object]]:
    if not _adapter_ready(engine_root):
        return []
    current = _current_router(project_root)
    if current is None:
        return []
    runtime, session_id, plan = current
    states = runtime.router_model_states(session_id)
    bindings = {row["model_id"]: row for row in plan["models"] if type(row) is dict and type(row.get("model_id")) is str}
    result: list[dict[str, object]] = []
    for profile in load_runtime_profiles(engine_root):
        if not profile.is_certified or profile.model_id not in bindings:
            continue
        if states.get(profile.model_id) not in {"loaded", "sleeping"}:
            continue
        admission = bindings[profile.model_id].get("admission")
        if type(admission) is not dict or type(admission.get("model_sha256")) is not str:
            continue
        result.append({
            "profile_id": profile.profile_id,
            "model_id": profile.model_id,
            "model_sha256": admission["model_sha256"],
            "lane": profile.lane,
            "context_tokens": profile.context_tokens,
            "max_output_tokens": profile.max_output_tokens,
            "profile_sha256": profile.profile_sha256,
            "session_id": session_id,
            "adapter_id": ADAPTER_ID,
            "tool_calling": True,
            "image_input": False,
        })
    return result


def list_models(engine_root: Path, project_root: Path) -> dict[str, object]:
    return {
        "schema_version": "px.vscode-model-list/1.0",
        "models": _available(engine_root, project_root),
        "authority_granted": False,
    }


def _model(engine_root: Path, project_root: Path, profile_id: str) -> tuple[dict[str, object], ModelRuntimeProfile, LocalModelRuntime]:
    rows = _available(engine_root, project_root)
    item = next((row for row in rows if row["profile_id"] == profile_id), None)
    if item is None:
        raise PermissionError("requested VS Code model profile is not certified, loaded, and admitted")
    profile = next(p for p in load_runtime_profiles(engine_root) if p.profile_id == profile_id)
    current = _current_router(project_root)
    if current is None or current[1] != item["session_id"]:
        raise RuntimeError("local-model router changed during client admission")
    return item, profile, current[0]


def _messages(value: object) -> tuple[Mapping[str, object], ...]:
    if type(value) is not list or not value or len(value) > 4096:
        raise ValueError("model bridge messages require a bounded nonempty list")
    rows: list[Mapping[str, object]] = []
    for row in value:
        if type(row) is not dict or set(row) - {"role", "content", "name", "tool_call_id"}:
            raise ValueError("model bridge message shape is invalid")
        rows.append(dict(row))
    return tuple(rows)


def _tools(value: object) -> tuple[CanonicalTool, ...]:
    if value is None:
        return ()
    if type(value) is not list or len(value) > 128:
        raise ValueError("model bridge tools require a bounded list")
    result: list[CanonicalTool] = []
    for row in value:
        if type(row) is not dict or set(row) != {"name", "description", "input_schema"}:
            raise ValueError("model bridge tool declaration is invalid")
        result.append(CanonicalTool(str(row["name"]), str(row["description"]), row["input_schema"]))
    return tuple(result)


def _gateway(engine_root: Path, project_root: Path) -> ProviderInvocationGateway:
    state = project_root / ".engineering-bootstrap" / "model-client-gateway"
    state.mkdir(parents=True, exist_ok=True)
    return ProviderInvocationGateway(
        engine_root,
        OperationalEventBus(engine_root, state / "events", state),
        ProviderBudgetLedger(engine_root, state / "budget", state),
    )


def _request(engine_root: Path, project_root: Path, payload: Mapping[str, object]) -> tuple[ProviderRequest, LlamaCppStreamingHttpAdapter]:
    profile_id = payload.get("profile_id")
    if type(profile_id) is not str:
        raise ValueError("model bridge profile_id is required")
    model, profile, runtime = _model(engine_root, project_root, profile_id)
    request_id = payload.get("request_id") or f"vscode-model-{uuid4().hex}"
    session_id = payload.get("client_session_id") or f"vscode-{uuid4().hex}"
    if type(request_id) is not str or type(session_id) is not str:
        raise ValueError("model bridge request/session identity must be text")
    max_output = payload.get("max_output_tokens", profile.max_output_tokens)
    if type(max_output) is not int or isinstance(max_output, bool):
        raise ValueError("max_output_tokens must be an integer")
    max_output = min(max_output, profile.max_output_tokens)
    deadline_ms = payload.get("deadline_ms", 300_000)
    canonical = CanonicalModelRequest(
        request_id=request_id,
        session_id=session_id,
        client_id="vscode-language-model-provider",
        operation_id="vscode.language-model.chat",
        privacy="local",
        route=ADAPTER_ID,
        messages=_messages(payload.get("messages")),
        tools=_tools(payload.get("tools")),
        max_output_tokens=max_output,
        deadline_ms=int(deadline_ms),
        response_schema=payload.get("response_schema") if type(payload.get("response_schema")) is dict else None,
        metadata={"profile_id": profile.profile_id, "profile_sha256": profile.profile_sha256, "lane": profile.lane},
    )
    provider_request = ProviderRequest(
        invocation_id=request_id,
        correlation_id=str(payload.get("correlation_id") or f"corr-{request_id}"),
        project_id=str(payload.get("project_id") or project_root.name or "workspace"),
        adapter_id=ADAPTER_ID,
        model_id=str(model["model_sha256"]),
        actor_id=ACTOR_ID,
        accountable_owner="vscode-extension-host",
        payload=canonical.as_dict(),
        session_id=session_id,
        harness="VS Code",
        budget_id=BUDGET_ID,
        max_input_tokens=profile.context_tokens,
        max_output_tokens=profile.max_output_tokens,
        requested_egress="loopback",
    )
    adapter = LlamaCppStreamingHttpAdapter(
        runtime._router_origin(str(model["session_id"])),
        adapter_id=ADAPTER_ID,
        session_id=str(model["session_id"]),
        model_sha256=str(model["model_sha256"]),
        # The llama.cpp router resolves a model by its preset key, not by its content digest.
        # PX identity assertions still use the digest; the wire must carry the key.
        wire_model_name=str(model.get("model_id") or model["model_sha256"]),
    )
    return provider_request, adapter


def count_tokens(engine_root: Path, project_root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    request, adapter = _request(engine_root, project_root, payload)
    result, receipt = _gateway(engine_root, project_root).count_tokens(request, adapter)
    return {"schema_version": "px.vscode-token-count/1.0", "input_tokens": result.input_tokens, "exact": True, "receipt_sha256": receipt["receipt_sha256"]}


def stream_chat(engine_root: Path, project_root: Path, payload: Mapping[str, object]) -> None:
    request, adapter = _request(engine_root, project_root, payload)
    gateway = _gateway(engine_root, project_root)
    def emit(event) -> None:
        sys.stdout.write(json.dumps({"type": "event", "event": event.as_dict()}, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    receipt = gateway.stream(request, adapter, emit)
    sys.stdout.write(json.dumps({"type": "receipt", "receipt": receipt}, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("list", "count", "chat"))
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    engine_root = Path(args.engine_root).resolve(strict=True)
    project_root = Path(args.project_root).resolve(strict=True)
    payload = _bounded_json_stdin()
    if args.operation == "list":
        print(json.dumps(list_models(engine_root, project_root), sort_keys=True, separators=(",", ":")))
    elif args.operation == "count":
        print(json.dumps(count_tokens(engine_root, project_root, payload), sort_keys=True, separators=(",", ":")))
    else:
        stream_chat(engine_root, project_root, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
