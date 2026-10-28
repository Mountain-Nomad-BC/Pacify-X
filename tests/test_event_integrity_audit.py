from copy import deepcopy
import json

import pytest

from runtime.event_ledger import append_chained_event, recover_event_ledger
from runtime.operational_event_bus import OperationalEventBus
from runtime.wal_transaction import JsonWal
from tests.test_operational_event_bus import ROOT, _event


def test_real_commissioning_and_tool_intake_share_one_lifecycle_owner(tmp_path):
    """Tool intake must advance the *same* state commissioning created.

    The control namespace is now canonical (`.agentic_engineering_os_px`). This
    test previously asserted the legacy spelling and explicitly required the
    canonical tree to be absent, which inverted the contract once the owner
    migrated: intake then wrote a state file nothing else read.
    """
    from runtime.commissioning import commission
    from runtime.tool_intake import record_tool_intake
    project = tmp_path / "project"
    commission(project, "new", apply=True, source_root=ROOT)
    state_path = project / ".agentic_engineering_os_px/project-management/state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    result = record_tool_intake(project, ROOT, apply=True)
    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["applied"] is True
    assert result["decision"] == "no_external_tooling"
    assert after["checkpoint"]["revision"] == before["checkpoint"]["revision"] + 1
    expected = ".agentic_engineering_os_px/project-management/tool-intake.json"
    assert after["evidence"]["tool_intake_records"] == [expected]
    assert json.loads((project / expected).read_text(encoding="utf-8"))["decision"] == result["decision"]
    # A second state authority beside the commissioned project is the defect.
    assert not (project / ".engineering-bootstrap/project-management/state.json").exists()


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


@pytest.mark.parametrize("boundary", [
    "intent:before_acceptance",
    "journal:transaction:created",
    "journal:after:0",
    "journal:after:5",
    "manifest:prepared:staged",
    "manifest:prepared:published",
    "manifest:applying:published",
    "target:0:staged",
    "target:2:published",
    "target:4:staged",
    "target:8:published",
    "manifest:committed:staged",
    "manifest:committed:published",
    "journal:committed:published",
])
def test_batch_failure_at_every_publication_point_keeps_one_custody_image(
    tmp_path, boundary, monkeypatch
):
    "A crash at any WAL boundary recovers the whole batch, never a prefix."
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    original = bus.wal.commit
    observed_boundaries = []
    def interrupted(observed):
        observed_boundaries.append(observed)
        if observed == boundary:
            raise RuntimeError(f"interrupted at {boundary}")

    def commit(wal_self, artifacts, **kwargs):
        return original(artifacts, **kwargs, fault_injector=interrupted)

    monkeypatch.setattr(JsonWal, "commit", commit)
    with pytest.raises(RuntimeError, match="interrupted at"):
        bus.publish_batch(
            [_event("boundary-a", None), _event("boundary-b", None)],
            link_current_head=True,
        )
    # The injected boundary must be the exact one reached, not a neighbour.
    assert observed_boundaries[-1] == boundary
    assert len(observed_boundaries) == 1 + [
        "intent:before_acceptance", "journal:transaction:created", "journal:after:0",
        "journal:after:1", "journal:after:2", "journal:after:3", "journal:after:4",
        "journal:after:5", "journal:after:6", "journal:after:7", "journal:after:8",
        "manifest:prepared:staged", "manifest:prepared:published",
        "manifest:applying:staged", "manifest:applying:published",
        *[f"target:{index}:{stage}" for index in range(9) for stage in ("staged", "published")],
        "manifest:committed:staged", "manifest:committed:published",
        "journal:committed:published",
    ].index(boundary)
    reopened = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    head = reopened.head()
    if head["valid"]:
        assert head["revision"] in (0, 2)
    replay = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path).replay()
    assert replay["valid"] is True, replay["errors"]
    ids = [row["event"]["event_id"] for row in replay["events"]]
    assert ids in ([], ["boundary-a", "boundary-b"])
    if ids:
        assert replay["revision"] == 2
        assert json.loads((bus.root / "state.json").read_text(encoding="utf-8"))["revision"] == 2

def test_concurrent_batch_and_single_publish_keep_one_chain(tmp_path):
    "Overlapping publications cannot interleave revisions or fork ancestry."
    from concurrent.futures import ThreadPoolExecutor
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    bus.publish(_event("seed", None))

    def publish_batch(index):
        return bus.publish_batch(
            [_event(f"batch-{index}-a", None), _event(f"batch-{index}-b", None)],
            link_current_head=True,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(publish_batch, index) for index in range(4)]
        results = [future.result(timeout=120) for future in futures]
    revisions = sorted(receipt["revision"] for group in results for receipt in group)
    assert revisions == [2, 3, 4, 5, 6, 7, 8, 9]
    replay = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path).replay()
    assert replay["valid"] is True, replay["errors"]
    assert replay["revision"] == 9

def test_concurrent_publishers_never_wait_on_their_own_lease(tmp_path):
    """A live lease recorded by this same process must not deadlock its siblings.

    Windows byte-range locks are owned by the process, so every thread of this
    process owns the region. The lease record, not the byte-range lock, decides
    who is inside the critical section; without that in-process serialization a
    sibling attempts an overlapping byte-range lock and busy-waits until timeout.
    """
    import threading
    import time
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    bus.publish(_event("seed", None))
    failures = []

    def publish_batch(index):
        try:
            bus.publish_batch(
                [_event(f"batch-{index}-a", None), _event(f"batch-{index}-b", None)],
                link_current_head=True,
            )
        except BaseException as error:  # noqa: BLE001 - retained for the assertion
            failures.append(repr(error))

    started = time.monotonic()
    threads = [threading.Thread(target=publish_batch, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert time.monotonic() - started < 60
    replay = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path).replay()
    assert replay["valid"] is True, replay["errors"]
    assert replay["revision"] == 9

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
