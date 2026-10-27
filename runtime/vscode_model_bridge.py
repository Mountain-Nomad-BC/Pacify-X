"""Governed VS Code language-model bridge into the canonical PX provider gateway.

This module is intentionally a client adapter, not a routing or process authority.
It exposes only certified model profiles already bound to a currently-running
LocalModelRuntime router session.  It never starts/loads/unloads a model and never
accepts an arbitrary localhost endpoint from a caller.
"""
from __future__ import annotations

from .secure_publish import atomic_write_bytes, read_physical_bytes

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable, Mapping
from uuid import uuid4

from .local_model_runtime import LocalModelRuntime, _sha as lifecycle_event_digest
from .engineering_os_paths import resolve as resolve_control_path
from .model_profile import ModelRuntimeProfile, load_runtime_profiles
from .model_protocol import CanonicalModelRequest, CanonicalTool
from .operational_event_bus import OperationalEventBus
from .provider_budget import ProviderBudgetLedger
from .provider_gateway import (
    LlamaCppStreamingHttpAdapter,
    ProviderInvocationGateway,
    ProviderInvocationError,
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
    path = resolve_control_path(project_root, "local-model-runtime", "events.jsonl")
    if not path.is_file() or path.stat().st_size > MAX_EVENT_LOG_BYTES:
        return []
    rows: list[dict[str, object]] = []
    previous = None
    for line in read_physical_bytes(path, max_bytes=MAX_EVENT_LOG_BYTES).decode("utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if type(value) is not dict:
            raise ValueError("local-model runtime event log contains a non-object")
        body = {key: item for key, item in value.items() if key != "event_sha256"}
        if value.get("previous_event_sha256") != previous or value.get("event_sha256") != lifecycle_event_digest(body):
            raise ValueError("local-model lifecycle event chain is invalid")
        previous = value["event_sha256"]
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
    if type(plan) is not dict or plan.get("schema_version") not in {"px.local-model-router-pool-plan/1.0", "px.local-model-router-pool-plan/1.1"}:
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
        if plan.get("schema_version") == "px.local-model-router-pool-plan/1.1":
            preset = plan.get("preset_binding")
            members = preset.get("models") if type(preset) is dict else None
            if type(members) is not list:
                raise ValueError("router preset profile bindings are unavailable")
            matches = [row for row in members if type(row) is dict and row.get("model_id") == profile.model_id]
            if (len(matches) != 1 or matches[0].get("profile_sha256") != profile.profile_sha256
                    or matches[0].get("model_sha256") != admission["model_sha256"]):
                continue
        result.append({
            "profile_id": profile.profile_id,
            "provider_id": "llama.cpp",
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
    models = _available(engine_root, project_root)
    remote_status = "unconfigured"
    try:
        from .remote_model_bridge import list_models as remote_models
        remote = remote_models(engine_root, project_root)
        models += remote["models"]
        remote_status = "declared_unavailable" if remote["models"] else "unconfigured"
    except (OSError, ValueError, PermissionError, KeyError, TypeError):
        # A malformed authoritative remote configuration grants no stale route.
        # Do not leak configuration contents or invalidate genuine local profiles.
        remote_status = "configuration_invalid"
    return {"schema_version": "px.vscode-model-list/1.0", "models": models,
            "remote_catalog_status": remote_status, "authority_granted": False}


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
    state = project_root / ".agentic_engineering_os_px" / "model-client-gateway"
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
    execution_context = None
    if payload.get("execution_context") is not None:
        from .execution_context import execution_context_from_dict
        from .json_io import load_json_object
        from .archive_io import reject_path_links
        from datetime import datetime, timezone
        execution_context = execution_context_from_dict(payload["execution_context"])
        project_id = str(payload.get("project_id") or project_root.name or "workspace")
        if (execution_context.execution_id != request_id or execution_context.session_id != session_id
                or execution_context.project_id != project_id or execution_context.actor_id != ACTOR_ID
                or execution_context.provider_id != "llama.cpp"):
            raise ValueError("model invocation differs from its exact execution context")
        state_path = project_root / ".agentic_engineering_os_px/runtime-core/agent-console/task-state.json"
        reject_path_links(state_path)
        state = load_json_object(state_path, max_bytes=16 * 1024 * 1024)
        runs = state.get("runs")
        if state.get("schemaVersion") != "px.agent-task-store/2.0" or type(runs) is not list or len(runs) > 10000:
            raise ValueError("execution task state is unavailable or invalid")
        matches = [row for row in runs if type(row) is dict and row.get("runId") == execution_context.root_execution_id]
        if (len(matches) != 1 or state.get("epoch") != execution_context.epoch
                or matches[0].get("epoch") != execution_context.epoch
                or matches[0].get("revision") != execution_context.revision
                or matches[0].get("status") != "running"
                or execution_context.cancellation_scope_id != execution_context.root_execution_id):
            raise ValueError("execution is stale, cancelled, terminal or attributed to another run")
        remaining = (datetime.fromisoformat(execution_context.deadline_utc.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise ValueError("execution context deadline expired")
        deadline_ms = min(int(deadline_ms), int(remaining * 1000))
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
        metadata={"profile_id": profile.profile_id, "profile_sha256": profile.profile_sha256, "lane": profile.lane,
                  **({"execution_context": execution_context.as_dict()} if execution_context is not None else {})},
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


def set_sandbox_mode(engine_root: Path, project_root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """Record the Isolated Agent Sandbox mode selected by the UI.

    The UI only selects the mode; the PX runtime policy is the authority that
    enforces it. This command validates the selection, persists it as the
    workspace/session-scoped sandbox policy, and returns the effective policy. It
    never claims enforcement and never grants authority.
    """
    from .isolated_sandbox import (
        SandboxPolicyError,
        establish_sandbox,
        sandbox_off,
        sandbox_policy_from_dict,
    )

    if payload.get("schema_version") != "px.isolated-agent-sandbox-request/1.0":
        raise ValueError("sandbox request schema version is invalid")
    unknown = set(payload) - {
        "schema_version", "mode", "allowed_endpoints", "scope_key", "policy_revision",
        "component_acknowledgments",
    }
    if unknown:
        raise ValueError("sandbox request contains unsupported fields")
    raw_mode_value = payload.get("mode")
    if type(raw_mode_value) is not str:
        raise ValueError("sandbox mode must be text")
    raw_mode = raw_mode_value.strip().upper()
    if raw_mode not in {"OFF", "ON"}:
        raise ValueError("sandbox mode must be OFF or ON")
    scope_key = project_root.resolve(strict=True).as_posix()
    requested_scope = payload.get("scope_key")
    if requested_scope is not None and requested_scope != scope_key:
        raise ValueError("sandbox request scope does not match the project root")
    policy_revision_value = payload.get("policy_revision", "sandbox-r1")
    if type(policy_revision_value) is not str or not policy_revision_value.strip():
        raise ValueError("sandbox policy revision must be nonempty text")
    policy_revision = policy_revision_value
    endpoints = payload.get("allowed_endpoints", [])
    if type(endpoints) is not list:
        raise ValueError("allowed_endpoints must be a list")
    if raw_mode == "OFF":
        if endpoints:
            raise ValueError("allowed_endpoints must be empty when sandbox mode is OFF")
        policy = sandbox_off(scope_key=scope_key, policy_revision=policy_revision)
    else:
        if any(type(item) is not str for item in endpoints):
            raise ValueError("allowed_endpoints must contain only text values")
        policy = establish_sandbox(
            scope_key=scope_key,
            allowed_endpoints=endpoints,
            policy_revision=policy_revision,
            component_acknowledgments=payload.get("component_acknowledgments"),
        )
    image = policy.as_dict()
    # Round-trip through the decoder so a tampered/oversized image cannot persist.
    sandbox_policy_from_dict(image)
    state_root = project_root / ".agentic_engineering_os_px" / "sandbox"
    state_root.mkdir(parents=True, exist_ok=True)
    target = state_root / "isolated-agent-sandbox.json"
    atomic_write_bytes(target, (json.dumps(image, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "schema_version": "px.isolated-agent-sandbox-result/1.0",
        "mode": policy.mode,
        "policy": image,
        "authority_granted": False,
    }


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
    parser.add_argument("operation", choices=("list", "count", "chat", "context", "sandbox", "prepared-group"))
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    engine_root = Path(args.engine_root).resolve(strict=True)
    project_root = Path(args.project_root).resolve(strict=True)
    payload = _bounded_json_stdin()
    if args.operation == "prepared-group":
        from .prepared_group_transport import inspect_prepared_group
        print(json.dumps(inspect_prepared_group(project_root, payload), sort_keys=True, separators=(",", ":")))
    elif args.operation == "context":
        from .chat_context import retrieve_chat_context
        print(json.dumps(retrieve_chat_context(engine_root, project_root, payload), sort_keys=True, separators=(",", ":")))
    elif args.operation == "sandbox":
        print(json.dumps(set_sandbox_mode(engine_root, project_root, payload), sort_keys=True, separators=(",", ":")))
    elif args.operation == "list":
        print(json.dumps(list_models(engine_root, project_root), sort_keys=True, separators=(",", ":")))
    elif args.operation == "count":
        print(json.dumps(count_tokens(engine_root, project_root, payload), sort_keys=True, separators=(",", ":")))
    else:
        stream_chat(engine_root, project_root, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderInvocationError as error:
        sys.stdout.write(json.dumps({"type": "failure", "failure": {
            "schema_version": "px.provider-client-failure/1.0", "adapter_id": error.adapter_id,
            "failure_type": error.failure_type, **error.failure_metadata}}, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        raise SystemExit(2) from None
