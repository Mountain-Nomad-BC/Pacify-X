from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path

from runtime.operational_event_bus import OperationalEventBus
from runtime.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[1]


def _event(identifier: str, previous: str | None) -> dict[str, object]:
    return {
        "schema_version": "px.operation-event/1",
        "event_id": identifier,
        "correlation_id": "corr-tracer",
        "parent_correlation_id": None,
        "actor": {"actor_id": "runtime", "actor_kind": "runtime", "session_id": "s1", "harness": "pytest", "accountable_owner": "pacify-x"},
        "work": {"project_id": "pacify-x", "task_id": "O01", "claim_id": None, "orchestration_id": None},
        "source": {"route_id": "runtime.cli", "component": "runtime.cli", "host_id": None, "coverage_tier": "C"},
        "operation": {"name": "tracer", "lifecycle": "completed", "result": "success"},
        "effects": {"declared": ["read"], "observed": ["read"], "scope_refs": ["project:pacify-x"]},
        "provider": None,
        "time": {"observed_at": "2026-08-11T19:00:00Z", "started_at": "2026-08-11T18:59:59Z", "duration_ms": 1000, "freshness": "live"},
        "integrity": {"input_sha256": None, "output_sha256": "a" * 64, "previous_event_sha256": previous},
        "capture": {"classification": "metadata_only", "payload_included": False},
    }


def test_publish_is_atomic_ordered_replayable_and_receipted(tmp_path: Path) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    first = bus.publish(_event("evt-1", None))
    second = bus.publish(_event("evt-2", str(first["event_sha256"])))
    replay = bus.replay()
    assert replay["valid"] is True
    assert [item["revision"] for item in replay["events"]] == [1, 2]
    assert replay["revision"] == 2
    receipt = json.loads((tmp_path / "bus/receipts/evt-2.json").read_text(encoding="utf-8"))
    assert receipt["event_sha256"] == second["event_sha256"]
    assert (tmp_path / "bus/projections/revision.json").is_file()


def test_anchored_head_reads_only_the_current_link_without_replacing_replay(
    tmp_path: Path,
) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    first = bus.publish(_event("evt-head-1", None))
    second = bus.publish(_event("evt-head-2", str(first["event_sha256"])))
    head = bus.head()
    assert head["valid"] is True
    assert head["revision"] == 2
    assert head["event_sha256"] == second["event_sha256"]
    assert head["event"]["event_id"] == "evt-head-2"
    assert head["verification_scope"] == "anchored-current-head"
    assert bus.replay()["valid_prefix_count"] == 2


def test_anchored_head_fails_closed_on_current_or_previous_link_tampering(
    tmp_path: Path,
) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    first = bus.publish(_event("evt-head-tamper-1", None))
    bus.publish(_event("evt-head-tamper-2", str(first["event_sha256"])))
    previous = tmp_path / "bus/events/00000001.json"
    value = json.loads(previous.read_text(encoding="utf-8"))
    value["event"]["operation"]["name"] = "tampered"
    previous.write_text(json.dumps(value), encoding="utf-8")
    head = bus.head()
    assert head["valid"] is False
    assert "previous link mismatch" in head["errors"][0]


def test_subscription_wakes_on_durable_revision(tmp_path: Path) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(bus.wait_for_revision, 0, 2)
        bus.publish(_event("evt-wake", None))
        result = waiting.result(timeout=3)
    assert result["valid"] is True
    assert [item["event"]["event_id"] for item in result["events"]] == ["evt-wake"]


def test_protected_head_tampering_degrades_replay(tmp_path: Path) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    bus.publish(_event("evt-1", None))
    (tmp_path / "bus/.authority/head.json").write_text("{}", encoding="utf-8")
    replay = bus.replay()
    assert replay["valid"] is False
    assert replay["valid_prefix_count"] == 1
    assert "protected head" in replay["errors"][0]


def test_unknown_route_and_dishonest_tier_are_refused(tmp_path: Path) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    unknown = _event("evt-unknown", None)
    unknown["source"]["route_id"] = "unknown.route"
    try:
        bus.publish(unknown)
    except ValueError as error:
        assert "not admitted" in str(error)
    else:
        raise AssertionError("unknown route was admitted")
    dishonest = _event("evt-tier", None)
    dishonest["source"]["coverage_tier"] = "A"
    try:
        bus.publish(dishonest)
    except ValueError as error:
        assert "differs from registry" in str(error)
    else:
        raise AssertionError("dishonest tier was admitted")


def test_external_batch_ingress_links_each_event_to_current_head(tmp_path: Path) -> None:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    receipts = bus.publish_batch(
        [_event("evt-ingress-1", None), _event("evt-ingress-2", None)],
        link_current_head=True,
    )
    replay = bus.replay()
    assert len(receipts) == 2
    assert replay["valid"] is True
    assert replay["revision"] == 2
    assert replay["events"][0]["event"]["integrity"]["previous_event_sha256"] is None
    assert (
        replay["events"][1]["event"]["integrity"]["previous_event_sha256"]
        == replay["events"][0]["event_sha256"]
    )


def test_cli_publishes_bounded_external_batch(tmp_path: Path, monkeypatch, capsys) -> None:
    document = {
        "schema_version": "px.operation-batch/1.0",
        "events": [_event("evt-cli-ingress", None)],
    }
    stream = io.TextIOWrapper(io.BytesIO(json.dumps(document).encode("utf-8")))
    monkeypatch.setattr("sys.stdin", stream)
    bus_root = tmp_path / "workspace" / ".engineering-bootstrap" / "operation-bus"
    status = cli_main(
        [
            "--root",
            str(ROOT),
            "visibility",
            "publish",
            "--bus-root",
            str(bus_root),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["valid"] is True
    assert output["published"] == 1
    assert OperationalEventBus(ROOT, bus_root, bus_root.parent).replay()["valid"] is True
