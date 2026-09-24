"""Subordinate in-process model-pool state machine.

Durable lifecycle authority remains :mod:`runtime.local_model_runtime`.  This
module coordinates child-model load state and leases but intentionally owns no
process ledger and no model bytes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from .archive_io import reject_path_links
from .json_io import load_json_object
from uuid import uuid4

_POOL_STATES = frozenset({"unloaded", "loading", "loaded", "warm", "draining", "unloading", "failed"})
_RESIDENCIES = frozenset({"resident", "warm", "cold", "exclusive_cold"})
_ROUTER_LOADED = frozenset({"loaded", "sleeping"})
_ROUTER_UNLOADED = frozenset({"unloaded", "unknown"})


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"model pool {field} must be bounded nonempty text")
    return value.strip()


def _sha(value: object, field: str) -> str:
    value = _text(value, field, maximum=64)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"model pool {field} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ModelResourcePolicy:
    models_max: int
    reserved_cpu_cores: int
    control_max_concurrency: int
    embedding_max_concurrency: int
    reranker_max_concurrency: int
    system_ram_reserve_bytes: int
    vram_reserve_bytes: int
    exclusive_concurrency: int
    preferred_resident_model: str
    preferred_deep_candidate: str

    def validate(self) -> None:
        for name, value, maximum in (
            ("models_max", self.models_max, 64),
            ("reserved_cpu_cores", self.reserved_cpu_cores, 1024),
            ("control_max_concurrency", self.control_max_concurrency, 64),
            ("embedding_max_concurrency", self.embedding_max_concurrency, 64),
            ("reranker_max_concurrency", self.reranker_max_concurrency, 64),
            ("exclusive_concurrency", self.exclusive_concurrency, 64),
        ):
            minimum = 0 if name == "reserved_cpu_cores" else 1
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"model resource policy {name} is invalid")
        for name, value in (("system_ram_reserve_bytes", self.system_ram_reserve_bytes), ("vram_reserve_bytes", self.vram_reserve_bytes)):
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise ValueError(f"model resource policy {name} is invalid")
        _text(self.preferred_resident_model, "preferred_resident_model")
        _text(self.preferred_deep_candidate, "preferred_deep_candidate")


def load_model_resource_policy(root: Path) -> ModelResourcePolicy:
    reject_path_links(root)
    path = root / "models" / "resource-policy.json"
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=131_072)
    if set(payload) != {"schema_version", "router", "cpu", "memory", "residency", "heavy", "authority"} or payload["schema_version"] != "px.model-resource-policy/1.0":
        raise ValueError("unsupported model resource policy contract")
    router, cpu, memory, residency, heavy, authority = (payload[name] for name in ("router", "cpu", "memory", "residency", "heavy", "authority"))
    if any(type(item) is not dict for item in (router, cpu, memory, residency, heavy, authority)):
        raise ValueError("model resource policy sections must be objects")
    if set(router) != {"models_max", "autoload", "loopback_only", "metrics_required", "slots_required", "ui_enabled"}:
        raise ValueError("model router resource policy fields are unsupported")
    if set(cpu) != {"reserved_logical_cores_min", "control_max_concurrency", "embedding_max_concurrency", "reranker_max_concurrency", "benchmark_before_parallelism_increase", "operator_must_not_starve_retrieval_or_extension_host"}:
        raise ValueError("model CPU resource policy fields are unsupported")
    if set(memory) != {"system_ram_reserve_bytes", "vram_reserve_bytes", "measured_peak_required_for_certification", "file_size_is_not_runtime_ram"}:
        raise ValueError("model memory resource policy fields are unsupported")
    if set(residency) != {"startup_required_lanes", "preferred_resident_model", "resident_never_idle_evict", "warm_requires_idle_timeout", "cold_requires_deadline_preflight", "failed_swap_must_reconcile"}:
        raise ValueError("model residency policy fields are unsupported")
    if set(heavy) != {"exclusive_concurrency", "drain_before_unload", "prove_release_before_lease_release", "preferred_deep_candidate"}:
        raise ValueError("model heavy resource policy fields are unsupported")
    if set(authority) != {"model_request_does_not_grant_load", "load_unload_requires_effect_authority", "models_do_not_own_resource_policy", "models_do_not_self_promote"}:
        raise ValueError("model authority resource policy fields are unsupported")
    required_true = [
        router["loopback_only"], router["metrics_required"], router["slots_required"],
        cpu["benchmark_before_parallelism_increase"], cpu["operator_must_not_starve_retrieval_or_extension_host"],
        memory["measured_peak_required_for_certification"], memory["file_size_is_not_runtime_ram"],
        residency["resident_never_idle_evict"], residency["warm_requires_idle_timeout"], residency["cold_requires_deadline_preflight"], residency["failed_swap_must_reconcile"],
        heavy["drain_before_unload"], heavy["prove_release_before_lease_release"],
        authority["model_request_does_not_grant_load"], authority["load_unload_requires_effect_authority"], authority["models_do_not_own_resource_policy"], authority["models_do_not_self_promote"],
    ]
    if router["autoload"] is not False or router["ui_enabled"] is not False or any(value is not True for value in required_true):
        raise ValueError("model resource policy weakens a required governed invariant")
    lanes = residency["startup_required_lanes"]
    if type(lanes) is not list or lanes != ["control"]:
        raise ValueError("startup model lanes must require only the bounded control lane at this stage")
    policy = ModelResourcePolicy(
        models_max=router["models_max"], reserved_cpu_cores=cpu["reserved_logical_cores_min"],
        control_max_concurrency=cpu["control_max_concurrency"], embedding_max_concurrency=cpu["embedding_max_concurrency"],
        reranker_max_concurrency=cpu["reranker_max_concurrency"], system_ram_reserve_bytes=memory["system_ram_reserve_bytes"],
        vram_reserve_bytes=memory["vram_reserve_bytes"], exclusive_concurrency=heavy["exclusive_concurrency"],
        preferred_resident_model=residency["preferred_resident_model"], preferred_deep_candidate=heavy["preferred_deep_candidate"],
    )
    policy.validate()
    return policy


@dataclass(frozen=True, slots=True)
class PoolModelSpec:
    model_id: str
    profile_id: str
    model_sha256: str
    profile_sha256: str
    residency: str
    idle_evict_seconds: int | None
    exclusive_group: str | None = None

    def validate(self) -> None:
        _text(self.model_id, "model_id")
        _text(self.profile_id, "profile_id")
        _sha(self.model_sha256, "model_sha256")
        _sha(self.profile_sha256, "profile_sha256")
        if self.residency not in _RESIDENCIES:
            raise ValueError("unsupported model-pool residency")
        if self.idle_evict_seconds is not None and (
            type(self.idle_evict_seconds) is not int or not 0 <= self.idle_evict_seconds <= 7 * 24 * 60 * 60
        ):
            raise ValueError("idle eviction must be a bounded nonnegative integer or null")
        if self.residency == "resident" and self.idle_evict_seconds is not None:
            raise ValueError("resident pool models cannot have idle eviction")
        if self.exclusive_group is not None:
            _text(self.exclusive_group, "exclusive_group")


@dataclass(frozen=True, slots=True)
class PoolLease:
    lease_id: str
    model_id: str
    owner: str
    acquired_monotonic: float


@dataclass(frozen=True, slots=True)
class PoolEntry:
    spec: PoolModelSpec
    state: str = "unloaded"
    active_leases: tuple[str, ...] = ()
    last_used_monotonic: float | None = None
    last_error: str | None = None

    def validate(self) -> None:
        self.spec.validate()
        if self.state not in _POOL_STATES:
            raise ValueError("unsupported model-pool state")
        if len(self.active_leases) > 1024 or len(set(self.active_leases)) != len(self.active_leases):
            raise ValueError("invalid model-pool lease set")
        if self.last_used_monotonic is not None and (
            type(self.last_used_monotonic) not in (int, float)
            or type(self.last_used_monotonic) is bool
            or not math.isfinite(self.last_used_monotonic)
            or self.last_used_monotonic < 0
        ):
            raise ValueError("invalid model-pool last-used clock value")
        if self.last_error is not None and (type(self.last_error) is not str or len(self.last_error.encode("utf-8")) > 2048):
            raise ValueError("model-pool error text exceeds the bound")


class ModelPool:
    """Thread-safe child-model coordinator with explicit load/unload callbacks."""

    def __init__(
        self,
        specs: tuple[PoolModelSpec, ...],
        *,
        load_model: Callable[[str], str],
        unload_model: Callable[[str], str],
        observe_models: Callable[[], Mapping[str, str]],
        event_sink: Callable[[str, Mapping[str, object]], object] | None = None,
        max_loaded_models: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_loaded_models) is not int or not 1 <= max_loaded_models <= 64:
            raise ValueError("max_loaded_models must be in [1, 64]")
        if not specs or len(specs) > 128:
            raise ValueError("model pool requires a bounded nonempty model set")
        entries: dict[str, PoolEntry] = {}
        for spec in specs:
            if type(spec) is not PoolModelSpec:
                raise ValueError("typed pool model specifications are required")
            spec.validate()
            if spec.model_id in entries:
                raise ValueError("duplicate model-pool model identity")
            entries[spec.model_id] = PoolEntry(spec)
        self._entries = entries
        self._leases: dict[str, PoolLease] = {}
        self._load_model = load_model
        self._unload_model = unload_model
        self._observe_models = observe_models
        self._event_sink = event_sink
        self._max_loaded = max_loaded_models
        self._clock = clock
        self._lock = threading.RLock()

    def _emit(self, event_type: str, payload: Mapping[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, dict(payload))

    def snapshot(self) -> tuple[PoolEntry, ...]:
        with self._lock:
            return tuple(self._entries[key] for key in sorted(self._entries))

    def entry(self, model_id: str) -> PoolEntry:
        model_id = _text(model_id, "model_id")
        with self._lock:
            try:
                return self._entries[model_id]
            except KeyError as error:
                raise KeyError(model_id) from error

    def _set(self, model_id: str, **changes: object) -> PoolEntry:
        entry = replace(self._entries[model_id], **changes)
        entry.validate()
        self._entries[model_id] = entry
        return entry

    def _now(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value) or value < 0:
            raise RuntimeError("model pool clock returned an invalid value")
        return float(value)

    def _loaded_count(self) -> int:
        return sum(1 for item in self._entries.values() if item.state in {"loading", "loaded", "warm", "draining", "unloading", "failed"})

    def _exclusive_conflict(self, spec: PoolModelSpec) -> str | None:
        if spec.exclusive_group is None:
            return None
        for model_id, entry in self._entries.items():
            if model_id == spec.model_id or entry.spec.exclusive_group != spec.exclusive_group:
                continue
            if entry.state in {"loading", "loaded", "warm", "draining", "unloading", "failed"}:
                return model_id
        return None

    def ensure_loaded(self, model_id: str, *, supplied_authority: bool) -> PoolEntry:
        model_id = _text(model_id, "model_id")
        if type(supplied_authority) is not bool:
            raise ValueError("model-pool authority flag must be boolean")
        with self._lock:
            entry = self.entry(model_id)
            if entry.state in {"loaded", "warm"}:
                return entry
            if supplied_authority is not True:
                raise PermissionError("explicit model-load authority is required")
            if entry.state == "draining":
                raise RuntimeError(f"model {model_id} is draining")
            if entry.state in {"loading", "unloading"}:
                raise RuntimeError(f"model {model_id} is in transition")
            conflict = self._exclusive_conflict(entry.spec)
            if conflict is not None:
                raise RuntimeError(f"exclusive model group is occupied by {conflict}")
            if self._loaded_count() >= self._max_loaded:
                self.evict_idle(supplied_authority=True, now=self._now(), require_one=True)
            if self._loaded_count() >= self._max_loaded:
                raise RuntimeError("model pool capacity is exhausted")
            transition_time = self._now()
            self._set(model_id, state="loading", last_error=None)
            self._emit("model_load_requested", {"model_id": model_id, "profile_id": entry.spec.profile_id})
            try:
                observed = _text(self._load_model(model_id), "router_state")
                if observed not in _ROUTER_LOADED:
                    raise RuntimeError(f"router reported non-loaded state {observed}")
            except BaseException as error:
                self._set(model_id, state="failed", last_error=f"{type(error).__name__}: {error}"[:2048])
                self._emit("model_load_failed", {"model_id": model_id, "error": type(error).__name__})
                raise
            current = self._set(model_id, state="warm", last_used_monotonic=transition_time)
            self._emit("model_loaded", {"model_id": model_id, "profile_id": entry.spec.profile_id, "router_state": observed})
            return current

    def acquire(self, model_id: str, *, owner: str, supplied_authority: bool) -> PoolLease:
        model_id = _text(model_id, "model_id")
        owner = _text(owner, "owner")
        if type(supplied_authority) is not bool:
            raise ValueError("model-pool authority flag must be boolean")
        with self._lock:
            current = self.entry(model_id)
            if current.state not in {"loaded", "warm"} and supplied_authority is not True:
                raise PermissionError("explicit model-load authority is required")
            entry = self.ensure_loaded(model_id, supplied_authority=supplied_authority)
            if entry.state == "draining":
                raise RuntimeError(f"model {model_id} is draining")
            now = self._now()
            lease = PoolLease(f"model-lease-{uuid4().hex}", model_id, owner, float(now))
            self._leases[lease.lease_id] = lease
            leases = tuple(sorted((*entry.active_leases, lease.lease_id)))
            self._set(model_id, state="loaded", active_leases=leases, last_used_monotonic=float(now))
            self._emit("model_lease_acquired", {"lease_id": lease.lease_id, "model_id": model_id, "owner": owner})
            return lease

    def release(self, lease: PoolLease) -> PoolEntry:
        if type(lease) is not PoolLease:
            raise ValueError("typed model-pool lease is required")
        with self._lock:
            current = self._leases.get(lease.lease_id)
            if current != lease:
                raise ValueError("model-pool lease mismatch or already released")
            entry = self.entry(lease.model_id)
            if lease.lease_id not in entry.active_leases:
                raise ValueError("model-pool lease is not attached to the model")
            now = self._now()
            del self._leases[lease.lease_id]
            leases = tuple(item for item in entry.active_leases if item != lease.lease_id)
            if entry.state == "draining":
                next_state = "draining"
            elif entry.state == "failed":
                next_state = "failed"
            else:
                next_state = "loaded" if leases else "warm"
            updated = self._set(lease.model_id, state=next_state, active_leases=leases, last_used_monotonic=float(now))
            self._emit("model_lease_released", {"lease_id": lease.lease_id, "model_id": lease.model_id, "owner": lease.owner})
            if updated.state == "draining" and not updated.active_leases:
                return self._unload_no_leases(lease.model_id)
            return updated

    def drain(self, model_id: str, *, supplied_authority: bool) -> PoolEntry:
        model_id = _text(model_id, "model_id")
        if supplied_authority is not True:
            raise PermissionError("explicit model-drain authority is required")
        with self._lock:
            entry = self.entry(model_id)
            if entry.state == "unloaded":
                return entry
            if entry.state in {"loading", "unloading"}:
                raise RuntimeError(f"model {model_id} is in transition")
            entry = self._set(model_id, state="draining")
            self._emit("model_draining", {"model_id": model_id, "active_leases": len(entry.active_leases)})
            return self._unload_no_leases(model_id) if not entry.active_leases else entry

    def _unload_no_leases(self, model_id: str) -> PoolEntry:
        entry = self.entry(model_id)
        if entry.active_leases:
            raise RuntimeError("cannot unload a model with active leases")
        if entry.state == "unloaded":
            return entry
        transition_time = self._now()
        self._set(model_id, state="unloading")
        self._emit("model_unload_requested", {"model_id": model_id, "profile_id": entry.spec.profile_id})
        try:
            observed = _text(self._unload_model(model_id), "router_state")
            if observed not in _ROUTER_UNLOADED:
                raise RuntimeError(f"router reported non-unloaded state {observed}")
        except BaseException as error:
            self._set(model_id, state="failed", last_error=f"{type(error).__name__}: {error}"[:2048])
            self._emit("model_unload_failed", {"model_id": model_id, "error": type(error).__name__})
            raise
        result = self._set(model_id, state="unloaded", last_used_monotonic=transition_time, last_error=None)
        self._emit("model_unloaded", {"model_id": model_id, "profile_id": entry.spec.profile_id, "router_state": observed})
        return result

    def unload(self, model_id: str, *, supplied_authority: bool) -> PoolEntry:
        model_id = _text(model_id, "model_id")
        if supplied_authority is not True:
            raise PermissionError("explicit model-unload authority is required")
        with self._lock:
            return self._unload_no_leases(model_id)

    def evict_idle(self, *, supplied_authority: bool, now: float | None = None, require_one: bool = False) -> tuple[str, ...]:
        if supplied_authority is not True:
            raise PermissionError("explicit idle-eviction authority is required")
        with self._lock:
            if now is None:
                now = self._now()
            elif type(now) not in (int, float) or type(now) is bool or not math.isfinite(now) or now < 0:
                raise ValueError("idle-eviction clock value must be bounded and finite")
            else:
                now = float(now)
            candidates: list[tuple[float, str]] = []
            for model_id, entry in self._entries.items():
                if entry.state != "warm" or entry.active_leases or entry.spec.residency == "resident":
                    continue
                idle_limit = entry.spec.idle_evict_seconds
                last_used = entry.last_used_monotonic
                if idle_limit is None or last_used is None:
                    continue
                if float(now) - last_used >= idle_limit:
                    candidates.append((last_used, model_id))
            evicted: list[str] = []
            for _last_used, model_id in sorted(candidates):
                self._unload_no_leases(model_id)
                evicted.append(model_id)
                if require_one:
                    break
            return tuple(evicted)

    def reconcile(self) -> tuple[PoolEntry, ...]:
        with self._lock:
            observed_raw = self._observe_models()
            if not isinstance(observed_raw, Mapping) or len(observed_raw) > 256:
                raise ValueError("router model observation must be a bounded mapping")
            observed: dict[str, str] = {}
            for key, value in observed_raw.items():
                if type(key) is not str or not key.strip() or len(key.encode("utf-8")) > 256:
                    raise ValueError("router model observation contains an invalid model ID")
                if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 64:
                    raise ValueError("router model observation contains an invalid state")
                if key in observed:
                    raise ValueError("router model observation contains a duplicate model ID")
                observed[key] = value.strip().lower()
            for model_id, entry in tuple(self._entries.items()):
                router_state = observed.get(model_id, "unloaded")
                if router_state in _ROUTER_LOADED:
                    if entry.state in {"unloaded", "failed"}:
                        target = "loaded" if entry.active_leases else "warm"
                        self._set(model_id, state=target, last_used_monotonic=self._now(), last_error=None)
                        self._emit("model_reconciled_loaded", {"model_id": model_id, "router_state": router_state, "state": target})
                elif router_state in _ROUTER_UNLOADED:
                    if entry.active_leases:
                        self._set(model_id, state="failed", last_error="router lost a model with active leases")
                        self._emit("model_reconcile_failed", {"model_id": model_id, "reason": "active_lease_model_absent"})
                    elif entry.state != "unloaded":
                        self._set(model_id, state="unloaded", last_error=None)
                        self._emit("model_reconciled_unloaded", {"model_id": model_id, "router_state": router_state})
                else:
                    self._set(model_id, state="failed", last_error=f"unsupported router state {router_state}"[:2048])
                    self._emit("model_reconcile_failed", {"model_id": model_id, "reason": "unsupported_router_state"})
            return self.snapshot()
