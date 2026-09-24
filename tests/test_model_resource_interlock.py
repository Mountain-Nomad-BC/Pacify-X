from __future__ import annotations
import json
from pathlib import Path
import pytest

from runtime.model_resource_interlock import ModelResourceInterlock, ModelResourceNeed, load_external_runtime_policy

ROOT = Path(__file__).resolve().parents[1]


def test_production_external_runtime_policy_is_disabled_and_strict() -> None:
    policy = load_external_runtime_policy(ROOT)
    assert policy.globally_enabled is False
    assert policy.docker_enabled is False
    assert policy.airllm_enabled is False
    assert policy.normal_requests_may_download is False
    assert policy.normal_requests_may_prepare is False
    assert len(policy.policy_sha256) == 64


def test_gpu_lease_is_exclusive_and_release_requires_cleanup_proof() -> None:
    lock = ModelResourceInterlock(max_ram_commit_bytes=1000, max_vram_commit_bytes=1000, cpu_heavy_slots=1)
    need = ModelResourceNeed("docker_model_runner", 400, 400, True, True)
    first = lock.acquire("docker:a", need)
    with pytest.raises(TimeoutError):
        lock.acquire("airllm:b", ModelResourceNeed("airllm", 100, 100, False, True))
    with pytest.raises(PermissionError):
        lock.release(first.lease_id, cleanup_proven=False)
    lock.release(first.lease_id, cleanup_proven=True)
    assert lock.snapshot()["leases"] == []


def test_ram_cpu_limits_and_need_validation_fail_closed() -> None:
    lock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=0, cpu_heavy_slots=1)
    lease = lock.acquire("native:a", ModelResourceNeed("native", 100, 0, True, False))
    with pytest.raises(TimeoutError):
        lock.acquire("native:b", ModelResourceNeed("native", 1, 0, True, False))
    lock.release(lease.lease_id, cleanup_proven=True)
    with pytest.raises(ValueError, match="VRAM"):
        ModelResourceNeed("airllm", 0, 1, False, False).validate()


def test_nonfinite_clock_is_rejected_before_lease_mutation() -> None:
    lock = ModelResourceInterlock(max_ram_commit_bytes=100, max_vram_commit_bytes=100, clock=lambda: float("nan"))
    with pytest.raises(ValueError, match="clock"):
        lock.acquire("x", ModelResourceNeed("native", 0, 0, False, False))
    assert lock.snapshot()["leases"] == []
