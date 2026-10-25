from copy import deepcopy
import json

import pytest

from runtime.event_ledger import append_chained_event, recover_event_ledger
from runtime.operational_event_bus import OperationalEventBus
from tests.test_operational_event_bus import ROOT, _event


def test_duplicate_event_id_cannot_overwrite_receipt(tmp_path):
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    bus.publish(_event("same-id", None))
    receipt = bus.root / "receipts/same-id.json"
    before = receipt.read_bytes()
    changed = _event("same-id", None)
    changed["operation"]["name"] = "different"
    with pytest.raises(ValueError, match="duplicate"):
        bus.publish(changed, link_current_head=True)
    assert receipt.read_bytes() == before
    assert bus.replay()["revision"] == 1


@pytest.mark.parametrize("failure", ["invalid", "duplicate"])
def test_entire_batch_is_validated_before_any_event_is_committed(tmp_path, failure):
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    first = _event("batch-first", None)
    second = deepcopy(first) if failure == "duplicate" else _event("batch-second", None)
    if failure == "invalid":
        second["source"]["coverage_tier"] = "incorrect"
    with pytest.raises(ValueError):
        bus.publish_batch([first, second], link_current_head=True)
    assert bus.replay()["revision"] == 0
    assert not list((bus.root / "events").glob("*.json"))


def test_recovery_does_not_rewrite_corrupt_protected_head(tmp_path):
    ledger = tmp_path / "events"
    append_chained_event(ledger, "one", {"value": 1})
    head = tmp_path / ".ledger-authority/events/head.json"
    damaged = b'{"sequence":999,"event_sha256":"tampered"}'
    head.write_bytes(damaged)
    result = recover_event_ledger(ledger)
    assert result["recovered"] is False
    assert result["errors"]
    assert head.read_bytes() == damaged


def test_batch_is_one_wal_transaction_and_retains_all_receipts(tmp_path, monkeypatch):
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    commits = []
    original = bus.wal.commit
    def commit(*args, **kwargs):
        commits.append(kwargs["transaction_id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(bus.wal, "commit", commit)
    receipts = bus.publish_batch([_event("batch-one", None), _event("batch-two", None)], link_current_head=True)
    assert len(commits) == 1
    assert len(receipts) == 2
    assert bus.replay()["valid"] is True
    for receipt in receipts:
        assert json.loads((bus.root / f"receipts/{receipt['event_id']}.json").read_text(encoding="utf-8"))["event_sha256"] == receipt["event_sha256"]


@pytest.mark.parametrize("index", [0, 3, 8])
def test_interrupted_batch_recovers_all_events_without_republishing(tmp_path, monkeypatch, index):
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    original = bus.wal.commit
    def interrupted(boundary):
        if boundary == f"target:{index}:published":
            raise RuntimeError("injected interruption")
    def commit(*args, **kwargs):
        return original(*args, **kwargs, fault_injector=interrupted)
    monkeypatch.setattr(bus.wal, "commit", commit)
    with pytest.raises(RuntimeError):
        bus.publish_batch([_event("first", None), _event("second", None)], link_current_head=True)
    replay = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path).replay()
    assert replay["valid"] is True
    assert [row["event"]["event_id"] for row in replay["events"]] == ["first", "second"]


def test_oversized_atomic_batch_is_rejected_before_effects(tmp_path):
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    with pytest.raises(ValueError, match="atomic operational event batch"):
        bus.publish_batch([_event(f"event-{i}", None) for i in range(42)], link_current_head=True)
    assert not bus.root.exists()


def test_pending_recovery_refuses_a_changed_head_before_image(tmp_path, monkeypatch):
    from runtime import event_ledger
    ledger = tmp_path / "events"
    append_chained_event(ledger, "one", {"value": 1})
    def fail(*args):
        raise OSError("head interruption")
    with monkeypatch.context() as patch:
        patch.setattr(event_ledger, "_publish_head", fail)
        with pytest.raises(OSError):
            append_chained_event(ledger, "two", {"value": 2})
    head = tmp_path / ".ledger-authority/events/head.json"
    head.write_bytes(b'{"tampered":true}')
    assert recover_event_ledger(ledger)["errors"]
    assert head.read_bytes() == b'{"tampered":true}'


@pytest.mark.parametrize("index", [0, 1])
def test_tool_intake_and_checkpoint_recover_as_one_transaction(tmp_path, monkeypatch, index):
    from runtime import tool_intake
    from runtime.wal_transaction import JsonWal
    directory = tmp_path / ".agentic_engineering_os_px/project-management"
    directory.mkdir(parents=True)
    state_path = directory / "state.json"
    state_path.write_text('{"checkpoint":{"revision":0}}', encoding="utf-8")
    monkeypatch.setattr(tool_intake, "scan_project_tooling", lambda *a, **k: {"decision": "no_external_tooling"})
    original = JsonWal.commit
    def interrupt(boundary):
        if boundary == f"target:{index}:published":
            raise RuntimeError("tool-intake interruption")
    with monkeypatch.context() as patch:
        patch.setattr(JsonWal, "commit", lambda self, *a, **k: original(self, *a, **k, fault_injector=interrupt))
        with pytest.raises(RuntimeError):
            tool_intake.record_tool_intake(tmp_path, ROOT, apply=True)
    JsonWal(directory / "tool-intake-wal", tmp_path).recover()
    assert json.loads(state_path.read_text(encoding="utf-8"))["checkpoint"]["revision"] == 1
    assert json.loads((directory / "tool-intake.json").read_text(encoding="utf-8"))["decision"] == "no_external_tooling"
