from __future__ import annotations

from pathlib import Path

import pytest

from runtime.model_pool import ModelPool, PoolModelSpec, load_model_resource_policy


ROOT = Path(__file__).parents[1]
SHA = "a" * 64
PROFILE_SHA = "b" * 64


class _Clock:
    def __init__(self, value: float = 10.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _spec(model_id: str, *, residency: str = "warm", idle: int | None = 5, exclusive: str | None = None) -> PoolModelSpec:
    return PoolModelSpec(model_id, f"profile-{model_id}", SHA, PROFILE_SHA, residency, idle, exclusive)


def _pool(specs: tuple[PoolModelSpec, ...], *, states: dict[str, str] | None = None, max_loaded: int = 2, clock: _Clock | None = None):
    states = {} if states is None else states
    events: list[tuple[str, dict[str, object]]] = []

    def load(model_id: str) -> str:
        states[model_id] = "loaded"
        return "loaded"

    def unload(model_id: str) -> str:
        states[model_id] = "unloaded"
        return "unloaded"

    pool = ModelPool(
        specs,
        load_model=load,
        unload_model=unload,
        observe_models=lambda: dict(states),
        event_sink=lambda name, payload: events.append((name, dict(payload))),
        max_loaded_models=max_loaded,
        clock=clock or _Clock(),
    )
    return pool, states, events


def test_resource_policy_locks_operator_and_deep_candidates_without_granting_authority() -> None:
    policy = load_model_resource_policy(ROOT)
    assert policy.models_max == 2
    assert policy.reserved_cpu_cores == 2
    assert policy.control_max_concurrency == 1
    assert policy.preferred_resident_model == "qwen35-4b-operator"
    assert policy.preferred_deep_candidate == "qwen3-30b-a3b-deep"


def test_acquire_load_release_requires_authority_only_for_load_transition() -> None:
    pool, states, events = _pool((_spec("operator", residency="resident", idle=None),))
    with pytest.raises(PermissionError, match="load authority"):
        pool.acquire("operator", owner="task-1", supplied_authority=False)
    lease = pool.acquire("operator", owner="task-1", supplied_authority=True)
    assert states["operator"] == "loaded"
    assert pool.entry("operator").state == "loaded"
    released = pool.release(lease)
    assert released.state == "warm"
    # Once resident and already loaded, ordinary request acquisition does not itself grant/re-require load authority.
    lease2 = pool.acquire("operator", owner="task-2", supplied_authority=False)
    pool.release(lease2)
    assert [name for name, _ in events].count("model_load_requested") == 1


def test_resident_never_idle_evicts_and_warm_model_does() -> None:
    clock = _Clock(10.0)
    pool, states, _events = _pool((
        _spec("operator", residency="resident", idle=None),
        _spec("helper", residency="warm", idle=5),
    ), clock=clock)
    operator = pool.acquire("operator", owner="o", supplied_authority=True)
    helper = pool.acquire("helper", owner="h", supplied_authority=True)
    pool.release(operator)
    pool.release(helper)
    clock.value = 20.0
    assert pool.evict_idle(supplied_authority=True, now=clock.value) == ("helper",)
    assert pool.entry("operator").state == "warm"
    assert pool.entry("helper").state == "unloaded"
    assert states["operator"] == "loaded"


def test_capacity_evicts_idle_warm_before_loading_another_model() -> None:
    clock = _Clock(10.0)
    pool, _states, _events = _pool((_spec("one", idle=0), _spec("two", idle=0)), max_loaded=1, clock=clock)
    first = pool.acquire("one", owner="one-owner", supplied_authority=True)
    pool.release(first)
    clock.value = 11.0
    second = pool.acquire("two", owner="two-owner", supplied_authority=True)
    assert pool.entry("one").state == "unloaded"
    assert pool.entry("two").state == "loaded"
    pool.release(second)


def test_drain_waits_for_active_lease_then_unloads_on_release() -> None:
    pool, states, _events = _pool((_spec("deep", residency="exclusive_cold", idle=30, exclusive="heavy"),))
    lease = pool.acquire("deep", owner="deep-task", supplied_authority=True)
    draining = pool.drain("deep", supplied_authority=True)
    assert draining.state == "draining"
    assert states["deep"] == "loaded"
    done = pool.release(lease)
    assert done.state == "unloaded"
    assert states["deep"] == "unloaded"


def test_exclusive_group_and_unload_with_active_lease_fail_closed() -> None:
    pool, _states, _events = _pool((
        _spec("deep-a", residency="exclusive_cold", idle=30, exclusive="heavy"),
        _spec("deep-b", residency="exclusive_cold", idle=30, exclusive="heavy"),
    ))
    lease = pool.acquire("deep-a", owner="task", supplied_authority=True)
    with pytest.raises(RuntimeError, match="occupied"):
        pool.acquire("deep-b", owner="task", supplied_authority=True)
    with pytest.raises(RuntimeError, match="active leases"):
        pool.unload("deep-a", supplied_authority=True)
    pool.release(lease)


def test_reconcile_marks_router_loss_with_active_lease_failed() -> None:
    pool, states, _events = _pool((_spec("operator", residency="resident", idle=None),))
    lease = pool.acquire("operator", owner="task", supplied_authority=True)
    states["operator"] = "unloaded"
    pool.reconcile()
    assert pool.entry("operator").state == "failed"
    assert "active leases" in (pool.entry("operator").last_error or "")
    released = pool.release(lease)
    assert released.state == "failed"


def test_pool_rejects_bad_clock_and_router_state() -> None:
    clock = _Clock(float("nan"))
    pool, _states, _events = _pool((_spec("operator", residency="resident", idle=None),), clock=clock)
    with pytest.raises(RuntimeError, match="clock"):
        pool.acquire("operator", owner="task", supplied_authority=True)

    states = {"operator": "mystery"}
    pool2, _states2, _events2 = _pool((_spec("operator", residency="resident", idle=None),), states=states)
    pool2.reconcile()
    assert pool2.entry("operator").state == "failed"


def _gguf_bytes(*, name: str) -> bytes:
    import struct

    def string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    architecture = "qwen3"
    values = [
        ("general.architecture", 8, string(architecture)),
        ("general.name", 8, string(name)),
        (f"{architecture}.context_length", 4, struct.pack("<I", 4096)),
        (f"{architecture}.embedding_length", 4, struct.pack("<I", 1024)),
    ]
    return (
        b"GGUF" + struct.pack("<IQQ", 3, 1, len(values))
        + b"".join(string(key) + struct.pack("<I", kind) + value for key, kind, value in values)
        + b"tensor-placeholder"
    )


def _capability_fingerprint(executable: Path, *options: str):
    """A test-only exact fingerprint bound to the fixture executable bytes."""
    from dataclasses import asdict, replace
    from hashlib import sha256
    from runtime import llama_cpp_capabilities as CAP

    fingerprint = CAP.LlamaCppCapabilityFingerprint(
        schema_version=CAP.FINGERPRINT_SCHEMA,
        executable_path=str(executable.resolve()),
        executable_sha256=sha256(executable.read_bytes()).hexdigest(),
        executable_size_bytes=executable.stat().st_size,
        version_text="test",
        version_sha256=sha256(b"test").hexdigest(),
        help_sha256=sha256(b"help").hexdigest(),
        devices_sha256=None,
        supported_options=tuple(sorted(set(options))),
        device_probe_supported=False,
        fingerprint_sha256="",
    )
    return replace(
        fingerprint,
        fingerprint_sha256=CAP._sha({
            **{key: value for key, value in asdict(fingerprint).items()
               if key != "fingerprint_sha256"},
            "supported_options": list(fingerprint.supported_options),
        }),
    )


def _certified_profile(model_id: str, **overrides):
    from runtime.model_profile import ModelRuntimeProfile, _sha

    payload = {
        "schema_version": "px.model-runtime-profile/1.0",
        "profile_id": f"{model_id}-fixture",
        "model_id": model_id,
        "lane": "control",
        "runtime": "llama_cpp_router",
        "state": "certified",
        "residency": "resident",
        "context_tokens": 4096,
        "max_output_tokens": 512,
        "parallel_slots": 1,
        "threads": 2,
        "threads_batch": 2,
        "batch_size": 256,
        "ubatch_size": 64,
        "gpu_layers": 0,
        "cpu_moe_layers": None,
        "flash_attention": False,
        "reasoning": False,
        "prompt_cache": False,
        "text_only": True,
        "idle_evict_seconds": None,
        "exclusive_heavy": False,
        "benchmark_required": False,
        "profile_sha256": "",
    }
    payload.update(overrides)
    payload["profile_sha256"] = _sha(
        {key: value for key, value in payload.items() if key != "profile_sha256"})
    return ModelRuntimeProfile(**payload)


def _preset_declaration(fingerprint, executable, extra_keys=("--host", "--port", "--models-max", "--models-preset", "--no-models-autoload", "--metrics", "--slots", "--no-ui", "--log-jsonl", "--model")):
    from dataclasses import asdict, replace
    from runtime.model_router_preset import RouterPresetFormat, _sha as _preset_sha
    from runtime import llama_cpp_capabilities as CAP

    option_keys = [
        ["--model", "model", ""], ["--ctx-size", "ctx_size", ""],
        ["--cache-type-k", "cache_type_k", ""], ["--threads", "n_threads", ""],
        ["--n-gpu-layers", "n_gpu_layers", ""],
        ["--threads-batch", "n_threads_batch", ""],
        ["--batch-size", "n_batch", ""], ["--ubatch-size", "n_ubatch", ""],
        ["--parallel", "n_parallel", ""], ["--flash-attn", "flash_attn", ""],
    ]
    options = {row[0] for row in option_keys} | set(extra_keys)
    fingerprint = replace(fingerprint, supported_options=tuple(sorted(options)))
    fingerprint = replace(
        fingerprint,
        fingerprint_sha256=CAP._sha({
            **{key: value for key, value in asdict(fingerprint).items()
               if key != "fingerprint_sha256"},
            "supported_options": list(fingerprint.supported_options),
        }),
    )
    declaration = RouterPresetFormat(
        schema_version="px.model-router-preset-format/1.0",
        executable_sha256=fingerprint.executable_sha256,
        capability_fingerprint_sha256=fingerprint.fingerprint_sha256,
        format_evidence_sha256="c" * 64,
        section_prefix="model-",
        section_suffix="",
        option_keys=tuple(tuple(row) for row in option_keys),
        declaration_sha256="",
    )
    return replace(declaration, declaration_sha256=_preset_sha(declaration.identity_payload())), fingerprint


def test_router_pool_plan_is_loopback_no_autoload_and_exact_file_bound(tmp_path: Path) -> None:
    from runtime.local_model_runtime import LocalModelRuntime

    model_root = tmp_path / "models"
    runtime_root = tmp_path / "runtime"
    config_root = tmp_path / "config"
    for path in (model_root, runtime_root, config_root):
        path.mkdir()
    one = model_root / "operator.gguf"
    two = model_root / "deep.gguf"
    one.write_bytes(_gguf_bytes(name="operator"))
    two.write_bytes(_gguf_bytes(name="deep"))
    executable = runtime_root / "llama-server"
    executable.write_bytes(b"runtime")
    preset = config_root / "models.ini"
    preset.write_text("[models]\n", encoding="utf-8")
    runtime = LocalModelRuntime(
        tmp_path,
        allowed_model_roots=[model_root],
        allowed_runtime_roots=[runtime_root],
        allowed_config_roots=[config_root],
    )
    fingerprint = _capability_fingerprint(
        executable,
        "--batch-size", "--ctx-size", "--flash-attn", "--host", "--log-jsonl",
        "--metrics", "--model", "--models-max", "--models-preset",
        "--n-gpu-layers", "--no-models-autoload", "--no-ui", "--parallel",
        "--port", "--slots", "--threads", "--threads-batch", "--ubatch-size",
    )
    profiles = {
        model_id: _certified_profile(model_id)
        for model_id in ("qwen35-4b-operator", "qwen3-30b-a3b-deep")
    }
    declarations, fingerprint = _preset_declaration(fingerprint, executable)
    models_map = {
        "qwen35-4b-operator": runtime.inspect_model(one),
        "qwen3-30b-a3b-deep": runtime.inspect_model(two),
    }
    from runtime.model_router_preset import render_model_router_preset
    rendered, _binding = render_model_router_preset(
        models_map, profiles, fingerprint, declarations,
        verify_format=lambda _decl, _fp: None)
    preset.write_bytes(rendered)
    plan = runtime.plan_router_pool(
        models_map,
        executable,
        preset,
        port=18080,
        models_max=2,
        profiles=profiles,
        capability_fingerprint=fingerprint,
        preset_format=declarations,
        verify_preset_format=lambda _decl, _fp: None,
    )
    assert plan.command == (
        str(executable.resolve()), "--host", "127.0.0.1", "--port", "18080",
        "--models-preset", str(preset.resolve()), "--models-max", "2",
        "--no-models-autoload", "--metrics", "--slots", "--no-ui", "--log-jsonl",
    )
    preset.write_text("[models]\nchanged=true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="preset changed"):
        runtime.start(plan, readiness_timeout_seconds=0.01)


def test_router_timeout_and_unplanned_router_models_fail_before_side_effect(tmp_path: Path) -> None:
    from dataclasses import replace
    from types import SimpleNamespace

    from runtime.local_model_runtime import LocalModelRuntime
    from runtime.resource_lifecycle import ResourceRecord

    model_root = tmp_path / "models"
    runtime_root = tmp_path / "runtime"
    config_root = tmp_path / "config"
    for path in (model_root, runtime_root, config_root):
        path.mkdir()
    model = model_root / "operator.gguf"
    model.write_bytes(_gguf_bytes(name="operator"))
    executable = runtime_root / "llama-server"
    executable.write_bytes(b"runtime")
    preset = config_root / "models.ini"
    preset.write_text("[models]\n", encoding="utf-8")

    class Ledger:
        def __init__(self) -> None:
            self.records: dict[str, ResourceRecord] = {}
        def get(self, resource_id: str) -> ResourceRecord:
            return self.records[resource_id]

    class Process:
        pid = 9876
        def poll(self):
            return None

    class Manager:
        def __init__(self) -> None:
            self.ledger = Ledger()
            self._processes: dict[str, Process] = {}
        def spawn_owned_process(self, command, **kwargs):
            process = Process()
            record = ResourceRecord(
                resource_id="router-process", resource_type="process", project_id="project",
                run_id=kwargs["run_id"], lane_id=kwargs["lane_id"], creator=kwargs["creator"],
                classification="ephemeral", created_at="2026-09-20T00:00:00+00:00",
                last_activity_at="2026-09-20T00:00:00+00:00",
                expected_cleanup_event="process_exit_or_cancel", retention_required=False,
                pid=process.pid, process_identity="process-start:router",
            )
            self.ledger.records[record.resource_id] = record
            self._processes[record.resource_id] = process
            return record, process
        def terminate_owned_process(self, resource_id):
            record = self.ledger.records[resource_id]
            self.ledger.records[resource_id] = replace(record, active=False, status="reclaimed", run_state="cancelled")
            self._processes.pop(resource_id, None)
            return SimpleNamespace(cleanup_id="cleanup", resources_reclaimed=1, errors=())
        def settle_failed_launch(self, resource_id, error):
            self.terminate_owned_process(resource_id)

    calls: list[tuple[str, str, object, float]] = []
    router_rows = [{"id": "qwen35-4b-operator", "status": {"value": "unloaded"}}]

    def request(method: str, url: str, payload, timeout: float):
        calls.append((method, url, payload, timeout))
        if method == "GET":
            return {"data": list(router_rows)}
        if url.endswith("/models/load"):
            router_rows[0] = {"id": "qwen35-4b-operator", "status": {"value": "loaded"}}
            return {}
        if url.endswith("/models/unload"):
            router_rows[0] = {"id": "qwen35-4b-operator", "status": {"value": "unloaded"}}
            return {}
        raise AssertionError(url)

    runtime = LocalModelRuntime(
        tmp_path,
        allowed_model_roots=[model_root],
        allowed_runtime_roots=[runtime_root],
        allowed_config_roots=[config_root],
        manager=Manager(),
        readiness_probe=lambda _origin, _timeout: True,
        router_request=request,
    )
    fingerprint = _capability_fingerprint(
        executable,
        "--batch-size", "--ctx-size", "--flash-attn", "--host", "--log-jsonl",
        "--metrics", "--model", "--models-max", "--models-preset",
        "--n-gpu-layers", "--no-models-autoload", "--no-ui", "--parallel",
        "--port", "--slots", "--threads", "--threads-batch", "--ubatch-size",
    )
    declaration, fingerprint = _preset_declaration(fingerprint, executable)
    profile = _certified_profile("qwen35-4b-operator")
    admission = runtime.inspect_model(model)
    from runtime.model_router_preset import render_model_router_preset
    rendered, _binding = render_model_router_preset(
        {"qwen35-4b-operator": admission}, {"qwen35-4b-operator": profile},
        fingerprint, declaration, verify_format=lambda _decl, _fp: None)
    preset.write_bytes(rendered)
    plan = runtime.plan_router_pool(
        {"qwen35-4b-operator": admission}, executable, preset, port=18081, models_max=1,
        profiles={"qwen35-4b-operator": profile}, capability_fingerprint=fingerprint,
        preset_format=declaration, verify_preset_format=lambda _decl, _fp: None)
    started = runtime.start(plan)
    before = len(calls)
    with pytest.raises(ValueError, match="router timeout"):
        runtime.load_router_model(started["session_id"], "qwen35-4b-operator", supplied_authority=True, timeout_seconds=float("nan"))
    assert len(calls) == before

    assert runtime.load_router_model(started["session_id"], "qwen35-4b-operator", supplied_authority=True, timeout_seconds=1.0) == "loaded"
    assert runtime.status(started["session_id"])["state"] == "running"
    profile = _certified_profile("qwen35-4b-operator")
    child_pool = runtime.open_model_pool(started["session_id"], {profile.model_id: profile})
    child_pool.reconcile()
    lease = child_pool.acquire(profile.model_id, owner="operator-query", supplied_authority=False)
    child_pool.release(lease)
    assert runtime.status(started["session_id"])["state"] == "running"
    router_rows.append({"id": "unplanned-model", "status": {"value": "loaded"}})
    with pytest.raises(ValueError, match="outside the admitted router plan"):
        runtime.router_model_states(started["session_id"])


def test_failed_unknown_router_state_consumes_capacity_until_reconciled() -> None:
    states = {"one": "unloaded", "two": "unloaded"}
    loads: list[str] = []

    def load(model_id: str) -> str:
        loads.append(model_id)
        if model_id == "one":
            states[model_id] = "loaded"
            return "mystery"
        states[model_id] = "loaded"
        return "loaded"

    pool = ModelPool(
        (_spec("one", idle=0), _spec("two", idle=0)),
        load_model=load,
        unload_model=lambda model_id: states.__setitem__(model_id, "unloaded") or "unloaded",
        observe_models=lambda: dict(states),
        max_loaded_models=1,
        clock=_Clock(),
    )
    with pytest.raises(RuntimeError, match="non-loaded state"):
        pool.ensure_loaded("one", supplied_authority=True)
    assert pool.entry("one").state == "failed"
    with pytest.raises(RuntimeError, match="capacity is exhausted"):
        pool.ensure_loaded("two", supplied_authority=True)
    assert loads == ["one"]
    # Reconciliation proves the first model is actually loaded and clears the failed marker.
    pool.reconcile()
    assert pool.entry("one").state == "warm"


def test_router_pool_plan_binds_certified_profiles_through_a_commissioned_preset_format(tmp_path: Path) -> None:
    """P4d: the per-model profile/placement contract is closed and enforced.

    ``plan_router_pool`` requires an exact typed fingerprint, frozen certified
    profiles and a commissioned format declaration; the on-disk preset must
    match the rendered bytes exactly, and a changed profile or preset fails
    closed before any process effect.
    """
    from hashlib import sha256
    from dataclasses import asdict, replace

    from runtime import llama_cpp_capabilities as CAP
    from runtime.local_model_runtime import LocalModelRuntime
    from runtime.model_profile import (
        load_runtime_profiles, runtime_profile_from_mapping)
    from runtime.model_router_preset import (
        router_preset_format_from_mapping, render_model_router_preset)

    model_root = tmp_path / "models"
    runtime_root = tmp_path / "runtime"
    config_root = tmp_path / "config"
    for path in (model_root, runtime_root, config_root):
        path.mkdir()
    model = model_root / "operator.gguf"
    model.write_bytes(_gguf_bytes(name="operator"))
    executable = runtime_root / "llama-server"
    executable.write_bytes(b"runtime")
    preset = config_root / "models.ini"

    runtime = LocalModelRuntime(
        tmp_path,
        allowed_model_roots=[model_root],
        allowed_runtime_roots=[runtime_root],
        allowed_config_roots=[config_root],
    )
    admission = runtime.inspect_model(model)

    fingerprint = CAP.LlamaCppCapabilityFingerprint(
        schema_version=CAP.FINGERPRINT_SCHEMA,
        executable_path=str(executable.resolve()),
        executable_sha256=sha256(executable.read_bytes()).hexdigest(),
        executable_size_bytes=executable.stat().st_size,
        version_text="test",
        version_sha256=sha256(b"test").hexdigest(),
        help_sha256=sha256(b"help").hexdigest(),
        devices_sha256=None,
        supported_options=("--batch-size", "--cache-type-k", "--ctx-size", "--flash-attn", "--host", "--log-jsonl", "--metrics", "--model", "--models-max", "--models-preset", "--n-gpu-layers", "--no-models-autoload", "--no-ui", "--parallel", "--port", "--slots", "--threads", "--threads-batch", "--ubatch-size"),
        device_probe_supported=False,
        fingerprint_sha256="",
    )
    fingerprint = replace(
        fingerprint,
        fingerprint_sha256=CAP._sha({
            **{key: value for key, value in asdict(fingerprint).items()
               if key != "fingerprint_sha256"},
            "supported_options": list(fingerprint.supported_options),
        }),
    )

    from runtime.model_profile import ModelRuntimeProfile, _sha
    profile_payload = {
        "schema_version": "px.model-runtime-profile/1.0",
        "profile_id": "preset-fixture",
        "model_id": "preset-fixture-model",
        "lane": "control",
        "runtime": "llama_cpp_router",
        "state": "certified",
        "residency": "resident",
        "context_tokens": 4096,
        "max_output_tokens": 512,
        "parallel_slots": 1,
        "threads": 2,
        "threads_batch": 2,
        "batch_size": 256,
        "ubatch_size": 64,
        "gpu_layers": 0,
        "cpu_moe_layers": None,
        "flash_attention": False,
        "reasoning": False,
        "prompt_cache": False,
        "text_only": True,
        "idle_evict_seconds": None,
        "exclusive_heavy": False,
        "benchmark_required": False,
        "profile_sha256": "",
    }
    profile_payload["profile_sha256"] = _sha(
        {key: value for key, value in profile_payload.items() if key != "profile_sha256"})
    profile = ModelRuntimeProfile(**profile_payload)
    profiles = {profile.model_id: profile}

    declaration = router_preset_format_from_mapping({
        "schema_version": "px.model-router-preset-format/1.0",
        "executable_sha256": fingerprint.executable_sha256,
        "capability_fingerprint_sha256": fingerprint.fingerprint_sha256,
        "format_evidence_sha256": "c" * 64,
        "section_prefix": "model-",
        "section_suffix": "",
        "option_keys": [["--model", "model", ""], ["--ctx-size", "ctx_size", ""], ["--cache-type-k", "cache_type_k", ""], ["--threads", "n_threads", ""], ["--n-gpu-layers", "n_gpu_layers", ""], ["--threads-batch", "n_threads_batch", ""], ["--batch-size", "n_batch", ""], ["--ubatch-size", "n_ubatch", ""], ["--parallel", "n_parallel", ""], ["--flash-attn", "flash_attn", ""]],
        "declaration_sha256": "",
    })
    from runtime.model_router_preset import _sha as _preset_sha
    declaration = replace(declaration, declaration_sha256=_preset_sha(declaration.identity_payload()))
    expected_bytes, binding = render_model_router_preset(
        {profile.model_id: admission}, profiles, fingerprint, declaration,
        verify_format=lambda _decl, _fp: None)
    preset.write_bytes(expected_bytes)

    plan = runtime.plan_router_pool(
        {profile.model_id: admission},
        executable,
        preset,
        port=18080,
        models_max=1,
        profiles=profiles,
        capability_fingerprint=fingerprint,
        preset_format=declaration,
        verify_preset_format=lambda _decl, _fp: None,
    )
    assert plan.preset_binding["binding_sha256"] == binding.binding_sha256

    # Any deviation between the admitted preset bytes and the exact rendered
    # binding fails closed before side effects.
    preset.write_bytes(expected_bytes + b"\n")
    with pytest.raises(ValueError, match="preset bytes do not match"):
        runtime.plan_router_pool(
            {profile.model_id: admission},
            executable,
            preset,
            port=18080,
            models_max=1,
            profiles=profiles,
            capability_fingerprint=fingerprint,
            preset_format=declaration,
            verify_preset_format=lambda _decl, _fp: None,
        )
