"""Hardware discovery and evidence-based CPU/CUDA workload routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Callable, Literal, Sequence, TypeVar


class Device(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"


class WorkloadKind(str, Enum):
    FILESYSTEM_IO = "filesystem_io"
    DATABASE = "database"
    SERIALIZATION = "serialization"
    HASHING = "hashing"
    COMPRESSION = "compression"
    SORTING = "sorting"
    TEXT_ANALYSIS = "text_analysis"
    EMBEDDING = "embedding"
    MODEL_INFERENCE = "model_inference"
    VECTOR_SEARCH = "vector_search"
    DATAFRAME = "dataframe"
    IMAGE_INFERENCE = "image_inference"
    NUMERICAL = "numerical"


GPU_SUITABLE = {
    WorkloadKind.EMBEDDING,
    WorkloadKind.MODEL_INFERENCE,
    WorkloadKind.VECTOR_SEARCH,
    WorkloadKind.IMAGE_INFERENCE,
    WorkloadKind.NUMERICAL,
}
CONDITIONAL = {
    WorkloadKind.HASHING,
    WorkloadKind.COMPRESSION,
    WorkloadKind.SORTING,
    WorkloadKind.TEXT_ANALYSIS,
    WorkloadKind.DATAFRAME,
}
CPU_AUTHORITATIVE = {
    WorkloadKind.FILESYSTEM_IO,
    WorkloadKind.DATABASE,
    WorkloadKind.SERIALIZATION,
}


@dataclass(frozen=True, slots=True)
class WorkloadProfile:
    kind: WorkloadKind
    item_count: int
    total_bytes: int
    batchable: bool
    arithmetic_intensity: float | None = None
    latency_sensitive: bool = False
    deterministic_required: bool = True
    estimated_device_bytes: int | None = None
    operation_id: str = "anonymous"


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    cuda_available: bool
    gpu_name: str | None
    driver_version: str | None
    cuda_runtime: str | None
    total_vram_bytes: int
    free_vram_bytes: int
    system_ram_bytes: int
    environment: Literal["windows", "wsl2", "linux", "docker", "unknown"]
    cpu_logical_cores: int | None
    cpu_physical_cores: int | None
    torch_cuda_available: bool
    onnx_providers: tuple[str, ...]
    optional_accelerators: tuple[str, ...]
    probe_errors: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        payload = {
            "gpu": self.gpu_name,
            "driver": self.driver_version,
            "cuda_runtime": self.cuda_runtime,
            "vram": self.total_vram_bytes,
            "environment": self.environment,
            "torch_cuda": self.torch_cuda_available,
            "onnx": self.onnx_providers,
            "accelerators": self.optional_accelerators,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    operation_id: str
    hardware_fingerprint: str
    cpu_seconds: float
    gpu_end_to_end_seconds: float
    correctness_passed: bool
    peak_vram_bytes: int
    measured_at: str
    numerical_tolerance: float | None = None

    @property
    def speedup(self) -> float:
        if self.gpu_end_to_end_seconds <= 0:
            return 0.0
        return self.cpu_seconds / self.gpu_end_to_end_seconds


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    minimum_gpu_items: int = 10_000
    minimum_gpu_bytes: int = 8 * 1024**2
    minimum_gpu_speedup: float = 1.25
    max_fraction_of_free_vram: float = 0.70
    minimum_free_vram_bytes: int = 1536 * 1024**2
    default_batch_size: int = 256
    oom_retry_count: int = 2
    fallback_to_cpu: bool = True
    require_benchmark: bool = True

    def validate(self) -> None:
        if self.minimum_gpu_items < 1 or self.minimum_gpu_bytes < 0:
            raise ValueError("GPU workload thresholds must be non-negative")
        if not 1.0 <= self.minimum_gpu_speedup <= 100.0:
            raise ValueError("minimum GPU speedup must be between 1 and 100")
        if not 0 < self.max_fraction_of_free_vram <= 1:
            raise ValueError("VRAM fraction must be in (0, 1]")
        if self.default_batch_size < 1 or self.oom_retry_count < 0:
            raise ValueError("batch size and retry count are invalid")


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    device: Device
    reason: str
    batch_size: int | None = None
    fallback_device: Device = Device.CPU
    required_checks: tuple[str, ...] = ()
    benchmark_speedup: float | None = None
    deterministic_required: bool = True


def _environment() -> Literal["windows", "wsl2", "linux", "docker", "unknown"]:
    release = platform.release().casefold()
    proc_version = ""
    try:
        with open("/proc/version", encoding="utf-8") as stream:
            proc_version = stream.read().casefold()
    except OSError:
        pass
    if os.environ.get("container") or os.path.exists("/.dockerenv"):
        return "docker"
    if "microsoft" in release or "microsoft" in proc_version or os.environ.get("WSL_DISTRO_NAME"):
        return "wsl2"
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _system_ram() -> int:
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
        except (AttributeError, OSError, ValueError):
            return 0
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return 0


def _run_nvidia_smi(timeout_seconds: float) -> tuple[dict[str, object], str | None]:
    if not shutil.which("nvidia-smi"):
        return {}, "nvidia-smi unavailable"
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {}, f"nvidia-smi probe failed: {error}"
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}, completed.stderr.strip() or "nvidia-smi returned no devices"
    parts = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
    if len(parts) != 4:
        return {}, "nvidia-smi returned an unexpected record"
    try:
        return {
            "name": parts[0],
            "driver": parts[1],
            "total": int(float(parts[2])) * 1024**2,
            "free": int(float(parts[3])) * 1024**2,
        }, None
    except ValueError:
        return {}, "nvidia-smi returned invalid memory values"


def _probe_torch() -> tuple[bool, str | None, str | None, dict[str, object]]:
    try:
        torch = importlib.import_module("torch")
        available = bool(torch.cuda.is_available())
        version = str(getattr(torch.version, "cuda", None) or "") or None
        details: dict[str, object] = {}
        if available and torch.cuda.device_count():
            properties = torch.cuda.get_device_properties(0)
            details = {
                "name": str(properties.name),
                "total": int(properties.total_memory),
            }
            try:
                free, total = torch.cuda.mem_get_info(0)
                details.update({"free": int(free), "total": int(total)})
            except (AttributeError, RuntimeError):
                pass
        return available, version, None, details
    except Exception as error:  # optional dependency probing must never fail startup
        return False, None, f"torch probe: {type(error).__name__}: {error}", {}


def _probe_onnx() -> tuple[tuple[str, ...], str | None]:
    try:
        runtime = importlib.import_module("onnxruntime")
        return tuple(map(str, runtime.get_available_providers())), None
    except Exception as error:
        return (), f"onnxruntime probe: {type(error).__name__}: {error}"


def discover_hardware(
    *, probe_external: bool = True, probe_libraries: bool = True, timeout_seconds: float = 2.0
) -> HardwareProfile:
    if not 0.1 <= timeout_seconds <= 10:
        raise ValueError("hardware probe timeout must be between 0.1 and 10 seconds")
    errors: list[str] = []
    smi, smi_error = _run_nvidia_smi(timeout_seconds) if probe_external else ({}, None)
    if smi_error and probe_external:
        errors.append(smi_error)
    torch_available = False
    cuda_runtime = None
    torch_details: dict[str, object] = {}
    onnx_providers: tuple[str, ...] = ()
    if probe_libraries:
        torch_available, cuda_runtime, torch_error, torch_details = _probe_torch()
        if torch_error:
            errors.append(torch_error)
        onnx_providers, onnx_error = _probe_onnx()
        if onnx_error:
            errors.append(onnx_error)
    optional = tuple(
        name
        for name in ("cupy", "cudf", "tensorrt")
        if importlib.util.find_spec(name) is not None
    )
    gpu_name = str(smi.get("name") or torch_details.get("name") or "") or None
    total_vram = int(smi.get("total") or torch_details.get("total") or 0)
    free_vram = int(smi.get("free") or torch_details.get("free") or 0)
    cuda_available = bool(
        torch_available
        or "CUDAExecutionProvider" in onnx_providers
        or smi
    )
    return HardwareProfile(
        cuda_available=cuda_available,
        gpu_name=gpu_name,
        driver_version=str(smi.get("driver") or "") or None,
        cuda_runtime=cuda_runtime,
        total_vram_bytes=total_vram,
        free_vram_bytes=free_vram,
        system_ram_bytes=_system_ram(),
        environment=_environment(),
        cpu_logical_cores=os.cpu_count(),
        cpu_physical_cores=None,
        torch_cuda_available=torch_available,
        onnx_providers=onnx_providers,
        optional_accelerators=optional,
        probe_errors=tuple(errors),
    )


def route_workload(
    workload: WorkloadProfile,
    hardware: HardwareProfile,
    *,
    policy: RoutingPolicy = RoutingPolicy(),
    benchmark: BenchmarkEvidence | None = None,
    requested_device: Literal["auto", "cpu", "cuda"] = "auto",
) -> RoutingDecision:
    policy.validate()
    checks = ["workload_classified", "fallback_declared"]
    if workload.item_count < 0 or workload.total_bytes < 0:
        raise ValueError("workload sizes cannot be negative")
    if requested_device not in {"auto", "cpu", "cuda"}:
        raise ValueError("requested device must be auto, cpu, or cuda")
    if workload.kind in CPU_AUTHORITATIVE:
        return RoutingDecision(
            Device.CPU,
            f"{workload.kind.value} is CPU/operating-system authoritative",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    if requested_device == "cpu":
        return RoutingDecision(
            Device.CPU,
            "CPU execution was explicitly requested",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    checks.append("cuda_available")
    if not hardware.cuda_available:
        return RoutingDecision(
            Device.CPU,
            "CUDA is unavailable; using declared CPU fallback",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    if hardware.free_vram_bytes < policy.minimum_free_vram_bytes:
        return RoutingDecision(
            Device.CPU,
            "free VRAM is below the configured reserve",
            required_checks=tuple(checks + ["free_vram_sufficient"]),
            deterministic_required=workload.deterministic_required,
        )
    estimated = workload.estimated_device_bytes or workload.total_bytes
    vram_limit = int(hardware.free_vram_bytes * policy.max_fraction_of_free_vram)
    checks.append("free_vram_sufficient")
    if estimated > vram_limit:
        return RoutingDecision(
            Device.CPU,
            "estimated device memory exceeds the configured free-VRAM fraction",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    if not workload.batchable:
        return RoutingDecision(
            Device.CPU,
            "workload is not batchable enough to amortize device overhead",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    if workload.item_count < policy.minimum_gpu_items and workload.total_bytes < policy.minimum_gpu_bytes:
        return RoutingDecision(
            Device.CPU,
            "workload is below configured GPU size thresholds",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    if workload.kind not in GPU_SUITABLE | CONDITIONAL:
        return RoutingDecision(
            Device.CPU,
            "no compatible GPU implementation is declared for this workload",
            required_checks=tuple(checks),
            deterministic_required=workload.deterministic_required,
        )
    checks.extend(("benchmark_current", "correctness_validated"))
    benchmark_valid = bool(
        benchmark
        and benchmark.operation_id == workload.operation_id
        and benchmark.hardware_fingerprint == hardware.fingerprint
        and benchmark.correctness_passed
        and benchmark.peak_vram_bytes <= vram_limit
        and benchmark.speedup >= policy.minimum_gpu_speedup
    )
    if policy.require_benchmark and requested_device == "auto" and not benchmark_valid:
        return RoutingDecision(
            Device.CPU,
            "current end-to-end benchmark and correctness evidence do not justify GPU routing",
            required_checks=tuple(checks),
            benchmark_speedup=benchmark.speedup if benchmark else None,
            deterministic_required=workload.deterministic_required,
        )
    reason = (
        "validated end-to-end benchmark exceeds the GPU speedup threshold"
        if benchmark_valid
        else "CUDA was explicitly requested and compatibility/resource checks passed"
    )
    return RoutingDecision(
        Device.CUDA,
        reason,
        batch_size=policy.default_batch_size,
        fallback_device=Device.CPU,
        required_checks=tuple(checks),
        benchmark_speedup=benchmark.speedup if benchmark else None,
        deterministic_required=workload.deterministic_required,
    )


def onnx_provider_order(available: Sequence[str]) -> tuple[object, ...]:
    providers: list[object] = []
    if "CUDAExecutionProvider" in set(available):
        providers.append(
            (
                "CUDAExecutionProvider",
                {"device_id": 0, "arena_extend_strategy": "kNextPowerOfTwo"},
            )
        )
    providers.append("CPUExecutionProvider")
    return tuple(providers)


T = TypeVar("T")


def execute_with_fallback(
    decision: RoutingDecision,
    *,
    gpu_fn: Callable[[int], T],
    cpu_fn: Callable[[], T],
    oom_retry_count: int = 2,
) -> tuple[T, dict[str, object]]:
    if decision.device is Device.CPU:
        started = time.perf_counter()
        value = cpu_fn()
        return value, {
            "selected_device": "cpu",
            "actual_device": "cpu",
            "fallback": False,
            "duration_seconds": time.perf_counter() - started,
            "routing_reason": decision.reason,
        }
    batch_size = decision.batch_size or 1
    events: list[str] = []
    started = time.perf_counter()
    for attempt in range(oom_retry_count + 1):
        try:
            value = gpu_fn(batch_size)
            return value, {
                "selected_device": "cuda",
                "actual_device": "cuda",
                "fallback": False,
                "batch_size": batch_size,
                "oom_events": events,
                "duration_seconds": time.perf_counter() - started,
                "routing_reason": decision.reason,
            }
        except RuntimeError as error:
            message = str(error).casefold()
            if not any(token in message for token in ("cuda", "cudnn", "out of memory")):
                raise
            events.append(f"attempt_{attempt + 1}:{type(error).__name__}")
            batch_size = max(1, batch_size // 2)
    value = cpu_fn()
    return value, {
        "selected_device": "cuda",
        "actual_device": "cpu",
        "fallback": True,
        "batch_size": batch_size,
        "oom_events": events,
        "duration_seconds": time.perf_counter() - started,
        "routing_reason": decision.reason,
    }


def benchmark_devices(
    operation_id: str,
    hardware: HardwareProfile,
    *,
    cpu_fn: Callable[[], T],
    gpu_fn: Callable[[], T],
    compare: Callable[[T, T], bool],
    synchronize: Callable[[], None] | None = None,
    peak_vram_bytes: Callable[[], int] | None = None,
) -> BenchmarkEvidence:
    cpu_started = time.perf_counter()
    cpu_result = cpu_fn()
    cpu_seconds = time.perf_counter() - cpu_started
    gpu_fn()  # warm-up
    if synchronize:
        synchronize()
    gpu_started = time.perf_counter()
    gpu_result = gpu_fn()
    if synchronize:
        synchronize()
    gpu_seconds = time.perf_counter() - gpu_started
    return BenchmarkEvidence(
        operation_id=operation_id,
        hardware_fingerprint=hardware.fingerprint,
        cpu_seconds=cpu_seconds,
        gpu_end_to_end_seconds=gpu_seconds,
        correctness_passed=bool(compare(cpu_result, gpu_result)),
        peak_vram_bytes=int(peak_vram_bytes() if peak_vram_bytes else 0),
        measured_at=datetime.now(timezone.utc).isoformat(),
    )


def hardware_report(*, probe_external: bool = True, probe_libraries: bool = True) -> dict[str, object]:
    profile = discover_hardware(
        probe_external=probe_external, probe_libraries=probe_libraries
    )
    return {
        "valid": True,
        "hardware": asdict(profile),
        "hardware_fingerprint": profile.fingerprint,
        "core_scan_device": "cpu",
        "gpu_optional": True,
        "external_data_transmission": False,
    }
