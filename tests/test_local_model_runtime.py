from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct
import threading
from types import SimpleNamespace

import pytest

from runtime.local_model_runtime import LocalModelRuntime, parse_gguf_metadata
from runtime.provider_budget import ProviderUsage
from runtime.provider_gateway import LlamaCppHttpAdapter, load_provider_registry
from runtime.resource_lifecycle import ResourceRecord


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _gguf(*, architecture: str = "llama", context: int = 4096) -> bytes:
    values = [
        ("general.architecture", 8, _string(architecture)),
        ("general.name", 8, _string("generic-test-model")),
        (f"{architecture}.context_length", 4, struct.pack("<I", context)),
        (f"{architecture}.embedding_length", 4, struct.pack("<I", 256)),
    ]
    return (
        b"GGUF" + struct.pack("<IQQ", 3, 1, len(values))
        + b"".join(_string(key) + struct.pack("<I", kind) + value for key, kind, value in values)
        + b"tensor-placeholder"
    )


class _Ledger:
    def __init__(self) -> None:
        self.records: dict[str, ResourceRecord] = {}

    def get(self, resource_id: str) -> ResourceRecord:
        return self.records[resource_id]


class _Process:
    pid = 4242

    def poll(self):
        return None


class _Manager:
    def __init__(self) -> None:
        self.ledger = _Ledger()
        self._processes: dict[str, _Process] = {}

    def spawn_owned_process(self, command, **kwargs):
        process = _Process()
        record = ResourceRecord(
            resource_id="process-test", resource_type="process", project_id="project",
            run_id=kwargs["run_id"], lane_id=kwargs["lane_id"], creator=kwargs["creator"],
            classification="ephemeral", created_at="2026-01-01T00:00:00+00:00",
            last_activity_at="2026-01-01T00:00:00+00:00",
            expected_cleanup_event="process_exit_or_cancel", retention_required=False, pid=process.pid,
            process_identity="process-start:test",
        )
        self.ledger.records[record.resource_id] = record
        self._processes[record.resource_id] = process
        return record, process

    def terminate_owned_process(self, resource_id):
        record = self.ledger.records[resource_id]
        self.ledger.records[resource_id] = replace(record, active=False, status="reclaimed", run_state="cancelled")
        self._processes.pop(resource_id, None)
        return SimpleNamespace(cleanup_id="cleanup-test", resources_reclaimed=1, errors=())

    def persisted_process_has_exited(self, resource_id, *, expected_pid):
        return not self.ledger.records[resource_id].active

    def complete_persisted_process_after_exit(self, resource_id, *, expected_pid, run_state):
        record = self.ledger.records[resource_id]
        self.ledger.records[resource_id] = replace(record, active=False, status="reclaimed", run_state=run_state.value)


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps(self.payload).encode()


class _Opener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _Response(self.payload)


def _runtime(tmp_path: Path, *, ready=True):
    model_root = tmp_path / "models"
    binary_root = tmp_path / "runtime"
    model_root.mkdir()
    binary_root.mkdir()
    model = model_root / "model.gguf"
    model.write_bytes(_gguf())
    binary = binary_root / "llama-server.exe"
    binary.write_bytes(b"generic-runtime-fixture")
    manager = _Manager()
    runtime = LocalModelRuntime(
        tmp_path, allowed_model_roots=[model_root], allowed_runtime_roots=[binary_root],
        manager=manager, readiness_probe=lambda _origin, _timeout: ready,
    )
    return runtime, manager, model, binary


def test_bounded_gguf_parser_and_admission_are_structured_and_digest_bound(tmp_path: Path) -> None:
    parsed = parse_gguf_metadata(_gguf())
    assert parsed["architecture"] == "llama"
    assert parsed["context_length"] == 4096
    runtime, _manager, model, _binary = _runtime(tmp_path)
    admission = runtime.inspect_model(model)
    assert admission.compatible is True
    assert admission.size_bytes == model.stat().st_size
    assert len(admission.model_sha256) == 64
    foreign = tmp_path / "foreign.gguf"
    foreign.write_bytes(_gguf())
    with pytest.raises(ValueError, match="outside"):
        runtime.inspect_model(foreign)


def test_admission_rejects_malformed_unknown_and_unsupported_models(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="header"):
        parse_gguf_metadata(b"not-a-model")
    runtime, _manager, model, _binary = _runtime(tmp_path)
    model.write_bytes(_gguf(architecture="unknown"))
    admission = runtime.inspect_model(model)
    assert admission.compatible is False
    assert admission.compatibility_reasons == ("architecture_not_supported",)


def test_plan_binds_exact_model_runtime_loopback_and_resource_limits(tmp_path: Path) -> None:
    runtime, _manager, model, binary = _runtime(tmp_path)
    admission = runtime.inspect_model(model)
    plan = runtime.plan_server(admission, binary, port=18080, context_size=2048, gpu_layers=8)
    assert plan.command == (
        str(binary.resolve()), "--model", str(model.resolve()), "--host", "127.0.0.1",
        "--port", "18080", "--ctx-size", "2048", "--n-gpu-layers", "8",
    )
    model.write_bytes(_gguf(context=8192))
    with pytest.raises(ValueError, match="digest is stale"):
        runtime.plan_server(admission, binary, port=18080, context_size=2048)


def test_start_status_reopen_and_unload_are_append_only_and_do_not_delete_model(tmp_path: Path) -> None:
    runtime, manager, model, binary = _runtime(tmp_path)
    plan = runtime.plan_server(runtime.inspect_model(model), binary, port=18080, context_size=2048)
    started = runtime.start(plan)
    assert started["state"] == "running"
    assert runtime.status(started["session_id"])["process_identity"] == "process-start:test"
    reopened = LocalModelRuntime(
        tmp_path, allowed_model_roots=[model.parent], allowed_runtime_roots=[binary.parent],
        manager=manager, readiness_probe=lambda _origin, _timeout: True,
    )
    assert reopened.status(started["session_id"])["state"] == "running"
    with pytest.raises(PermissionError):
        reopened.unload(started["session_id"], supplied_authority=False)
    stopped = runtime.unload(started["session_id"], supplied_authority=True)
    assert stopped["tree_closed"] is True
    assert stopped["model_deleted"] is False
    assert model.is_file()
    assert [json.loads(line)["event_type"] for line in runtime.event_path.read_text(encoding="utf-8").splitlines()] == ["started", "stopped"]


def test_start_failure_closes_owned_process_and_retains_recovery_event(tmp_path: Path) -> None:
    runtime, manager, model, binary = _runtime(tmp_path, ready=False)
    plan = runtime.plan_server(runtime.inspect_model(model), binary, port=18080, context_size=2048)
    with pytest.raises(RuntimeError, match="bounded startup"):
        runtime.start(plan, readiness_timeout_seconds=0.01)
    assert manager.ledger.get("process-test").active is False
    assert json.loads(runtime.event_path.read_text(encoding="utf-8").splitlines()[-1])["event_type"] == "start_failed"


def test_llama_cpp_adapter_is_loopback_digest_bound_and_non_billable() -> None:
    digest = "a" * 64
    opener = _Opener({"choices": [{"message": {"content": "ready"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    adapter = LlamaCppHttpAdapter(
        "http://127.0.0.1:18080", session_id="local-model-session-" + "b" * 32,
        model_sha256=digest, opener=opener,
    )
    response = adapter.invoke(digest, {"messages": [{"role": "user", "content": "ready?"}]})
    assert response.value == "ready"
    assert response.usage == ProviderUsage("local_non_billable", 3, 1, 0)
    request, _timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:18080/v1/chat/completions"
    assert request.headers["X-pacify-local-session"].startswith("local-model-session-")
    with pytest.raises(ValueError, match="admitted digest"):
        adapter.invoke("c" * 64, {"messages": [{"role": "user", "content": "x"}]})
    with pytest.raises(ValueError, match="literal loopback"):
        LlamaCppHttpAdapter("http://localhost:18080", session_id="local-model-session-" + "b" * 32, model_sha256=digest)


def test_llama_cpp_adapter_is_authoritatively_admitted() -> None:
    registry = load_provider_registry(Path(__file__).parents[1])
    record = next(item for item in registry["adapters"] if item["adapter_id"] == "llama-cpp-http")
    assert record == {
        "adapter_id": "llama-cpp-http", "provider_id": "llama.cpp", "mode": "local",
        "implementation": "runtime/provider_gateway.py", "admitted": True,
        "status": "ready", "billing_state": "local_non_billable",
    }


def test_lifecycle_events_are_serialized_and_tampering_fails_closed(tmp_path: Path) -> None:
    runtime, _manager, _model, _binary = _runtime(tmp_path)
    threads = [threading.Thread(target=runtime._append, args=("test", {"index": index})) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    events = runtime._load_events()
    assert [event["sequence"] for event in events] == list(range(1, 9))
    lines = runtime.event_path.read_text(encoding="utf-8").splitlines()
    changed = json.loads(lines[3])
    changed["payload"]["index"] = 99
    lines[3] = json.dumps(changed, sort_keys=True)
    runtime.event_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chain is invalid"):
        runtime._load_events()
