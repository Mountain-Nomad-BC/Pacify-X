from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from runtime.contracts import validate_instance
from runtime.operational_visibility import (
    OPERATION_EVENT_SCHEMA,
    ROUTE_REGISTRY_SCHEMA,
    validate_operation_event,
    validate_route_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def _event() -> dict[str, object]:
    return {
        "schema_version": "px.operation-event/1",
        "event_id": "evt-1",
        "correlation_id": "corr-1",
        "parent_correlation_id": None,
        "actor": {"actor_id": "runtime", "actor_kind": "runtime", "session_id": "s1", "harness": "pytest", "accountable_owner": "pacify-x"},
        "work": {"project_id": "pacify-x", "task_id": "F05", "claim_id": None, "orchestration_id": None},
        "source": {"route_id": "runtime.cli", "component": "runtime.cli", "host_id": None, "coverage_tier": "C"},
        "operation": {"name": "validate", "lifecycle": "completed", "result": "success"},
        "effects": {"declared": ["read"], "observed": ["read"], "scope_refs": ["project:pacify-x"]},
        "provider": None,
        "time": {"observed_at": "2026-08-11T18:00:00Z", "started_at": "2026-08-11T17:59:59Z", "duration_ms": 1000, "freshness": "live"},
        "integrity": {"input_sha256": None, "output_sha256": "a" * 64, "previous_event_sha256": None},
        "capture": {"classification": "metadata_only", "payload_included": False},
    }


def test_shipped_visibility_contracts_and_registry_are_valid() -> None:
    validate_instance(_event(), ROOT / OPERATION_EVENT_SCHEMA)
    registry = json.loads((ROOT / "registry/operation_route_registry.json").read_text(encoding="utf-8"))
    validate_instance(registry, ROOT / ROUTE_REGISTRY_SCHEMA)
    report = validate_route_registry(ROOT)
    assert report["valid"] is True
    assert report["route_count"] == 14
    assert report["certifiable"] is True
    assert report["tiers"] == {"A": 2, "B": 4, "C": 6, "D": 2}
    assert report["tier_d_advertised"] == []


def test_event_rejects_unapproved_payload_capture() -> None:
    event = _event()
    event["capture"] = {"classification": "metadata_only", "payload_included": True}
    report = validate_operation_event(ROOT, event)
    assert report["valid"] is False
    assert "content_authorized" in report["errors"][-1]


def test_registry_rejects_dishonest_tier_pairing(tmp_path: Path) -> None:
    registry = json.loads((ROOT / "registry/operation_route_registry.json").read_text(encoding="utf-8"))
    dishonest = deepcopy(registry)
    dishonest["routes"][0]["coverage_tier"] = "A"
    (tmp_path / "registry").mkdir()
    (tmp_path / "contracts/operations").mkdir(parents=True)
    (tmp_path / "registry/operation_route_registry.json").write_text(json.dumps(dishonest), encoding="utf-8")
    (tmp_path / ROUTE_REGISTRY_SCHEMA).write_bytes((ROOT / ROUTE_REGISTRY_SCHEMA).read_bytes())
    report = validate_route_registry(tmp_path)
    assert report["valid"] is False
    assert "Tier A requires mediator" in report["errors"][0]
