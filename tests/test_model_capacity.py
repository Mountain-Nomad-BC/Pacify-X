from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.capability_scheduler import Resources, Scheduler, model_route_capacity_snapshot
from runtime.hardware_routing import HardwareProfile, model_capacity_snapshot_from_headroom, model_resource_headroom
from runtime.model_capacity import ModelCapacityNeed, ModelCapacitySnapshot, assess_model_capacity


def snapshot(**overrides) -> ModelCapacitySnapshot:
    base = dict(
        cpu_cores_total=8.0, cpu_cores_available=6.0,
        ram_gb_total=32.0, ram_gb_available=24.0,
        vram_gb_total=8.0, vram_gb_available=7.0,
        concurrent_slots_total=2, concurrent_slots_available=1,
        queue_depth=1, max_queue_depth=8,
    )
    base.update(overrides)
    return ModelCapacitySnapshot(**base)


def test_capacity_admits_waits_and_denies_without_dropping() -> None:
    snap = snapshot()
    admitted = assess_model_capacity(snap, ModelCapacityNeed("tiny", cpu_cores=2, ram_gb=2, concurrent_slots=1))
    assert admitted.state == "admit"
    assert admitted.no_drop is True and admitted.authority_granted is False

    waiting = assess_model_capacity(snap, ModelCapacityNeed("deep", cpu_cores=7, ram_gb=2, concurrent_slots=1))
    assert waiting.state == "wait"
    assert "cpu_pressure" in waiting.reasons

    denied = assess_model_capacity(snap, ModelCapacityNeed("too-big", cpu_cores=9, concurrent_slots=1))
    assert denied.state == "deny"
    assert denied.reasons == ("request_exceeds_total_capacity",)


def test_exclusive_lease_and_queue_pressure_wait_instead_of_silent_fallback() -> None:
    snap = snapshot(exclusive_model_id="deep", queue_depth=8, max_queue_depth=8)
    other = assess_model_capacity(snap, ModelCapacityNeed("tiny", cpu_cores=1))
    assert other.state == "wait"
    assert other.reasons == ("exclusive_model_lease_active",)
    deep = assess_model_capacity(snap, ModelCapacityNeed("deep", cpu_cores=1))
    assert deep.state == "wait"
    assert "route_queue_full" in deep.reasons


def test_snapshot_rejects_impossible_or_nonfinite_capacity() -> None:
    with pytest.raises(ValueError, match="available cannot exceed total"):
        snapshot(cpu_cores_available=9.0)
    with pytest.raises(ValueError, match="finite"):
        snapshot(ram_gb_total=float("nan"))
    with pytest.raises(ValueError, match="positive"):
        snapshot(max_queue_depth=0)


def test_scheduler_projects_observational_capacity_without_reserving() -> None:
    scheduler = Scheduler(Resources(cpu_cores=8, ram_gb=16, gpu_count=1, vram_gb=8, disk_gb=10))
    before = scheduler.available.record()
    snap = model_route_capacity_snapshot(
        scheduler, queue_depth=2, max_queue_depth=8,
        concurrent_slots_total=2, concurrent_slots_available=1,
    )
    assert snap.cpu_cores_total == 8.0
    assert snap.concurrent_slots_available == 1
    assert scheduler.available.record() == before
    assert len(snap.source_sha256 or "") == 64


def test_hardware_headroom_projects_bounded_capacity_and_binds_fingerprint() -> None:
    hardware = HardwareProfile(
        cuda_available=True, gpu_name="gpu", driver_version="1", cuda_runtime="1",
        total_vram_bytes=8 * 1024**3, free_vram_bytes=6 * 1024**3,
        system_ram_bytes=64 * 1024**3, environment="linux", cpu_logical_cores=16,
        cpu_physical_cores=8, torch_cuda_available=True, onnx_providers=(), optional_accelerators=(),
    )
    headroom = model_resource_headroom(hardware, free_system_ram_bytes=48 * 1024**3)
    snap = model_capacity_snapshot_from_headroom(
        hardware, headroom, queue_depth=0, max_queue_depth=8,
        concurrent_slots_total=2, concurrent_slots_available=2,
    )
    assert snap.cpu_cores_total == 14.0
    assert snap.vram_gb_total == 7.0
    assert snap.vram_gb_available == 5.0
    with pytest.raises(ValueError, match="fingerprint"):
        model_capacity_snapshot_from_headroom(
            replace(hardware, driver_version="2"), headroom, queue_depth=0, max_queue_depth=8,
            concurrent_slots_total=2, concurrent_slots_available=2,
        )


def test_capacity_need_and_decision_identities_are_deterministic_and_context_sensitive() -> None:
    snap = snapshot()
    need = ModelCapacityNeed("tiny", cpu_cores=2, context_tokens=4096, generation_tokens=512)
    one = assess_model_capacity(snap, need)
    two = assess_model_capacity(snap, need)
    assert one.need_sha256 == need.need_sha256
    assert one.decision_sha256 == two.decision_sha256
    changed = assess_model_capacity(snap, ModelCapacityNeed("tiny", cpu_cores=2, context_tokens=8192, generation_tokens=512))
    assert changed.need_sha256 != one.need_sha256
    assert changed.decision_sha256 != one.decision_sha256


def test_hardware_capacity_projection_fails_closed_when_cpu_or_ram_headroom_is_unknown() -> None:
    hardware = HardwareProfile(
        cuda_available=False, gpu_name=None, driver_version=None, cuda_runtime=None,
        total_vram_bytes=0, free_vram_bytes=0, system_ram_bytes=0, environment="unknown",
        cpu_logical_cores=None, cpu_physical_cores=None, torch_cuda_available=False,
        onnx_providers=(), optional_accelerators=(),
    )
    headroom = model_resource_headroom(hardware, free_system_ram_bytes=None)
    with pytest.raises(ValueError, match="known CPU and system-RAM"):
        model_capacity_snapshot_from_headroom(
            hardware, headroom, queue_depth=0, max_queue_depth=8,
            concurrent_slots_total=1, concurrent_slots_available=1,
        )
