from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile

from runtime.event_ledger import (
    append_chained_event,
    read_event_tail,
    validate_event_ledger,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def test_deleted_event_breaks_hash_chain() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        append_chained_event(ledger, "one", {"value": 1})
        second = append_chained_event(ledger, "two", {"value": 2})
        first = next(path for path in ledger.glob("*.json") if path != second)
        first.rename(ledger.parent / first.name)
        assert not validate_event_ledger(ledger)["valid"]


def test_reordered_event_breaks_hash_chain() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        one = append_chained_event(ledger, "one", {"value": 1})
        two = append_chained_event(ledger, "two", {"value": 2})
        one_bytes, two_bytes = one.read_bytes(), two.read_bytes()
        one.write_bytes(two_bytes)
        two.write_bytes(one_bytes)
        assert not validate_event_ledger(ledger)["valid"]


def test_duplicate_event_sequence_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        first = append_chained_event(ledger, "one", {"value": 1})
        (ledger / "00000001-duplicate.json").write_bytes(first.read_bytes())
        assert not validate_event_ledger(ledger)["valid"]


def test_concurrent_event_append_preserves_chain() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        with ThreadPoolExecutor(max_workers=4) as pool:
            tuple(
                pool.map(
                    lambda value: append_chained_event(
                        ledger, "event", {"value": value}
                    ),
                    range(16),
                )
            )
        result = validate_event_ledger(ledger)
        assert result["valid"] and result["event_count"] == 16


def test_rewritten_history_cannot_replace_protected_head() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        event = append_chained_event(ledger, "one", {"value": 1})
        record = json.loads(event.read_text(encoding="utf-8"))
        record["payload"] = {"value": 9}
        record["payload_sha256"] = hashlib.sha256(
            _canonical(record["payload"])
        ).hexdigest()
        record["event_sha256"] = hashlib.sha256(
            _canonical(
                {key: value for key, value in record.items() if key != "event_sha256"}
            )
        ).hexdigest()
        event.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        result = validate_event_ledger(ledger)
        assert not result["valid"]
        assert any("protected ledger head" in error for error in result["errors"])


def test_event_tail_preserves_valid_prefix_and_degraded_ancestry() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        append_chained_event(ledger, "one", {"value": 1})
        second = append_chained_event(ledger, "two", {"value": 2})
        second_record = json.loads(second.read_text(encoding="utf-8"))
        (ledger / "00000003-broken.json").write_text(
            '{"schema_version":', encoding="utf-8"
        )
        (ledger / "00000004-ignored.json").write_text("{}", encoding="utf-8")
        result = read_event_tail(ledger, limit=10)
        assert [event["sequence"] for event in result["events"]] == [1, 2]
        assert result["health"] == {
            "status": "degraded",
            "valid_prefix_count": 2,
            "failed_file": "00000003-broken.json",
            "ignored_suffix_files": 2,
            "reason": "truncated-or-malformed-event",
            "ancestry_head_sha256": second_record["event_sha256"],
        }


def test_event_tail_is_bounded_and_checks_protected_head() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Path(directory) / "events"
        for value in range(5):
            append_chained_event(ledger, "item", {"value": value})
        result = read_event_tail(ledger, limit=2)
        assert [event["sequence"] for event in result["events"]] == [4, 5]
        assert result["health"]["status"] == "healthy"
        head_path = ledger.parent / ".ledger-authority" / ledger.name / "head.json"
        head_path.write_text("{}", encoding="utf-8")
        degraded = read_event_tail(ledger, limit=2)
        assert degraded["health"]["status"] == "degraded"
        assert degraded["health"]["failed_file"] == "head.json"
