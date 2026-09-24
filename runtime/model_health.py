"""Read-only normalization for local model and router health evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping

MAX_ERROR_BYTES = 2048
_HEALTH = frozenset({"healthy", "degraded", "unavailable", "unknown"})
_STATES = frozenset({"unloaded", "loading", "loaded", "warm", "draining", "unloading", "failed", "unknown"})


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"model health {field} must be bounded nonempty text")
    return value.strip()




def _timestamp(value: object) -> str:
    text = _text(value, "observed_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("model health observed_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("model health observed_at must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()

def _count(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError(f"model health {field} must be a bounded nonnegative integer")
    return value


def _metric(value: object, field: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value) or value < 0 or value > 1e12:
        raise ValueError(f"model health {field} must be a bounded finite nonnegative number")
    return float(value)


@dataclass(frozen=True, slots=True)
class ModelHealthSnapshot:
    schema_version: str
    model_id: str
    profile_id: str
    fabric_generation_id: str | None
    state: str
    health: str
    accepting_requests: bool
    active_requests: int
    queue_depth: int
    rss_bytes: int | None
    vram_bytes: int | None
    p95_latency_ms: float | None
    observed_at: str
    error: str | None
    snapshot_sha256: str

    @property
    def route_eligible(self) -> bool:
        return self.health == "healthy" and self.accepting_requests and self.state in {"loaded", "warm"}

    def identity_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("snapshot_sha256")
        return payload

    def validate(self) -> None:
        if self.schema_version != "px.model-health/1.0":
            raise ValueError("unsupported model health schema")
        _text(self.model_id, "model_id")
        _text(self.profile_id, "profile_id")
        if self.fabric_generation_id is not None:
            value = _text(self.fabric_generation_id, "fabric_generation_id", maximum=64)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("fabric generation identity must be lowercase SHA-256")
        if self.state not in _STATES or self.health not in _HEALTH:
            raise ValueError("unsupported model state/health value")
        if type(self.accepting_requests) is not bool:
            raise ValueError("model health accepting_requests must be boolean")
        _count(self.active_requests, "active_requests")
        _count(self.queue_depth, "queue_depth")
        for field in ("rss_bytes", "vram_bytes"):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
                raise ValueError(f"model health {field} must be a bounded nonnegative integer")
        _metric(self.p95_latency_ms, "p95_latency_ms")
        _timestamp(self.observed_at)
        if self.error is not None and (type(self.error) is not str or len(self.error.encode("utf-8")) > MAX_ERROR_BYTES):
            raise ValueError("model health error exceeds the bounded text contract")
        expected = hashlib.sha256(_canonical(self.identity_payload())).hexdigest()
        if self.snapshot_sha256 != expected:
            raise ValueError("model health snapshot digest is invalid")


def normalize_model_health(payload: Mapping[str, object]) -> ModelHealthSnapshot:
    required = {
        "model_id", "profile_id", "fabric_generation_id", "state", "health",
        "accepting_requests", "active_requests", "queue_depth", "rss_bytes", "vram_bytes",
        "p95_latency_ms", "observed_at", "error",
    }
    if type(payload) is not dict or set(payload) != required:
        raise ValueError("model health payload fields are incomplete or unsupported")
    generation = payload["fabric_generation_id"]
    if generation is not None and type(generation) is not str:
        raise ValueError("fabric generation identity must be text or null")
    error = payload["error"]
    if error is not None and type(error) is not str:
        raise ValueError("model health error must be text or null")
    body = {
        "schema_version": "px.model-health/1.0",
        "model_id": _text(payload["model_id"], "model_id"),
        "profile_id": _text(payload["profile_id"], "profile_id"),
        "fabric_generation_id": generation,
        "state": _text(payload["state"], "state"),
        "health": _text(payload["health"], "health"),
        "accepting_requests": payload["accepting_requests"],
        "active_requests": _count(payload["active_requests"], "active_requests"),
        "queue_depth": _count(payload["queue_depth"], "queue_depth"),
        "rss_bytes": payload["rss_bytes"],
        "vram_bytes": payload["vram_bytes"],
        "p95_latency_ms": _metric(payload["p95_latency_ms"], "p95_latency_ms"),
        "observed_at": _timestamp(payload["observed_at"]),
        "error": error,
    }
    snapshot = ModelHealthSnapshot(**body, snapshot_sha256=hashlib.sha256(_canonical(body)).hexdigest())
    snapshot.validate()
    return snapshot
