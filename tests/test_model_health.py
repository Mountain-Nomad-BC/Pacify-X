from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.model_health import normalize_model_health


def _payload(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "model_id": "qwen35-4b-operator",
        "profile_id": "control-qwen35-4b-cpu-q6",
        "fabric_generation_id": "a" * 64,
        "state": "loaded",
        "health": "healthy",
        "accepting_requests": True,
        "active_requests": 0,
        "queue_depth": 0,
        "rss_bytes": 900_000_000,
        "vram_bytes": 0,
        "p95_latency_ms": 42.5,
        "observed_at": "2026-09-20T12:00:00+00:00",
        "error": None,
    }
    base.update(changes)
    return base


def test_health_snapshot_is_digest_bound_and_route_eligibility_is_explicit() -> None:
    snapshot = normalize_model_health(_payload())
    assert snapshot.route_eligible is True
    assert len(snapshot.snapshot_sha256) == 64
    degraded = normalize_model_health(_payload(health="degraded"))
    assert degraded.route_eligible is False
    warm = normalize_model_health(_payload(state="warm"))
    assert warm.route_eligible is True


def test_health_rejects_loose_numeric_boolean_nan_and_unknown_state() -> None:
    for changes, match in (
        ({"queue_depth": True}, "queue_depth"),
        ({"p95_latency_ms": float("nan")}, "p95_latency_ms"),
        ({"rss_bytes": -1}, "rss_bytes"),
        ({"state": "teleported"}, "state/health"),
        ({"fabric_generation_id": "short"}, "generation"),
        ({"observed_at": "2026-09-20T12:00:00"}, "timezone-aware"),
    ):
        with pytest.raises(ValueError, match=match):
            normalize_model_health(_payload(**changes))


def test_health_digest_tampering_is_detected() -> None:
    snapshot = normalize_model_health(_payload())
    with pytest.raises(ValueError, match="digest"):
        replace(snapshot, queue_depth=1).validate()
