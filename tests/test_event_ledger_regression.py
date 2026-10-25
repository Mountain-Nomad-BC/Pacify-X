from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from runtime.event_ledger import (
    append_chained_event,
    read_event_tail,
    validate_event_ledger,
)


def _write_event(ledger: Path, name: str, content: object) -> None:
    (ledger / name).write_text(
        json.dumps(content) if not isinstance(content, str) else content,
        encoding="utf-8",
    )


class PXAUD086_EmptyLedgerBypassHeadCheck(unittest.TestCase):
    """PX-AUD-086: empty event file set bypasses protected-ledger head consistency check."""

    def test_orphaned_head_reported_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events"
            ledger.mkdir()
            head_path = ledger.parent / ".ledger-authority" / ledger.name / "head.json"
            head_path.parent.mkdir(parents=True)
            head_path.write_text(
                json.dumps({"schema_version": "1.0", "sequence": 1, "event_sha256": "a" * 64}),
                encoding="utf-8",
            )
            result = validate_event_ledger(ledger)
            self.assertFalse(result["valid"])
            self.assertIn(
                "protected ledger history exists but no event files remain",
                result["errors"],
            )

    def test_read_tail_orphaned_head_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events"
            ledger.mkdir()
            head_path = ledger.parent / ".ledger-authority" / ledger.name / "head.json"
            head_path.parent.mkdir(parents=True)
            head_path.write_text(
                json.dumps({"schema_version": "1.0", "sequence": 1, "event_sha256": "a" * 64}),
                encoding="utf-8",
            )
            result = read_event_tail(ledger)
            self.assertEqual(result["health"]["status"], "degraded")
            self.assertIsNotNone(result["health"]["failed_file"])


class PXAUD087_TamperedHeadHealedWithoutClassification(unittest.TestCase):
    """PX-AUD-087: event-ledger recovery heals tampered protected head without classifying incident."""

    def test_tampered_payload_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events"
            event = append_chained_event(ledger, "one", {"value": 1})
            record = json.loads(event.read_text(encoding="utf-8"))
            record["payload"] = {"value": 9}
            record["payload_sha256"] = hashlib.sha256(
                json.dumps(
                    record["payload"], sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            record["event_sha256"] = hashlib.sha256(
                json.dumps(
                    {k: v for k, v in record.items() if k != "event_sha256"},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode()
            ).hexdigest()
            event.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            result = validate_event_ledger(ledger)
            self.assertFalse(result["valid"])
            self.assertTrue(
                any("head" in e.lower() for e in result["errors"]),
                f"expected head-related error, got: {result['errors']}",
            )


class PXAUD088_MissingStateAsValidEmptyHistory(unittest.TestCase):
    """PX-AUD-088: operational bus replay treats missing state as valid empty history."""

    def test_durable_artifacts_without_state_raises(self) -> None:
        import tempfile
        from runtime.operational_event_bus import OperationalEventBus

        ROOT = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            bus_root = Path(directory) / "bus"
            bus_root.mkdir(parents=True)
            events_dir = bus_root / "events"
            events_dir.mkdir()
            head_path = bus_root / ".authority" / "head.json"
            head_path.parent.mkdir(parents=True)
            head_path.write_text("{}", encoding="utf-8")
            bus = OperationalEventBus(ROOT, bus_root, Path(directory))
            with self.assertRaises(ValueError) as ctx:
                bus.replay()
            self.assertIn("state is missing despite durable history", str(ctx.exception))


class PXAUD089_NonfiniteJSONPayloads(unittest.TestCase):
    """PX-AUD-089: event ledger persists non-standard JSON nonfinite numeric payloads."""

    def test_nan_payload_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events"
            with self.assertRaises((ValueError, TypeError)):
                append_chained_event(ledger, "one", {"value": float("nan")})

    def test_inf_payload_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events"
            with self.assertRaises((ValueError, TypeError)):
                append_chained_event(ledger, "one", {"value": float("inf")})


if __name__ == "__main__":
    unittest.main()
