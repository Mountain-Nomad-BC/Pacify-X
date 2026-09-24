from __future__ import annotations
from dataclasses import asdict, replace
import hashlib, json, os
from pathlib import Path
import sys, time
import pytest

from runtime.airllm_runtime import AirLlmRuntime
from runtime.model_resource_interlock import ModelResourceInterlock, ModelResourceNeed, load_external_runtime_policy
from runtime.resource_lifecycle import ResourceManager

ROOT=Path(__file__).resolve().parents[1]


def _enabled_policy():
    base=load_external_runtime_policy(ROOT)
    body=replace(base, globally_enabled=True, airllm_enabled=True, policy_sha256="")
    raw=asdict(body); raw.pop("policy_sha256")
    sha=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return replace(body,policy_sha256=sha)


def _fixture(tmp_path: Path, *, compression="none", prefetching=True, ready=True):
    prepared=tmp_path/'prepared'; prepared.mkdir()
    manifest=prepared/'prepared-manifest.json'
    payload={"schema_version":"px.airllm-prepared-model/1.0","model_id":"qwen-deep","source_revision":"rev-1","prepared_root":str(prepared),"prepared_set_sha256":"a"*64,"compression":compression,"prefetching":prefetching,"disk_bytes":1234}
    raw=json.dumps(payload,sort_keys=True).encode(); manifest.write_bytes(raw); manifest_sha=hashlib.sha256(raw).hexdigest()
    runtime_root=tmp_path/'runtime'; runtime_root.mkdir()
    fake_python=Path(sys.executable)
    worker=runtime_root/'worker.py'; worker.write_text('import time\ntime.sleep(60)\n', encoding='utf-8')
    manager=ResourceManager(tmp_path/'state'/'ledger.json',receipt_dir=tmp_path/'state'/'receipts')
    lock=ModelResourceInterlock(max_ram_commit_bytes=10000,max_vram_commit_bytes=10000)
    rt=AirLlmRuntime(tmp_path,manager=manager,interlock=lock,allowed_prepared_roots=[prepared],allowed_runtime_roots=[runtime_root, Path(sys.executable).resolve().parent],policy=_enabled_policy(),readiness_probe=lambda _o,_t: ready)
    model=rt.load_prepared_model(manifest,expected_manifest_sha256=manifest_sha)
    plan=rt.plan_worker(model,python_path=fake_python,worker_script=worker,port=19090,max_seq_len=2048)
    return rt,manager,lock,manifest,manifest_sha,plan


def test_prepared_manifest_and_worker_plan_are_exactly_bound(tmp_path: Path) -> None:
    rt,_manager,_lock,manifest,sha,plan=_fixture(tmp_path)
    assert plan.prepared_model.manifest_sha256 == sha
    assert len(plan.python_sha256)==64 and len(plan.worker_sha256)==64 and len(plan.plan_sha256)==64
    manifest.write_text('{}')
    with pytest.raises(ValueError,match="manifest digest"): rt.load_prepared_model(manifest,expected_manifest_sha256=sha)


def test_compression_and_prefetching_are_distinct_incompatible_identities(tmp_path: Path) -> None:
    with pytest.raises(ValueError,match="compression and prefetching"):
        _fixture(tmp_path,compression="4bit",prefetching=True)


def test_start_stop_is_single_concurrency_supervised_and_releases_resources(tmp_path: Path) -> None:
    rt,manager,lock,_manifest,_sha,plan=_fixture(tmp_path)
    receipt=rt.start(plan,ModelResourceNeed("airllm",100,100,True,True),supplied_authority=True,readiness_timeout_seconds=1)
    assert receipt["routing_authority"] is False and len(lock.snapshot()["leases"])==1
    with pytest.raises(RuntimeError,match="one active"): rt.start(plan,ModelResourceNeed("airllm",1,1,False,True),supplied_authority=True,readiness_timeout_seconds=1)
    stopped=rt.stop(receipt["session_id"],supplied_authority=True)
    assert stopped["operation"] == "stop" and lock.snapshot()["leases"] == []
    assert manager.ledger.get(receipt["resource_id"]).active is False


def test_startup_failure_cleans_worker_and_interlock(tmp_path: Path) -> None:
    rt,manager,lock,_manifest,_sha,plan=_fixture(tmp_path,ready=False)
    with pytest.raises(RuntimeError,match="did not become ready"):
        rt.start(plan,ModelResourceNeed("airllm",100,100,True,True),supplied_authority=True,readiness_timeout_seconds=0.2)
    assert lock.snapshot()["leases"] == []
    records=manager.ledger.load(); assert len(records)==1 and records[0].active is False


def test_production_policy_disables_airllm_before_process_creation(tmp_path: Path) -> None:
    prepared=tmp_path/'p'; prepared.mkdir(); runtime=tmp_path/'r'; runtime.mkdir()
    manager=ResourceManager(tmp_path/'s'/'ledger.json')
    rt=AirLlmRuntime(ROOT,manager=manager,interlock=ModelResourceInterlock(max_ram_commit_bytes=1,max_vram_commit_bytes=1),allowed_prepared_roots=[prepared],allowed_runtime_roots=[runtime])
    # The policy denial is independent of plan content and occurs first.
    with pytest.raises(PermissionError,match="disabled"):
        rt.start(object(),ModelResourceNeed("airllm",0,0,False,False),supplied_authority=True)  # type: ignore[arg-type]
    assert manager.ledger.load() == ()


def test_resource_manager_reconciles_exited_cold_worker_without_guessing(tmp_path: Path) -> None:
    manager=ResourceManager(tmp_path/'state'/'ledger.json')
    record,process=manager.spawn_owned_process([sys.executable,'-c','pass'],cwd=tmp_path,project_id='p',run_id='r',lane_id='cold',creator='test')
    process.wait(timeout=5)
    observed=manager.reconcile_cold_worker(record.resource_id,expected_pid=process.pid,apply=False)
    assert observed["state"] == "exited_pending_close" and observed["tree_absent"] is True
    applied=manager.reconcile_cold_worker(record.resource_id,expected_pid=process.pid,apply=True)
    assert applied["state"] == "closed" and manager.ledger.get(record.resource_id).active is False

def test_worker_start_rechecks_prepared_manifest_identity(tmp_path: Path) -> None:
    rt,_manager,lock,manifest,_sha,plan=_fixture(tmp_path)
    manifest.write_text('{"tampered":true}')
    with pytest.raises(ValueError,match="changed after planning"):
        rt.start(plan,ModelResourceNeed("airllm",1,1,False,True),supplied_authority=True,readiness_timeout_seconds=1)
    assert lock.snapshot()["leases"] == []


def test_airllm_benchmark_reducer_is_deterministic_and_never_promotes(tmp_path: Path) -> None:
    import subprocess
    inp=tmp_path/'cases.json'; a=tmp_path/'a.json'; b=tmp_path/'b.json'
    payload={
      "schema_version":"px.airllm-benchmark-input/1.0","model_id":"m","source_revision":"r","prepared_set_sha256":"e"*64,
      "cases":[
        {"compression":"none","prefetching":True,"success":True,"cold_start_seconds":4.0,"total_seconds":10.0,"output_tokens":20,"peak_ram_bytes":100,"peak_vram_bytes":50,"failure_type":None},
        {"compression":"none","prefetching":True,"success":True,"cold_start_seconds":6.0,"total_seconds":8.0,"output_tokens":24,"peak_ram_bytes":120,"peak_vram_bytes":55,"failure_type":None}
      ]}
    inp.write_text(json.dumps(payload))
    script=ROOT/'scripts/benchmark_airllm_modes.py'
    subprocess.run([sys.executable,str(script),'--input',str(inp),'--output',str(a)],check=True)
    subprocess.run([sys.executable,str(script),'--input',str(inp),'--output',str(b)],check=True)
    assert a.read_bytes() == b.read_bytes()
    result=json.loads(a.read_text())
    assert result["promotion_authority"] is False and result["preparation_authority"] is False
    assert result["modes"][0]["median_cold_start_seconds"] == 5.0
