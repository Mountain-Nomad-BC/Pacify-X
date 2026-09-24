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
            return CommandResult(0, json.dumps({"Descriptor":{"digest":digest}}).encode(), b"")
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
