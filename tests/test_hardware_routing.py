from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from runtime.hardware_routing import (
    BenchmarkEvidence,
    Device,
    HardwareProfile,
    RoutingDecision,
    RoutingPolicy,
    WorkloadKind,
    WorkloadProfile,
    execute_with_fallback,
    onnx_provider_order,
    route_workload,
)


class HardwareRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hardware = HardwareProfile(
            cuda_available=True,
            gpu_name="Test GPU",
            driver_version="1",
            cuda_runtime="12",
            total_vram_bytes=8 * 1024**3,
            free_vram_bytes=6 * 1024**3,
            system_ram_bytes=64 * 1024**3,
            environment="windows",
            cpu_logical_cores=16,
            cpu_physical_cores=8,
            torch_cuda_available=True,
            onnx_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            optional_accelerators=(),
        )
        self.workload = WorkloadProfile(
            kind=WorkloadKind.EMBEDDING,
            item_count=100_000,
            total_bytes=200 * 1024**2,
            batchable=True,
            estimated_device_bytes=1024**3,
            operation_id="embedding-v1",
        )

    def _benchmark(self, *, speedup: float = 2.0, correct: bool = True):
        return BenchmarkEvidence(
            operation_id=self.workload.operation_id,
            hardware_fingerprint=self.hardware.fingerprint,
            cpu_seconds=speedup,
            gpu_end_to_end_seconds=1.0,
            correctness_passed=correct,
            peak_vram_bytes=1024**3,
            measured_at=datetime.now(timezone.utc).isoformat(),
            workload_fingerprint=self.workload.fingerprint,
        )

    def test_filesystem_database_and_serialization_are_always_cpu(self) -> None:
        for kind in (
            WorkloadKind.FILESYSTEM_IO,
            WorkloadKind.DATABASE,
            WorkloadKind.SERIALIZATION,
        ):
            decision = route_workload(
                replace(self.workload, kind=kind),
                self.hardware,
                benchmark=self._benchmark(),
                requested_device="cuda",
            )
            self.assertEqual(decision.device, Device.CPU)

    def test_absent_cuda_busy_gpu_tiny_and_nonbatchable_fall_back_to_cpu(self) -> None:
        cases = (
            (
                self.workload,
                replace(self.hardware, cuda_available=False),
                "CUDA is unavailable",
            ),
            (
                self.workload,
                replace(self.hardware, free_vram_bytes=1024),
                "free VRAM",
            ),
            (replace(self.workload, item_count=1, total_bytes=1), self.hardware, "threshold"),
            (replace(self.workload, batchable=False), self.hardware, "batchable"),
        )
        for workload, hardware, reason in cases:
            decision = route_workload(workload, hardware, benchmark=self._benchmark())
            self.assertEqual(decision.device, Device.CPU)
            self.assertIn(reason.casefold(), decision.reason.casefold())

    def test_auto_cuda_requires_current_correct_fast_benchmark(self) -> None:
        self.assertEqual(
            route_workload(self.workload, self.hardware).device,
            Device.CPU,
        )
        stale = replace(self._benchmark(), hardware_fingerprint="stale")
        self.assertEqual(
            route_workload(self.workload, self.hardware, benchmark=stale).device,
            Device.CPU,
        )
        expired = replace(self._benchmark(), measured_at="2020-01-01T00:00:00+00:00")
        self.assertEqual(
            route_workload(self.workload, self.hardware, benchmark=expired).device,
            Device.CPU,
        )
        wrong_shape = replace(self._benchmark(), workload_fingerprint="0" * 64)
        self.assertEqual(
            route_workload(self.workload, self.hardware, benchmark=wrong_shape).device,
            Device.CPU,
        )
        incorrect = self._benchmark(correct=False)
        self.assertEqual(
            route_workload(self.workload, self.hardware, benchmark=incorrect).device,
            Device.CPU,
        )
        slow = self._benchmark(speedup=1.1)
        self.assertEqual(
            route_workload(self.workload, self.hardware, benchmark=slow).device,
            Device.CPU,
        )
        decision = route_workload(
            self.workload, self.hardware, benchmark=self._benchmark()
        )
        self.assertEqual(decision.device, Device.CUDA)
        self.assertEqual(decision.fallback_device, Device.CPU)
        self.assertGreaterEqual(decision.benchmark_speedup or 0, 1.25)

    def test_conditional_workload_needs_benchmark_and_vram_policy_is_enforced(self) -> None:
        conditional = replace(self.workload, kind=WorkloadKind.HASHING)
        self.assertEqual(
            route_workload(conditional, self.hardware).device,
            Device.CPU,
        )
        evidence = replace(
            self._benchmark(),
            operation_id=conditional.operation_id,
            workload_fingerprint=conditional.fingerprint,
        )
        self.assertEqual(
            route_workload(conditional, self.hardware, benchmark=evidence).device,
            Device.CUDA,
        )
        oversized = replace(
            conditional, estimated_device_bytes=self.hardware.free_vram_bytes
        )
        self.assertEqual(
            route_workload(oversized, self.hardware, benchmark=evidence).device,
            Device.CPU,
        )

    def test_forced_cuda_still_obeys_compatibility_and_resource_checks(self) -> None:
        decision = route_workload(
            self.workload,
            self.hardware,
            requested_device="cuda",
        )
        self.assertEqual(decision.device, Device.CUDA)
        no_cuda = route_workload(
            self.workload,
            replace(self.hardware, cuda_available=False),
            requested_device="cuda",
        )
        self.assertEqual(no_cuda.device, Device.CPU)

    def test_oom_retries_are_bounded_and_then_fall_back(self) -> None:
        batches: list[int] = []

        def fail_gpu(batch: int) -> str:
            batches.append(batch)
            raise RuntimeError("CUDA out of memory")

        value, telemetry = execute_with_fallback(
            RoutingDecision(Device.CUDA, "test", batch_size=16),
            gpu_fn=fail_gpu,
            cpu_fn=lambda: "cpu-result",
            oom_retry_count=2,
        )
        self.assertEqual(value, "cpu-result")
        self.assertEqual(batches, [16, 8, 4])
        self.assertTrue(telemetry["fallback"])
        self.assertEqual(telemetry["actual_device"], "cpu")

    def test_non_gpu_runtime_error_is_not_swallowed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "application bug"):
            execute_with_fallback(
                RoutingDecision(Device.CUDA, "test", batch_size=4),
                gpu_fn=lambda batch: (_ for _ in ()).throw(RuntimeError("application bug")),
                cpu_fn=lambda: "cpu",
            )

    def test_onnx_provider_order_always_has_cpu_fallback(self) -> None:
        providers = onnx_provider_order(
            ["CPUExecutionProvider", "CUDAExecutionProvider"]
        )
        self.assertEqual(providers[-1], "CPUExecutionProvider")
        self.assertEqual(providers[0][0], "CUDAExecutionProvider")
        self.assertEqual(
            onnx_provider_order(["CPUExecutionProvider"]),
            ("CPUExecutionProvider",),
        )

    def test_invalid_policy_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "VRAM"):
            route_workload(
                self.workload,
                self.hardware,
                policy=RoutingPolicy(max_fraction_of_free_vram=0),
            )


if __name__ == "__main__":
    unittest.main()
