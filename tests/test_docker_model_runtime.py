from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import pytest

from runtime.docker_model_runtime import CommandResult, DockerModelRuntime
from runtime.model_resource_interlock import ModelResourceInterlock, ModelResourceNeed, load_external_runtime_policy
from runtime.provider_gateway import ColdRuntimeHttpAdapter, ProviderUsage

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "a" * 64


def _enabled_policy():
    base = load_external_runtime_policy(ROOT)
    body = replace(base, globally_enabled=True, docker_enabled=True, policy_sha256="")
    from dataclasses import asdict
    import hashlib
    raw = asdict(body); raw.pop("policy_sha256")
    sha = hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return replace(body, policy_sha256=sha)


class Runner:
    def __init__(self, *, fail_prewarm=False, bad_digest=False):
        self.calls=[]; self.fail_prewarm=fail_prewarm; self.bad_digest=bad_digest
    def __call__(self, argv, timeout):
        self.calls.append((tuple(argv), timeout))
        if argv[2] == "inspect":
            digest = "sha256:" + ("b" if self.bad_digest else "a") * 64
            return CommandResult(0, json.dumps({"id": digest, "tags": [argv[3]],
                                               "created": 0, "config": {"format": "gguf"}}).encode(), b"")
        if argv[2] == "run" and self.fail_prewarm:
            return CommandResult(7,b"",b"failed")
        return CommandResult(0,b"ok",b"")


def test_production_policy_blocks_docker_before_side_effects() -> None:
    runner=Runner(); rt=DockerModelRuntime(ROOT, interlock=ModelResourceInterlock(max_ram_commit_bytes=1,max_vram_commit_bytes=1), command_runner=runner)
    plan=rt.plan(model_id="deep", model_ref="ai/deep", oci_digest=DIGEST)
    with pytest.raises(PermissionError, match="disabled"):
        rt.prewarm(plan, ModelResourceNeed("docker_model_runner",0,0,False,False), supplied_authority=True)
    assert runner.calls == []


def test_cached_identity_prewarm_and_unload_hold_one_exact_lease() -> None:
    runner=Runner(); lock=ModelResourceInterlock(max_ram_commit_bytes=1000,max_vram_commit_bytes=1000)
    rt=DockerModelRuntime(ROOT, interlock=lock, policy=_enabled_policy(), command_runner=runner)
    plan=rt.plan(model_id="deep",model_ref="ai/deep",oci_digest=DIGEST)
    receipt=rt.prewarm(plan,ModelResourceNeed("docker_model_runner",500,500,True,True),supplied_authority=True)
    assert receipt["oci_digest"] == DIGEST and receipt["routing_authority"] is False
    assert len(lock.snapshot()["leases"]) == 1
    rt.unload(plan,supplied_authority=True)
    assert lock.snapshot()["leases"] == []
    assert [c[0][:3] for c in runner.calls] == [("docker","model","inspect"),("docker","model","run"),("docker","model","unload")]


def test_digest_mismatch_and_failed_prewarm_fail_closed_without_leak() -> None:
    lock=ModelResourceInterlock(max_ram_commit_bytes=100,max_vram_commit_bytes=100)
    bad=DockerModelRuntime(ROOT,interlock=lock,policy=_enabled_policy(),command_runner=Runner(bad_digest=True))
    plan=bad.plan(model_id="m",model_ref="ai/m",oci_digest=DIGEST)
    with pytest.raises(ValueError,match="OCI digest"):
        bad.prewarm(plan,ModelResourceNeed("docker_model_runner",1,1,False,True),supplied_authority=True)
    assert lock.snapshot()["leases"] == []
    runner=Runner(fail_prewarm=True); rt=DockerModelRuntime(ROOT,interlock=lock,policy=_enabled_policy(),command_runner=runner)
    plan=rt.plan(model_id="m",model_ref="ai/m",oci_digest=DIGEST)
    with pytest.raises(RuntimeError,match="prewarm"):
        rt.prewarm(plan,ModelResourceNeed("docker_model_runner",1,1,False,True),supplied_authority=True)
    assert lock.snapshot()["leases"] == []
    assert runner.calls[-1][0][:3] == ("docker","model","unload")


@pytest.mark.parametrize("mutation", ["annotation-only", "legacy-descriptor", "conflicting-field",
                                    "missing-tags", "wrong-reference", "duplicate-tags",
                                    "invalid-created", "invalid-config", "multiple-models"])
def test_inspect_requires_one_exact_manifest_identity_and_reference(mutation):
    payload = {"id": DIGEST, "tags": ["ai/m"], "created": 0, "config": {"format": "gguf"}}
    if mutation == "annotation-only":
        payload["id"] = "sha256:" + "b" * 64
        payload["config"]["unrelated_digest"] = DIGEST
    elif mutation == "legacy-descriptor":
        payload = {"Descriptor": {"digest": DIGEST}}
    elif mutation == "conflicting-field":
        payload["Descriptor"] = {"digest": "sha256:" + "b" * 64}
    elif mutation == "missing-tags":
        payload.pop("tags")
    elif mutation == "wrong-reference":
        payload["tags"] = ["ai/different"]
    elif mutation == "duplicate-tags":
        payload["tags"] = ["ai/m", "ai/m"]
    elif mutation == "invalid-created":
        payload["created"] = True
    elif mutation == "invalid-config":
        payload["config"] = []
    else:
        payload = [payload, payload]
    runner = lambda argv, timeout: CommandResult(0, json.dumps(payload).encode(), b"")
    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    with pytest.raises(ValueError):
        runtime.verify_cached(plan)
    assert interlock.snapshot()["leases"] == []


def test_inspect_duplicate_identity_keys_are_not_last_writer_wins():
    raw = ('{"id":"sha256:' + 'b' * 64 + '","id":"' + DIGEST
           + '","tags":["ai/m"],"created":0,"config":{}}').encode()
    runtime = DockerModelRuntime(ROOT, interlock=ModelResourceInterlock(max_ram_commit_bytes=1,
                                max_vram_commit_bytes=1), policy=_enabled_policy(),
                                command_runner=lambda argv, timeout: CommandResult(0, raw, b""))
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    with pytest.raises(ValueError):
        runtime.verify_cached(plan)


def test_valid_inspect_binds_only_model_manifest_id_and_tolerates_unrelated_config_digest():
    payload = {"id": DIGEST, "tags": ["ai/m"], "created": 0,
               "config": {"unrelated_digest": "sha256:" + "b" * 64}}
    runtime = DockerModelRuntime(ROOT, interlock=ModelResourceInterlock(max_ram_commit_bytes=1,
                                max_vram_commit_bytes=1), policy=_enabled_policy(),
                                command_runner=lambda argv, timeout: CommandResult(0, json.dumps(payload).encode(), b""))
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    assert runtime.verify_cached(plan)["oci_digest"] == DIGEST


def test_digest_qualified_model_reference_cannot_contradict_planned_manifest():
    runtime = DockerModelRuntime(ROOT, interlock=ModelResourceInterlock(max_ram_commit_bytes=1,
                                max_vram_commit_bytes=1), policy=_enabled_policy(), command_runner=Runner())
    with pytest.raises(ValueError, match="reference.*digest|digest.*reference"):
        runtime.plan(model_id="m", model_ref="ai/m@sha256:" + "b" * 64, oci_digest=DIGEST)


def test_exact_immutable_reference_can_inspect_an_untagged_local_model():
    payload = {"id": DIGEST, "created": 0, "config": {"format": "gguf"}}
    runtime = DockerModelRuntime(ROOT, interlock=ModelResourceInterlock(max_ram_commit_bytes=1,
                                max_vram_commit_bytes=1), policy=_enabled_policy(),
                                command_runner=lambda argv, timeout: CommandResult(0, json.dumps(payload).encode(), b""))
    plan = runtime.plan(model_id="m", model_ref="ai/m@" + DIGEST, oci_digest=DIGEST)
    assert runtime.verify_cached(plan)["oci_digest"] == DIGEST


@pytest.mark.parametrize("timeout", [-1, 0, True, float("nan"), float("inf"), "1"])
def test_invalid_prewarm_timeout_has_no_command_or_resource_effect(timeout):
    runner = Runner()
    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    with pytest.raises(ValueError, match="timeout"):
        runtime.prewarm(plan, ModelResourceNeed("docker_model_runner", 1, 0, False, False),
                        supplied_authority=True, timeout_seconds=timeout)
    assert interlock.snapshot()["leases"] == []
    assert runtime._leases == {}
    assert runner.calls == []


def test_identical_prewarm_reserves_one_plan_before_cache_io():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()
    ordinary = Runner()
    calls = 0
    gate = threading.Lock()

    def runner(argv, timeout):
        nonlocal calls
        if argv[2] == "inspect":
            with gate:
                calls += 1
                first = calls == 1
            if first:
                entered.set()
                assert release.wait(5), "test did not release first cache inspection"
        return ordinary(argv, timeout)

    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    need = ModelResourceNeed("docker_model_runner", 1, 0, False, False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.prewarm, plan, need, supplied_authority=True)
        try:
            assert entered.wait(5)
            second = pool.submit(runtime.prewarm, plan, need, supplied_authority=True)
            with pytest.raises(ValueError, match="holding|progress|pending"):
                second.result(timeout=5)
        finally:
            release.set()
        receipt = first.result(timeout=5)
    assert calls == 1
    leases = interlock.snapshot()["leases"]
    assert len(leases) == len(runtime._leases) == 1
    assert leases[0]["lease_id"] == receipt["resource_lease_id"]
    runtime.unload(plan, supplied_authority=True)
    assert interlock.snapshot()["leases"] == []


def test_failed_cache_inspection_releases_single_flight_reservation():
    runner = Runner(bad_digest=True)
    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    need = ModelResourceNeed("docker_model_runner", 1, 0, False, False)
    with pytest.raises(ValueError, match="OCI digest"):
        runtime.prewarm(plan, need, supplied_authority=True)
    assert interlock.snapshot()["leases"] == []
    runner.bad_digest = False
    runtime.prewarm(plan, need, supplied_authority=True)
    runtime.unload(plan, supplied_authority=True)
    assert interlock.snapshot()["leases"] == []


def test_failed_prewarm_cleanup_retains_exact_lease_until_successful_unload():
    ordinary = Runner(fail_prewarm=True)
    fail_unload = True

    def runner(argv, timeout):
        if argv[2] == "unload" and fail_unload:
            return CommandResult(7, b"", b"unconfirmed cleanup")
        return ordinary(argv, timeout)

    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    need = ModelResourceNeed("docker_model_runner", 1, 0, False, False)
    with pytest.raises(RuntimeError, match="prewarm"):
        runtime.prewarm(plan, need, supplied_authority=True)
    lease = interlock.snapshot()["leases"][0]["lease_id"]
    assert runtime._leases[plan.plan_sha256].lease_id == lease
    with pytest.raises(ValueError, match="holding"):
        runtime.prewarm(plan, need, supplied_authority=True)
    with pytest.raises(RuntimeError, match="retained"):
        runtime.unload(plan, supplied_authority=True)
    assert interlock.snapshot()["leases"][0]["lease_id"] == lease
    fail_unload = False
    assert runtime.unload(plan, supplied_authority=True)["resource_lease_id"] == lease
    assert interlock.snapshot()["leases"] == []


@pytest.mark.parametrize("operation", ["prewarm", "unload"])
def test_unload_refuses_overlap_with_a_pending_lifecycle_operation(operation):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()
    ordinary = Runner()
    held_command = "run" if operation == "prewarm" else "unload"
    block = False

    def runner(argv, timeout):
        if block and argv[2] == held_command:
            entered.set()
            assert release.wait(5)
        return ordinary(argv, timeout)

    interlock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100)
    runtime = DockerModelRuntime(ROOT, interlock=interlock, policy=_enabled_policy(), command_runner=runner)
    plan = runtime.plan(model_id="m", model_ref="ai/m", oci_digest=DIGEST)
    need = ModelResourceNeed("docker_model_runner", 1, 0, False, False)
    if operation == "unload":
        runtime.prewarm(plan, need, supplied_authority=True)
    block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = (pool.submit(runtime.prewarm, plan, need, supplied_authority=True)
                 if operation == "prewarm" else pool.submit(runtime.unload, plan, supplied_authority=True))
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match="progress"):
                runtime.unload(plan, supplied_authority=True)
        finally:
            release.set()
        first.result(timeout=5)
    block = False
    if operation == "prewarm":
        runtime.unload(plan, supplied_authority=True)
    assert interlock.snapshot()["leases"] == []


def test_operator_pull_is_separate_from_request_path_and_requires_authority() -> None:
    runner=Runner(); rt=DockerModelRuntime(ROOT,interlock=ModelResourceInterlock(max_ram_commit_bytes=1,max_vram_commit_bytes=1),policy=_enabled_policy(),command_runner=runner)
    plan=rt.plan(model_id="m",model_ref="ai/m",oci_digest=DIGEST)
    with pytest.raises(PermissionError): rt.pull_for_operator_preparation(plan,supplied_authority=False)
    receipt=rt.pull_for_operator_preparation(plan,supplied_authority=True)
    assert receipt["normal_request_path"] is False
    assert runner.calls[-1][0] == ("docker","model","pull","ai/m")


class _Response:
    def __init__(self, value): self.body=json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self,*a): return None
    def read(self,n): return self.body[:n]
class _Opener:
    def __init__(self): self.requests=[]
    def open(self, req, timeout):
        self.requests.append((req,timeout)); return _Response({"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":2,"completion_tokens":1}})


def test_cold_http_adapter_binds_exact_runtime_receipt_and_loopback() -> None:
    opener=_Opener(); adapter=ColdRuntimeHttpAdapter("docker-model-runner-http","http://127.0.0.1:12434",endpoint_path="/engines/v1/chat/completions",session_id="dmr-session-1",model_identity="ai/deep",runtime_receipt_sha256="c"*64,opener=opener)
    result=adapter.invoke("ai/deep",{"messages":[{"role":"user","content":"x"}]})
    assert result.value == "ok" and result.usage == ProviderUsage("local_non_billable",2,1,0)
    req,_=opener.requests[0]
    assert req.headers["X-pacify-cold-runtime-receipt"] == "c"*64
    with pytest.raises(ValueError,match="lifecycle identity"): adapter.invoke("other",{"messages":[{}]})
    with pytest.raises(ValueError,match="loopback"): ColdRuntimeHttpAdapter("airllm-http","http://localhost:9999",endpoint_path="/v1/chat/completions",session_id="s",model_identity="m",runtime_receipt_sha256="d"*64)
