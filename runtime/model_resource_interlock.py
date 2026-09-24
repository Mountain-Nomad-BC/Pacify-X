"""Bounded cross-runtime resource leases for local, Docker, and AirLLM model lanes.

This module is deliberately subordinate to PX routing and lifecycle authorities.  A
lease proves only that this in-process coordinator admitted a bounded resource
claim; it grants no model-load, process, provider, network, or routing authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from typing import Callable, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from .archive_io import reject_path_links
from .json_io import load_json_object

_MAX_BYTES = 2**63 - 1
_RUNTIME_IDS = frozenset({"native", "docker_model_runner", "airllm"})


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field} must be bounded nonempty text")
    return value.strip()


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer in [{minimum}, {maximum}]")
    return value


def _finite(value: object, field: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)):
        raise ValueError(f"{field} must be finite")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{field} must be in [{minimum}, {maximum}]")
    return result


@dataclass(frozen=True, slots=True)
class ExternalRuntimePolicy:
    schema_version: str
    globally_enabled: bool
    normal_requests_may_download: bool
    normal_requests_may_prepare: bool
    docker_enabled: bool
    docker_loopback_origin: str
    docker_start_timeout_seconds: float
    docker_unload_timeout_seconds: float
    docker_pull_timeout_seconds: float
    docker_approved_engines: tuple[str, ...]
    airllm_enabled: bool
    airllm_concurrency: int
    airllm_start_timeout_seconds: float
    airllm_cancel_timeout_seconds: float
    airllm_approved_compression: tuple[str, ...]
    airllm_allow_prefetch: bool
    airllm_allow_prepare: bool
    cpu_heavy_slots: int
    max_ram_commit_bytes: int
    max_vram_commit_bytes: int
    gpu_exclusive: bool
    policy_sha256: str

    def validate(self) -> None:
        if self.schema_version != "px.external-runtime-policy/1.0":
            raise ValueError("unsupported external runtime policy")
        for name in (
            "globally_enabled", "normal_requests_may_download", "normal_requests_may_prepare",
            "docker_enabled", "airllm_enabled", "airllm_allow_prefetch", "airllm_allow_prepare", "gpu_exclusive",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"external runtime policy {name} must be boolean")
        if self.normal_requests_may_download or self.normal_requests_may_prepare or self.airllm_allow_prepare:
            raise ValueError("normal request paths may not download or prepare cold models")
        if not self.gpu_exclusive:
            raise ValueError("external GPU runtime policy must remain exclusive")
        origin = _text(self.docker_loopback_origin, "docker_loopback_origin", maximum=512)
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        ):
            raise ValueError("Docker external runtime origin must be literal loopback HTTP")
        for name, value in (
            ("docker_start_timeout_seconds", self.docker_start_timeout_seconds),
            ("docker_unload_timeout_seconds", self.docker_unload_timeout_seconds),
            ("docker_pull_timeout_seconds", self.docker_pull_timeout_seconds),
            ("airllm_start_timeout_seconds", self.airllm_start_timeout_seconds),
            ("airllm_cancel_timeout_seconds", self.airllm_cancel_timeout_seconds),
        ):
            _finite(value, name, 0.1, 86_400.0)
        _integer(self.airllm_concurrency, "airllm_concurrency", 1, 1)
        _integer(self.cpu_heavy_slots, "cpu_heavy_slots", 1, 64)
        _integer(self.max_ram_commit_bytes, "max_ram_commit_bytes", 0, _MAX_BYTES)
        _integer(self.max_vram_commit_bytes, "max_vram_commit_bytes", 0, _MAX_BYTES)
        if not self.docker_approved_engines or len(self.docker_approved_engines) > 16:
            raise ValueError("Docker engine allow-list must be bounded and nonempty")
        for item in self.docker_approved_engines:
            _text(item, "docker engine")
        if not self.airllm_approved_compression or len(self.airllm_approved_compression) > 8:
            raise ValueError("AirLLM compression allow-list must be bounded and nonempty")
        if any(item not in {"none", "4bit", "8bit"} for item in self.airllm_approved_compression):
            raise ValueError("unsupported AirLLM compression mode")
        body = asdict(self)
        body.pop("policy_sha256")
        if self.policy_sha256 != _sha(body):
            raise ValueError("external runtime policy digest is invalid")


def load_external_runtime_policy(root: Path) -> ExternalRuntimePolicy:
    reject_path_links(root)
    path = root / "models" / "external-runtime-policy.json"
    reject_path_links(path)
    raw = load_json_object(path, max_bytes=131_072)
    if set(raw) != {"schema_version", "authority", "docker", "airllm", "interlock"}:
        raise ValueError("external runtime policy fields are incomplete or unsupported")
    if raw["schema_version"] != "px.external-runtime-policy/1.0":
        raise ValueError("unsupported external runtime policy contract")
    authority, docker, airllm, interlock = (raw[k] for k in ("authority", "docker", "airllm", "interlock"))
    if any(type(v) is not dict for v in (authority, docker, airllm, interlock)):
        raise ValueError("external runtime policy sections must be objects")
    if set(authority) != {"globally_enabled", "normal_requests_may_download", "normal_requests_may_prepare", "runtime_does_not_route", "model_output_grants_no_authority"}:
        raise ValueError("external runtime authority policy fields are unsupported")
    if authority["runtime_does_not_route"] is not True or authority["model_output_grants_no_authority"] is not True:
        raise ValueError("external runtime policy weakens authority invariants")
    if set(docker) != {"enabled", "loopback_origin", "start_timeout_seconds", "unload_timeout_seconds", "pull_timeout_seconds", "approved_engines", "auto_pull", "use_docker_gateway_for_routing"}:
        raise ValueError("Docker external runtime policy fields are unsupported")
    if docker["auto_pull"] is not False or docker["use_docker_gateway_for_routing"] is not False:
        raise ValueError("Docker runtime may not auto-pull or own routing")
    if set(airllm) != {"enabled", "concurrency", "start_timeout_seconds", "cancel_timeout_seconds", "approved_compression", "allow_prefetch", "allow_prepare", "in_process_import"}:
        raise ValueError("AirLLM external runtime policy fields are unsupported")
    if airllm["in_process_import"] is not False:
        raise ValueError("AirLLM must not be imported into the PX broker process")
    if set(interlock) != {"cpu_heavy_slots", "max_ram_commit_bytes", "max_vram_commit_bytes", "gpu_exclusive", "release_requires_cleanup_proof"}:
        raise ValueError("external runtime interlock policy fields are unsupported")
    if interlock["release_requires_cleanup_proof"] is not True:
        raise ValueError("resource lease release must require cleanup proof")
    if type(docker["approved_engines"]) is not list or type(airllm["approved_compression"]) is not list:
        raise ValueError("external runtime allow-lists must be arrays")
    body = {
        "schema_version": raw["schema_version"],
        "globally_enabled": authority["globally_enabled"],
        "normal_requests_may_download": authority["normal_requests_may_download"],
        "normal_requests_may_prepare": authority["normal_requests_may_prepare"],
        "docker_enabled": docker["enabled"],
        "docker_loopback_origin": docker["loopback_origin"],
        "docker_start_timeout_seconds": docker["start_timeout_seconds"],
        "docker_unload_timeout_seconds": docker["unload_timeout_seconds"],
        "docker_pull_timeout_seconds": docker["pull_timeout_seconds"],
        "docker_approved_engines": tuple(docker["approved_engines"]),
        "airllm_enabled": airllm["enabled"],
        "airllm_concurrency": airllm["concurrency"],
        "airllm_start_timeout_seconds": airllm["start_timeout_seconds"],
        "airllm_cancel_timeout_seconds": airllm["cancel_timeout_seconds"],
        "airllm_approved_compression": tuple(airllm["approved_compression"]),
        "airllm_allow_prefetch": airllm["allow_prefetch"],
        "airllm_allow_prepare": airllm["allow_prepare"],
        "cpu_heavy_slots": interlock["cpu_heavy_slots"],
        "max_ram_commit_bytes": interlock["max_ram_commit_bytes"],
        "max_vram_commit_bytes": interlock["max_vram_commit_bytes"],
        "gpu_exclusive": interlock["gpu_exclusive"],
    }
    policy = ExternalRuntimePolicy(**body, policy_sha256=_sha(body))
    policy.validate()
    return policy


@dataclass(frozen=True, slots=True)
class ModelResourceNeed:
    runtime_id: str
    ram_bytes: int
    vram_bytes: int
    cpu_heavy: bool
    gpu_exclusive: bool

    def validate(self) -> None:
        if self.runtime_id not in _RUNTIME_IDS:
            raise ValueError("unsupported model runtime identity")
        _integer(self.ram_bytes, "ram_bytes", 0, _MAX_BYTES)
        _integer(self.vram_bytes, "vram_bytes", 0, _MAX_BYTES)
        if type(self.cpu_heavy) is not bool or type(self.gpu_exclusive) is not bool:
            raise ValueError("resource need booleans must be literal booleans")
        if self.vram_bytes and not self.gpu_exclusive:
            raise ValueError("VRAM claims must use the exclusive GPU interlock")


@dataclass(frozen=True, slots=True)
class ModelResourceLease:
    lease_id: str
    owner: str
    need: ModelResourceNeed
    acquired_monotonic: float
    need_sha256: str


class ModelResourceInterlock:
    """Small process-local coordinator; durable process custody stays ResourceManager-owned."""

    def __init__(
        self,
        *,
        max_ram_commit_bytes: int,
        max_vram_commit_bytes: int,
        cpu_heavy_slots: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_ram = _integer(max_ram_commit_bytes, "max_ram_commit_bytes", 0, _MAX_BYTES)
        self.max_vram = _integer(max_vram_commit_bytes, "max_vram_commit_bytes", 0, _MAX_BYTES)
        self.cpu_slots = _integer(cpu_heavy_slots, "cpu_heavy_slots", 1, 64)
        self.clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._leases: dict[str, ModelResourceLease] = {}

    def _now(self) -> float:
        return _finite(self.clock(), "resource interlock clock", 0.0, 1e18)

    def _available(self, need: ModelResourceNeed) -> bool:
        ram = sum(lease.need.ram_bytes for lease in self._leases.values())
        vram = sum(lease.need.vram_bytes for lease in self._leases.values())
        cpu = sum(lease.need.cpu_heavy for lease in self._leases.values())
        gpu_owned = any(lease.need.gpu_exclusive for lease in self._leases.values())
        return (
            ram + need.ram_bytes <= self.max_ram
            and vram + need.vram_bytes <= self.max_vram
            and cpu + int(need.cpu_heavy) <= self.cpu_slots
            and not (need.gpu_exclusive and gpu_owned)
        )

    def acquire(self, owner: str, need: ModelResourceNeed, *, timeout_seconds: float = 0.0) -> ModelResourceLease:
        owner = _text(owner, "resource lease owner")
        need.validate()
        timeout = _finite(timeout_seconds, "resource lease timeout", 0.0, 86_400.0)
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._available(need):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("model resource interlock capacity is unavailable")
                self._condition.wait(timeout=min(remaining, 0.25))
            acquired = self._now()
            lease = ModelResourceLease(
                lease_id=f"model-resource-lease-{uuid4().hex}", owner=owner, need=need,
                acquired_monotonic=acquired, need_sha256=_sha(asdict(need)),
            )
            self._leases[lease.lease_id] = lease
            return lease

    def release(self, lease_id: str, *, cleanup_proven: bool) -> ModelResourceLease:
        if type(cleanup_proven) is not bool or cleanup_proven is not True:
            raise PermissionError("resource lease release requires explicit cleanup proof")
        with self._condition:
            try:
                lease = self._leases.pop(lease_id)
            except KeyError as error:
                raise KeyError("unknown model resource lease") from error
            self._condition.notify_all()
            return lease

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            rows = [
                {
                    "lease_id": lease.lease_id,
                    "owner": lease.owner,
                    "runtime_id": lease.need.runtime_id,
                    "ram_bytes": lease.need.ram_bytes,
                    "vram_bytes": lease.need.vram_bytes,
                    "cpu_heavy": lease.need.cpu_heavy,
                    "gpu_exclusive": lease.need.gpu_exclusive,
                    "need_sha256": lease.need_sha256,
                }
                for lease in sorted(self._leases.values(), key=lambda item: item.lease_id)
            ]
            body = {"schema_version": "px.model-resource-interlock-snapshot/1.0", "leases": rows}
            return {**body, "snapshot_sha256": _sha(body)}
