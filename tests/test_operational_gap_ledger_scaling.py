from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json

from runtime.operational_gap_ledger import (
    append_event,
    migrate_ledger_segments,
    read_events,
    validate_ledger_segments,
)


def _ledger(root: Path) -> None:
    append_event(
        root,
        "ledger_initialized",
        {"ledger_id": "segmented-test", "scope": ["test"]},
        actor="test",
    )


def test_segment_migration_preserves_exact_legacy_order_and_identity(tmp_path):
    _ledger(tmp_path)
    before = (tmp_path / "registry/operational_gap_ledger.jsonl").read_bytes()
    manifest = migrate_ledger_segments(tmp_path, segment_events=1)
    assert manifest["legacy_retained"] is True
    assert manifest["validation"]["valid"] is True
    assert (tmp_path / "registry/operational_gap_ledger.jsonl").read_bytes() == before
    assert validate_ledger_segments(tmp_path)["event_count"] == len(read_events(tmp_path))


def test_segment_corruption_fails_closed_without_touching_legacy(tmp_path):
    _ledger(tmp_path)
    manifest = migrate_ledger_segments(tmp_path, segment_events=1)
    segment = manifest["segments"][0]
    path = tmp_path / "evidence/operational-gap-ledger/migration/segments" / f"{segment['content_sha256']}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    assert validate_ledger_segments(tmp_path)["valid"] is False
    assert len(read_events(tmp_path)) == 1


def test_large_snapshot_append_uses_content_addressed_delta_without_rewrite(tmp_path, monkeypatch):
    import runtime.operational_gap_ledger as ledger

    _ledger(tmp_path)
    before = (tmp_path / "registry/operational_gap_ledger.snapshot.json").read_bytes()
    monkeypatch.setattr(ledger, "DELTA_CHECKPOINT_THRESHOLD_BYTES", 1)
    append_event(
        tmp_path,
        "surface_registered",
        {"surface_id":"benchmark","name":"Benchmark","source_files":["bench.py"],"known_controls":["run"],"owner":"test","inventory_evidence":["test"]},
        actor="test",
    )
    assert (tmp_path / "registry/operational_gap_ledger.snapshot.json").read_bytes() == before
    head = json.loads((tmp_path / "registry/operational_gap_ledger.head.json").read_text(encoding="utf-8"))
    assert head["delta_projection"]["authoritative"] is False
    assert ledger.read_snapshot(tmp_path)["event_count"] == 2


def test_delta_checkpoint_concurrent_writers_serialize_without_fork(tmp_path, monkeypatch):
    import runtime.operational_gap_ledger as ledger

    _ledger(tmp_path)
    monkeypatch.setattr(ledger, "DELTA_CHECKPOINT_THRESHOLD_BYTES", 1)

    def append(index):
        append_event(
            tmp_path,
            "surface_registered",
            {"surface_id":f"benchmark-{index}","name":f"Benchmark {index}","source_files":["bench.py"],"known_controls":["run"],"owner":"test","inventory_evidence":["test"]},
            actor=f"writer-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(8)))
    events = read_events(tmp_path)
    assert [item["sequence"] for item in events] == list(range(1, 10))
    assert ledger.read_snapshot(tmp_path)["event_count"] == 9
