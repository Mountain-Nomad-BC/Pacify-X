"""Typed, immutable local-model runtime profiles.

Profiles describe *how* an already admitted model may run.  They are data only:
model bytes remain outside Pacify-X, and a profile never grants authority to load,
route, call tools, write memory, or perform network work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping

from .archive_io import reject_path_links
from .json_io import load_json_object

MAX_PROFILES = 128
MAX_TEXT_BYTES = 256
_HEX = frozenset("0123456789abcdef")
_PROFILE_STATES = frozenset({"candidate", "certified", "retired"})
_RESIDENCIES = frozenset({"resident", "warm", "cold", "exclusive_cold"})
_LANES = frozenset({"control", "embedding", "reranker", "fast", "balanced", "deep", "specialist"})
_RUNTIMES = frozenset({"llama_cpp_router"})


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, field: str, *, allowed: frozenset[str] | None = None) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"model profile {field} must be bounded nonempty text")
    value = value.strip()
    if allowed is not None and value not in allowed:
        raise ValueError(f"unsupported model profile {field}: {value}")
    return value


def _integer(value: object, field: str, minimum: int, maximum: int, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"model profile {field} must be an integer in [{minimum}, {maximum}]")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"model profile {field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class ModelRuntimeProfile:
    schema_version: str
    profile_id: str
    model_id: str
    lane: str
    runtime: str
    state: str
    residency: str
    context_tokens: int
    max_output_tokens: int
    parallel_slots: int
    threads: int | None
    threads_batch: int | None
    batch_size: int
    ubatch_size: int
    gpu_layers: int | None
    cpu_moe_layers: int | None
    flash_attention: bool
    reasoning: bool
    prompt_cache: bool
    text_only: bool
    idle_evict_seconds: int | None
    exclusive_heavy: bool
    benchmark_required: bool
    profile_sha256: str

    @property
    def is_certified(self) -> bool:
        return self.state == "certified"

    @property
    def cpu_only(self) -> bool:
        return self.gpu_layers == 0

    def identity_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("profile_sha256")
        return payload

    def validate(self) -> None:
        if self.schema_version != "px.model-runtime-profile/1.0":
            raise ValueError("unsupported model runtime profile schema")
        _text(self.profile_id, "profile_id")
        _text(self.model_id, "model_id")
        _text(self.lane, "lane", allowed=_LANES)
        _text(self.runtime, "runtime", allowed=_RUNTIMES)
        _text(self.state, "state", allowed=_PROFILE_STATES)
        _text(self.residency, "residency", allowed=_RESIDENCIES)
        _integer(self.context_tokens, "context_tokens", 128, 1_048_576)
        _integer(self.max_output_tokens, "max_output_tokens", 1, 1_048_576)
        _integer(self.parallel_slots, "parallel_slots", 1, 64)
        _integer(self.threads, "threads", 1, 1024, optional=True)
        _integer(self.threads_batch, "threads_batch", 1, 1024, optional=True)
        _integer(self.batch_size, "batch_size", 1, 1_048_576)
        _integer(self.ubatch_size, "ubatch_size", 1, self.batch_size)
        _integer(self.gpu_layers, "gpu_layers", 0, 100_000, optional=True)
        _integer(self.cpu_moe_layers, "cpu_moe_layers", 0, 100_000, optional=True)
        _integer(self.idle_evict_seconds, "idle_evict_seconds", 0, 7 * 24 * 60 * 60, optional=True)
        for field in ("flash_attention", "reasoning", "prompt_cache", "text_only", "exclusive_heavy", "benchmark_required"):
            _boolean(getattr(self, field), field)
        if self.max_output_tokens > self.context_tokens:
            raise ValueError("model max output cannot exceed certified context")
        if self.residency == "resident" and self.idle_evict_seconds is not None:
            raise ValueError("resident model profiles cannot have idle eviction")
        if self.exclusive_heavy and self.residency not in {"cold", "exclusive_cold"}:
            raise ValueError("exclusive-heavy profiles must be cold")
        if self.lane == "control":
            if self.gpu_layers not in {0, None}:
                raise ValueError("control-lane profiles are CPU-only")
            if self.reasoning:
                raise ValueError("control-lane reasoning must remain disabled")
            if not self.text_only:
                raise ValueError("control-lane profile must be text-only")
        if self.state == "certified":
            if self.threads is None or self.threads_batch is None or self.gpu_layers is None:
                raise ValueError("certified profiles require frozen thread/GPU placement")
            if self.benchmark_required:
                raise ValueError("certified profile cannot remain benchmark-required")
        expected = _sha(self.identity_payload())
        if self.profile_sha256 != expected:
            raise ValueError("model runtime profile identity digest is invalid")


def runtime_profile_from_mapping(payload: Mapping[str, object]) -> ModelRuntimeProfile:
    required = {
        "schema_version", "profile_id", "model_id", "lane", "runtime", "state", "residency",
        "context_tokens", "max_output_tokens", "parallel_slots", "threads", "threads_batch",
        "batch_size", "ubatch_size", "gpu_layers", "cpu_moe_layers", "flash_attention",
        "reasoning", "prompt_cache", "text_only", "idle_evict_seconds", "exclusive_heavy",
        "benchmark_required",
    }
    if type(payload) is not dict or set(payload) != required:
        raise ValueError("model runtime profile fields are incomplete or unsupported")
    body = dict(payload)
    profile = ModelRuntimeProfile(
        schema_version=_text(body["schema_version"], "schema_version"),
        profile_id=_text(body["profile_id"], "profile_id"),
        model_id=_text(body["model_id"], "model_id"),
        lane=_text(body["lane"], "lane", allowed=_LANES),
        runtime=_text(body["runtime"], "runtime", allowed=_RUNTIMES),
        state=_text(body["state"], "state", allowed=_PROFILE_STATES),
        residency=_text(body["residency"], "residency", allowed=_RESIDENCIES),
        context_tokens=_integer(body["context_tokens"], "context_tokens", 128, 1_048_576),  # type: ignore[arg-type]
        max_output_tokens=_integer(body["max_output_tokens"], "max_output_tokens", 1, 1_048_576),  # type: ignore[arg-type]
        parallel_slots=_integer(body["parallel_slots"], "parallel_slots", 1, 64),  # type: ignore[arg-type]
        threads=_integer(body["threads"], "threads", 1, 1024, optional=True),
        threads_batch=_integer(body["threads_batch"], "threads_batch", 1, 1024, optional=True),
        batch_size=_integer(body["batch_size"], "batch_size", 1, 1_048_576),  # type: ignore[arg-type]
        ubatch_size=_integer(body["ubatch_size"], "ubatch_size", 1, 1_048_576),  # type: ignore[arg-type]
        gpu_layers=_integer(body["gpu_layers"], "gpu_layers", 0, 100_000, optional=True),
        cpu_moe_layers=_integer(body["cpu_moe_layers"], "cpu_moe_layers", 0, 100_000, optional=True),
        flash_attention=_boolean(body["flash_attention"], "flash_attention"),
        reasoning=_boolean(body["reasoning"], "reasoning"),
        prompt_cache=_boolean(body["prompt_cache"], "prompt_cache"),
        text_only=_boolean(body["text_only"], "text_only"),
        idle_evict_seconds=_integer(body["idle_evict_seconds"], "idle_evict_seconds", 0, 7 * 24 * 60 * 60, optional=True),
        exclusive_heavy=_boolean(body["exclusive_heavy"], "exclusive_heavy"),
        benchmark_required=_boolean(body["benchmark_required"], "benchmark_required"),
        profile_sha256="",
    )
    profile = ModelRuntimeProfile(**{**asdict(profile), "profile_sha256": _sha(profile.identity_payload())})
    profile.validate()
    return profile


def load_runtime_profiles(root: Path) -> tuple[ModelRuntimeProfile, ...]:
    reject_path_links(root)
    path = root / "models" / "runtime-profiles.json"
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=262_144)
    if set(payload) != {"schema_version", "profiles"} or payload["schema_version"] != "px.model-runtime-profiles/1.0":
        raise ValueError("unsupported runtime profile registry contract")
    rows = payload["profiles"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_PROFILES:
        raise ValueError("runtime profile registry requires a bounded nonempty profile list")
    profiles = tuple(runtime_profile_from_mapping(row) for row in rows)
    profile_ids = [item.profile_id for item in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("duplicate runtime profile identity")
    return profiles
