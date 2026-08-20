"""Hardware discovery and evidence-based CPU/CUDA workload routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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

    @property
    def fingerprint(self) -> str:
        payload = {
            "kind": self.kind.value,
            "item_count": self.item_count,
            "total_bytes": self.total_bytes,
            "batchable": self.batchable,
            "arithmetic_intensity": self.arithmetic_intensity,
            "latency_sensitive": self.latency_sensitive,
            "deterministic_required": self.deterministic_required,
            "estimated_device_bytes": self.estimated_device_bytes,
            "operation_id": self.operation_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()


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
    cuda_device_count: int = 0
    cuda_executor_available: bool = False
    available_execution_backends: tuple[str, ...] = ()
    selected_cuda_device_index: int | None = None
    gpu_process_parallelism: int = 0
    gpu_parallelism_reason: str = "no compatible GPU executor is active"
    probe_duration_seconds: float = 0.0

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
            "cuda_device_count": self.cuda_device_count,
            "cuda_executor_available": self.cuda_executor_available,
            "execution_backends": self.available_execution_backends,
            "selected_cuda_device_index": self.selected_cuda_device_index,
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
    workload_fingerprint: str | None = None
    software_fingerprint: str | None = None

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
    maximum_benchmark_age_seconds: int = 7 * 24 * 60 * 60
    require_workload_fingerprint: bool = True

    def validate(self) -> None:
        if self.minimum_gpu_items < 1 or self.minimum_gpu_bytes < 0:
            raise ValueError("GPU workload thresholds must be non-negative")
        if not 1.0 <= self.minimum_gpu_speedup <= 100.0:
            raise ValueError("minimum GPU speedup must be between 1 and 100")
        if not 0 < self.max_fraction_of_free_vram <= 1:
            raise ValueError("VRAM fraction must be in (0, 1]")
        if self.default_batch_size < 1 or self.oom_retry_count < 0:
            raise ValueError("batch size and retry count are invalid")
        if self.maximum_benchmark_age_seconds < 1:
            raise ValueError("maximum benchmark age must be positive")


def _benchmark_is_current(
    benchmark: BenchmarkEvidence, workload: WorkloadProfile, policy: RoutingPolicy
) -> bool:
    try:
        measured = datetime.fromisoformat(benchmark.measured_at.replace("Z", "+00:00"))
        if measured.tzinfo is None:
            return False
        age = datetime.now(timezone.utc) - measured.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return False
    if age < timedelta(0) or age > timedelta(seconds=policy.maximum_benchmark_age_seconds):
        return False
    if policy.require_workload_fingerprint:
        return benchmark.workload_fingerprint == workload.fingerprint
    return benchmark.workload_fingerprint in {None, workload.fingerprint}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    device: Device
    reason: str
    batch_size: int | None = None
    fallback_device: Device = Device.CPU
    required_checks: tuple[str, ...] = ()
    benchmark_speedup: float | None = None
    deterministic_required: bool = True
    executor_backend: str | None = None
    device_index: int | None = None
    process_parallelism: int = 0


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


def _hidden_creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _run_nvidia_smi(timeout_seconds: float) -> tuple[dict[str, object], str | None]:
    if not shutil.which("nvidia-smi"):
        return {}, "nvidia-smi unavailable"
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,memory.total,memory.free,temperature.gpu,utilization.gpu,power.draw,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=_hidden_creationflags(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {}, f"nvidia-smi probe failed: {error}"
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}, completed.stderr.strip() or "nvidia-smi returned no devices"
    devices: list[dict[str, object]] = []
    for line in completed.stdout.splitlines():
        parts = [value.strip() for value in line.split(",")]
        if len(parts) != 9:
            continue
        try:
            devices.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "driver": parts[2],
                    "total": int(float(parts[3])) * 1024**2,
                    "free": int(float(parts[4])) * 1024**2,
                    "temperature": _number_or_none(parts[5]),
                    "utilization": _number_or_none(parts[6]),
                    "power": _number_or_none(parts[7]),
                    "fan": _number_or_none(parts[8]),
                }
            )
        except ValueError:
            continue
    if not devices:
        return {}, "nvidia-smi returned no parseable devices"
    selected = max(devices, key=lambda item: (int(item["free"]), -int(item["index"])))
    return {**selected, "devices": tuple(devices)}, None


def _sensor(
    *,
    sensor_id: str,
    kind: str,
    device: str,
    label: str,
    metric: str,
    value: float | None,
    unit: str,
    source: str,
    sampled_at: str,
    available: bool = True,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "id": sensor_id,
        "kind": kind,
        "device": device,
        "label": label,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source": source,
        "sampled_at": sampled_at,
        "available": available,
        "error": error,
    }


def _number_or_none(value: str) -> float | None:
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in {"n/a", "na", "[not supported]", "not supported"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _nvidia_telemetry_from_snapshot(
    snapshot: dict[str, object], sampled_at: str
) -> tuple[list[dict[str, object]], dict[str, object]]:
    provider = {"id": "nvidia-smi", "available": False, "error": None}
    devices = snapshot.get("devices", ())
    if not isinstance(devices, (tuple, list)) or not devices:
        provider["error"] = "nvidia-smi returned no telemetry"
        return [], provider
    sensors: list[dict[str, object]] = []
    metrics = (
        ("temperature", "Temperature", "celsius"),
        ("utilization", "Utilization", "percent"),
        ("power", "Power draw", "watts"),
        ("fan", "Fan speed", "percent"),
    )
    for record in devices:
        if not isinstance(record, dict):
            continue
        index = str(record.get("index", "unknown"))
        name = str(record.get("name", "unknown"))
        values = tuple(record.get(metric) for metric, _label, _unit in metrics)
        device = f"GPU {index}: {name}"
        for (metric, label, unit), raw in zip(metrics, values, strict=True):
            value = float(raw) if isinstance(raw, (int, float)) else None
            sensors.append(
                _sensor(
                    sensor_id=f"gpu:{index}:{metric}",
                    kind="gpu",
                    device=device,
                    label=label,
                    metric=metric,
                    value=value,
                    unit=unit,
                    source="nvidia-smi",
                    sampled_at=sampled_at,
                    available=value is not None,
                    error=None if value is not None else "metric not supported",
                )
            )
    provider["available"] = bool(sensors)
    if not sensors:
        provider["error"] = "nvidia-smi returned no parseable telemetry records"
    return sensors, provider


def _probe_nvidia_telemetry(
    timeout_seconds: float, sampled_at: str
) -> tuple[list[dict[str, object]], dict[str, object]]:
    snapshot, error = _run_nvidia_smi(timeout_seconds)
    if error:
        return [], {"id": "nvidia-smi", "available": False, "error": error}
    return _nvidia_telemetry_from_snapshot(snapshot, sampled_at)


def _probe_psutil_telemetry(
    sampled_at: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    provider = {"id": "psutil", "available": False, "error": None}
    try:
        psutil = importlib.import_module("psutil")
    except Exception as error:
        provider["error"] = f"psutil unavailable: {type(error).__name__}"
        return [], provider
    temperatures = getattr(psutil, "sensors_temperatures", None)
    if not callable(temperatures):
        provider["error"] = "temperature API unavailable on this host"
        return [], provider
    try:
        groups = temperatures(fahrenheit=False) or {}
    except Exception as error:
        provider["error"] = f"temperature probe failed: {type(error).__name__}: {error}"
        return [], provider
    sensors: list[dict[str, object]] = []
    for group, entries in sorted(groups.items()):
        kind = "cpu" if any(token in group.casefold() for token in ("cpu", "coretemp", "k10temp")) else "thermal"
        for index, entry in enumerate(entries):
            current = getattr(entry, "current", None)
            value = float(current) if isinstance(current, (int, float)) else None
            label = str(getattr(entry, "label", "") or f"{group} {index + 1}")
            sensors.append(
                _sensor(
                    sensor_id=f"{kind}:{group}:{index}:temperature",
                    kind=kind,
                    device=group,
                    label=label,
                    metric="temperature",
                    value=value,
                    unit="celsius",
                    source="psutil",
                    sampled_at=sampled_at,
                    available=value is not None,
                    error=None if value is not None else "metric unavailable",
                )
            )
    provider["available"] = bool(sensors)
    if not sensors:
        provider["error"] = "no temperature sensors exposed by the operating system"
    return sensors, provider


def hardware_telemetry(
    *,
    probe_external: bool = True,
    timeout_seconds: float = 2.0,
    nvidia_snapshot: dict[str, object] | None = None,
    nvidia_error: str | None = None,
) -> dict[str, object]:
    """Return bounded, best-effort live sensors without changing hardware authority."""
    if not 0.1 <= timeout_seconds <= 10:
        raise ValueError("hardware probe timeout must be between 0.1 and 10 seconds")
    sampled_at = datetime.now(timezone.utc).isoformat()
    sensors: list[dict[str, object]] = []
    providers: list[dict[str, object]] = []
    psutil_sensors, psutil_provider = _probe_psutil_telemetry(sampled_at)
    sensors.extend(psutil_sensors)
    providers.append(psutil_provider)
    if probe_external:
        if nvidia_snapshot is None:
            nvidia_sensors, nvidia_provider = _probe_nvidia_telemetry(
                timeout_seconds, sampled_at
            )
        elif nvidia_error:
            nvidia_sensors, nvidia_provider = [], {
                "id": "nvidia-smi", "available": False, "error": nvidia_error
            }
        else:
            nvidia_sensors, nvidia_provider = _nvidia_telemetry_from_snapshot(
                nvidia_snapshot, sampled_at
            )
        sensors.extend(nvidia_sensors)
        providers.append(nvidia_provider)
    else:
        providers.append(
            {"id": "nvidia-smi", "available": False, "error": "external probes disabled"}
        )
    sensors.sort(key=lambda item: str(item["id"]))
    return {
        "schema_version": "1.0",
        "sampled_at": sampled_at,
        "sensors": sensors,
        "providers": providers,
        "available_count": sum(1 for item in sensors if item["available"]),
        "temperature_count": sum(
            1 for item in sensors if item["available"] and item["metric"] == "temperature"
        ),
        "external_data_transmission": False,
    }


def _probe_library_worker(kind: str, timeout_seconds: float) -> tuple[dict[str, object], str | None]:
    """Probe an optional accelerator in an owned, bounded child process."""
    script = (
        "import json,sys\n"
        "kind=sys.argv[1]\n"
        "if kind=='torch':\n"
        " import torch\n"
        " available=bool(torch.cuda.is_available())\n"
        " out={'available':available,'version':str(getattr(torch.version,'cuda',None) or '')}\n"
        " if available:\n"
        "  out['device_count']=int(torch.cuda.device_count())\n"
        "  p=torch.cuda.get_device_properties(0); out.update(name=str(p.name),total=int(p.total_memory))\n"
        "  try:\n"
        "   free,total=torch.cuda.mem_get_info(0); out.update(free=int(free),total=int(total))\n"
        "  except (AttributeError,RuntimeError): pass\n"
        "else:\n"
        " import onnxruntime as ort\n"
        " out={'providers':list(map(str,ort.get_available_providers()))}\n"
        "print(json.dumps(out,separators=(',',':')))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, kind],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=_hidden_creationflags(),
        )
    except subprocess.TimeoutExpired:
        return {}, f"{kind} probe timed out after {timeout_seconds:g} seconds; child process terminated"
    except OSError as error:
        return {}, f"{kind} probe failed: {type(error).__name__}: {error}"
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else f"exit {completed.returncode}"
        return {}, f"{kind} probe failed: {detail}"
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}, f"{kind} probe returned invalid JSON"
    return (payload, None) if isinstance(payload, dict) else ({}, f"{kind} probe returned an invalid object")


def _probe_torch(timeout_seconds: float = 2.0) -> tuple[bool, str | None, str | None, dict[str, object]]:
    try:
        if importlib.util.find_spec("torch") is None:
            return False, None, "torch unavailable", {}
    except (ImportError, ValueError) as error:
        return False, None, f"torch discovery failed: {error}", {}
    payload, error = _probe_library_worker("torch", timeout_seconds)
    return (
        bool(payload.get("available")),
        str(payload.get("version") or "") or None,
        error,
        payload,
    )


def _probe_onnx(timeout_seconds: float = 2.0) -> tuple[tuple[str, ...], str | None]:
    try:
        if importlib.util.find_spec("onnxruntime") is None:
            return (), "onnxruntime unavailable"
    except (ImportError, ValueError) as error:
        return (), f"onnxruntime discovery failed: {error}"
    payload, error = _probe_library_worker("onnx", timeout_seconds)
    providers = payload.get("providers", ())
    return tuple(map(str, providers)) if isinstance(providers, list) else (), error


def _discover_hardware_details(
    *,
    probe_external: bool = True,
    probe_libraries: bool = True,
    timeout_seconds: float = 2.0,
    nvidia_snapshot: dict[str, object] | None = None,
    nvidia_error: str | None = None,
) -> tuple[HardwareProfile, dict[str, object], str | None]:
    if not 0.1 <= timeout_seconds <= 10:
        raise ValueError("hardware probe timeout must be between 0.1 and 10 seconds")
    started = time.perf_counter()
    errors: list[str] = []
    smi: dict[str, object] = nvidia_snapshot or {}
    smi_error = nvidia_error
    torch_result: tuple[bool, str | None, str | None, dict[str, object]] = (False, None, None, {})
    onnx_result: tuple[tuple[str, ...], str | None] = ((), None)
    probes: dict[str, Callable[[], object]] = {}
    if probe_external and nvidia_snapshot is None:
        probes["nvidia"] = lambda: _run_nvidia_smi(timeout_seconds)
    if probe_libraries:
        probes["torch"] = lambda: _probe_torch(timeout_seconds)
        probes["onnx"] = lambda: _probe_onnx(timeout_seconds)
    if probes:
        with ThreadPoolExecutor(max_workers=min(3, len(probes)), thread_name_prefix="px-hardware-probe") as pool:
            futures = {name: pool.submit(operation) for name, operation in probes.items()}
            results = {name: future.result() for name, future in futures.items()}
        if "nvidia" in results:
            smi, smi_error = results["nvidia"]  # type: ignore[assignment]
        if "torch" in results:
            torch_result = results["torch"]  # type: ignore[assignment]
        if "onnx" in results:
            onnx_result = results["onnx"]  # type: ignore[assignment]
    if smi_error and probe_external:
        errors.append(smi_error)
    torch_available = False
    cuda_runtime = None
    torch_details: dict[str, object] = {}
    onnx_providers: tuple[str, ...] = ()
    if probe_libraries:
        torch_available, cuda_runtime, torch_error, torch_details = torch_result
        if torch_error:
            errors.append(torch_error)
        onnx_providers, onnx_error = onnx_result
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
    cuda_device_count = len(smi.get("devices", ())) if isinstance(smi.get("devices", ()), (tuple, list)) else 0
    cuda_available = bool(smi or torch_available or "CUDAExecutionProvider" in onnx_providers)
    backends = tuple(
        name
        for name, available in (
            ("torch-cuda", torch_available),
            ("onnx-cuda", "CUDAExecutionProvider" in onnx_providers),
            ("onnx-directml", "DmlExecutionProvider" in onnx_providers),
            ("cupy", "cupy" in optional),
            ("cudf", "cudf" in optional),
            ("tensorrt", "tensorrt" in optional),
        )
        if available
    )
    cuda_executor_available = any(
        name in backends for name in ("torch-cuda", "onnx-cuda", "cupy", "cudf", "tensorrt")
    )
    profile = HardwareProfile(
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
        cuda_device_count=cuda_device_count or int(torch_details.get("device_count") or (1 if torch_available else 0)),
        cuda_executor_available=cuda_executor_available,
        available_execution_backends=backends,
        selected_cuda_device_index=int(smi.get("index")) if smi.get("index") is not None else (0 if torch_available else None),
        gpu_process_parallelism=1 if cuda_executor_available else 0,
        gpu_parallelism_reason=(
            "one bounded GPU executor; parallelism occurs inside batched device kernels"
            if cuda_executor_available
            else "GPU hardware may be visible, but no compatible CUDA executor is active"
        ),
        probe_duration_seconds=round(time.perf_counter() - started, 6),
    )
    return profile, smi, smi_error


def discover_hardware(
    *,
    probe_external: bool = True,
    probe_libraries: bool = True,
    timeout_seconds: float = 2.0,
    nvidia_snapshot: dict[str, object] | None = None,
    nvidia_error: str | None = None,
) -> HardwareProfile:
    profile, _snapshot, _error = _discover_hardware_details(
        probe_external=probe_external,
        probe_libraries=probe_libraries,
        timeout_seconds=timeout_seconds,
        nvidia_snapshot=nvidia_snapshot,
        nvidia_error=nvidia_error,
    )
    return profile


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
    checks.append("cuda_executor_available")
    if not hardware.cuda_executor_available:
        return RoutingDecision(
            Device.CPU,
            "CUDA hardware is visible, but no compatible CUDA execution backend is ready",
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
        and _benchmark_is_current(benchmark, workload, policy)
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
        executor_backend=next(
            (name for name in hardware.available_execution_backends if name != "onnx-directml"),
            None,
        ),
        device_index=hardware.selected_cuda_device_index,
        process_parallelism=hardware.gpu_process_parallelism,
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
            "executor_backend": None,
            "device_index": None,
            "process_parallelism": 0,
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
                "executor_backend": decision.executor_backend,
                "device_index": decision.device_index,
                "process_parallelism": decision.process_parallelism,
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
        "executor_backend": decision.executor_backend,
        "device_index": decision.device_index,
        "process_parallelism": decision.process_parallelism,
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
    workload: WorkloadProfile | None = None,
    software_fingerprint: str | None = None,
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
        workload_fingerprint=workload.fingerprint if workload else None,
        software_fingerprint=software_fingerprint,
    )


def hardware_report(
    *,
    probe_external: bool = True,
    probe_libraries: bool = True,
    probe_sensors: bool | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    report_started = time.perf_counter()
    needs_nvidia = probe_external or (probe_external if probe_sensors is None else probe_sensors)
    profile, nvidia_snapshot, nvidia_error = _discover_hardware_details(
        probe_external=needs_nvidia,
        probe_libraries=probe_libraries,
        timeout_seconds=timeout_seconds,
        nvidia_snapshot=None if needs_nvidia else {},
        nvidia_error=None,
    )
    telemetry = hardware_telemetry(
        probe_external=probe_external if probe_sensors is None else probe_sensors,
        timeout_seconds=timeout_seconds,
        nvidia_snapshot=nvidia_snapshot,
        nvidia_error=nvidia_error,
    )
    return {
        "valid": True,
        "hardware": asdict(profile),
        "telemetry": telemetry,
        "hardware_fingerprint": profile.fingerprint,
        "core_scan_device": "cpu",
        "gpu_optional": True,
        "probe_duration_seconds": round(time.perf_counter() - report_started, 6),
        "probe_process_policy": {
            "maximum_concurrent_children": 3,
            "discovery_parallelism": "independent read-only probes only",
            "gpu_execution_processes": profile.gpu_process_parallelism,
            "per_child_timeout_seconds": timeout_seconds,
            "shell": False,
            "visible_window": False,
            "timeout_terminates_and_waits_for_child": True,
        },
        "routing_capabilities": {
            "cpu_authoritative_workloads": sorted(kind.value for kind in CPU_AUTHORITATIVE),
            "gpu_eligible_workloads": sorted(kind.value for kind in GPU_SUITABLE),
            "conditional_gpu_workloads": sorted(kind.value for kind in CONDITIONAL),
            "cuda_device_visible": profile.cuda_available,
            "cuda_executor_ready": profile.cuda_executor_available,
            "directml_discovered": "onnx-directml" in profile.available_execution_backends,
            "directml_routing": "unsupported until an admitted DirectML executor passes compatibility and benchmark gates; Intel/integrated GPU is never selected implicitly",
            "process_parallelism": profile.gpu_process_parallelism,
            "parallelism_reason": profile.gpu_parallelism_reason,
            "automatic_gpu_requires_current_benchmark": True,
            "deterministic_cpu_fallback": True,
        },
        "external_data_transmission": False,
    }
