"""Bounded model-route capacity and dropless backpressure primitives.

Capacity evidence can make a route wait or become ineligible, but it does not
select a model and it never grants load/start/execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping

from .json_io import validate_json_value

CAPACITY_STATES = frozenset({"admit", "wait", "deny"})


def _jsonable(value: object) -> object:
    if type(value) is tuple:
        return [_jsonable(item) for item in value]
    if type(value) is list:
        return [_jsonable(item) for item in value]
    if type(value) is dict:
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _canonical(value: object) -> bytes:
    value = _jsonable(value)
    validate_json_value(value, max_nodes=10_000)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite_nonnegative(value: object, name: str) -> float:
    if type(value) not in (int, float) or type(value) is bool:
        raise ValueError(f"{name} must be a bounded finite nonnegative number")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1e12:
        raise ValueError(f"{name} must be a bounded finite nonnegative number")
    return number


def _bounded_int(value: object, name: str, maximum: int = 1_000_000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be a bounded nonnegative integer")
    return value


def _text_or_none(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 256:
        raise ValueError(f"{name} must be bounded text or null")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ModelCapacitySnapshot:
    cpu_cores_total: float
    cpu_cores_available: float
    ram_gb_total: float
    ram_gb_available: float
    vram_gb_total: float
    vram_gb_available: float
    concurrent_slots_total: int
    concurrent_slots_available: int
    queue_depth: int
    max_queue_depth: int
    exclusive_model_id: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        for resource in ("cpu_cores", "ram_gb", "vram_gb"):
            total = _finite_nonnegative(getattr(self, f"{resource}_total"), f"{resource}_total")
            available = _finite_nonnegative(getattr(self, f"{resource}_available"), f"{resource}_available")
            if available > total:
                raise ValueError(f"{resource} available cannot exceed total")
        total_slots = _bounded_int(self.concurrent_slots_total, "concurrent_slots_total")
        available_slots = _bounded_int(self.concurrent_slots_available, "concurrent_slots_available")
        if total_slots < 1 or available_slots > total_slots:
            raise ValueError("concurrent slot capacity is invalid")
        _bounded_int(self.queue_depth, "queue_depth")
        maximum = _bounded_int(self.max_queue_depth, "max_queue_depth")
        if maximum < 1:
            raise ValueError("max_queue_depth must be positive")
        _text_or_none(self.exclusive_model_id, "exclusive_model_id")
        if self.source_sha256 is not None and (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("capacity source_sha256 must be lowercase SHA-256 or null")

    @property
    def snapshot_sha256(self) -> str:
        return _sha({"schema_version": "px.model-capacity-snapshot/1.0", **asdict(self)})

    @property
    def pressure(self) -> float:
        pressures = []
        for total, available in (
            (self.cpu_cores_total, self.cpu_cores_available),
            (self.ram_gb_total, self.ram_gb_available),
            (self.vram_gb_total, self.vram_gb_available),
        ):
            if total > 0:
                pressures.append(1.0 - available / total)
        pressures.append(1.0 - self.concurrent_slots_available / self.concurrent_slots_total)
        pressures.append(min(1.0, self.queue_depth / self.max_queue_depth))
        return round(max(0.0, min(1.0, max(pressures, default=0.0))), 9)


@dataclass(frozen=True, slots=True)
class ModelCapacityNeed:
    model_id: str
    cpu_cores: float = 0.0
    ram_gb: float = 0.0
    vram_gb: float = 0.0
    concurrent_slots: int = 1
    context_tokens: int = 0
    generation_tokens: int = 0
    exclusive: bool = False

    def __post_init__(self) -> None:
        if _text_or_none(self.model_id, "capacity need model_id") is None:
            raise ValueError("capacity need model_id must be bounded nonempty text")
        for name in ("cpu_cores", "ram_gb", "vram_gb"):
            _finite_nonnegative(getattr(self, name), f"capacity need {name}")
        slots = _bounded_int(self.concurrent_slots, "capacity need concurrent_slots")
        if slots < 1:
            raise ValueError("capacity need concurrent_slots must be positive")
        _bounded_int(self.context_tokens, "capacity need context_tokens", 2**31)
        _bounded_int(self.generation_tokens, "capacity need generation_tokens", 2**31)
        if type(self.exclusive) is not bool:
            raise ValueError("capacity need exclusive must be boolean")

    @property
    def need_sha256(self) -> str:
        return _sha({"schema_version": "px.model-capacity-need/1.0", **asdict(self)})


@dataclass(frozen=True, slots=True)
class ModelCapacityDecision:
    model_id: str
    state: str
    pressure: float
    reasons: tuple[str, ...]
    snapshot_sha256: str
    need_sha256: str
    no_drop: bool = True
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if _text_or_none(self.model_id, "capacity decision model_id") is None:
            raise ValueError("capacity decision model_id must be bounded nonempty text")
        if self.state not in CAPACITY_STATES:
            raise ValueError("unsupported model capacity state")
        pressure = _finite_nonnegative(self.pressure, "capacity decision pressure")
        if pressure > 1.0:
            raise ValueError("capacity pressure must be in [0,1]")
        if type(self.reasons) is not tuple or not self.reasons or len(self.reasons) > 32:
            raise ValueError("capacity decision requires bounded immutable reasons")
        for reason in self.reasons:
            if type(reason) is not str or not reason or len(reason.encode("utf-8")) > 256:
                raise ValueError("capacity decision reason is invalid")
        for name, digest in (("snapshot", self.snapshot_sha256), ("need", self.need_sha256)):
            if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError(f"capacity decision {name} identity is invalid")
        if self.no_drop is not True or self.authority_granted is not False:
            raise ValueError("capacity decision cannot grant authority or permit silent drop")

    @property
    def decision_sha256(self) -> str:
        return _sha({"schema_version": "px.model-capacity-decision/1.0", **asdict(self)})


def assess_model_capacity(snapshot: ModelCapacitySnapshot, need: ModelCapacityNeed) -> ModelCapacityDecision:
    """Return ADMIT/WAIT/DENY while preserving dropless semantics.

    ``DENY`` means the request can never fit the declared total envelope or an
    exclusivity rule makes the model ineligible.  Temporary pressure returns
    ``WAIT``; callers may choose a separately admitted fallback only when route
    policy explicitly allows that behavior.
    """

    if type(snapshot) is not ModelCapacitySnapshot or type(need) is not ModelCapacityNeed:
        raise ValueError("typed capacity snapshot and need are required")
    reasons: list[str] = []
    impossible = (
        need.cpu_cores > snapshot.cpu_cores_total
        or need.ram_gb > snapshot.ram_gb_total
        or need.vram_gb > snapshot.vram_gb_total
        or need.concurrent_slots > snapshot.concurrent_slots_total
    )
    if impossible:
        return ModelCapacityDecision(
            need.model_id, "deny", snapshot.pressure, ("request_exceeds_total_capacity",), snapshot.snapshot_sha256, need.need_sha256
        )
    if snapshot.exclusive_model_id is not None and snapshot.exclusive_model_id != need.model_id:
        return ModelCapacityDecision(
            need.model_id, "wait", snapshot.pressure, ("exclusive_model_lease_active",), snapshot.snapshot_sha256, need.need_sha256
        )
    if need.exclusive and snapshot.concurrent_slots_available != snapshot.concurrent_slots_total:
        reasons.append("exclusive_model_requires_idle_capacity")
    if need.cpu_cores > snapshot.cpu_cores_available:
        reasons.append("cpu_pressure")
    if need.ram_gb > snapshot.ram_gb_available:
        reasons.append("ram_pressure")
    if need.vram_gb > snapshot.vram_gb_available:
        reasons.append("vram_pressure")
    if need.concurrent_slots > snapshot.concurrent_slots_available:
        reasons.append("slot_pressure")
    if snapshot.queue_depth >= snapshot.max_queue_depth:
        reasons.append("route_queue_full")
    if reasons:
        return ModelCapacityDecision(
            need.model_id, "wait", snapshot.pressure, tuple(sorted(set(reasons))), snapshot.snapshot_sha256, need.need_sha256
        )
    return ModelCapacityDecision(
        need.model_id, "admit", snapshot.pressure, ("capacity_available",), snapshot.snapshot_sha256, need.need_sha256
    )


def capacity_decision_map(
    snapshot: ModelCapacitySnapshot,
    needs: Mapping[str, ModelCapacityNeed],
) -> dict[str, ModelCapacityDecision]:
    if type(needs) is not dict or len(needs) > 256:
        raise ValueError("capacity need map must be a bounded object")
    out: dict[str, ModelCapacityDecision] = {}
    for model_id, need in sorted(needs.items()):
        if type(model_id) is not str or type(need) is not ModelCapacityNeed or model_id != need.model_id:
            raise ValueError("capacity need map requires exact typed model identities")
        out[model_id] = assess_model_capacity(snapshot, need)
    return out
