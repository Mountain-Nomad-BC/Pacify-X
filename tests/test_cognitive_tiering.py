from __future__ import annotations

from datetime import date, datetime, timezone
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

EXTERNAL_ROOT = os.environ.get("PX_PERSISTENT_MEMORY_EXTERNAL_ROOT")
if EXTERNAL_ROOT:
    sys.path.insert(0, EXTERNAL_ROOT)
    importlib.invalidate_caches()
PACKAGE_AVAILABLE = importlib.util.find_spec("pacifyx_memory") is not None
if PACKAGE_AVAILABLE:
    from pacifyx_memory.tiering import (
        TierRecordRef, build_daily_capsule, build_project_capsule, build_week_capsule,
        memory_temperature, plan_record,
    )
else:
    TierRecordRef = None


SHA = "a" * 64
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@unittest.skipUnless(PACKAGE_AVAILABLE, "external cognitive package source not supplied to test environment")
class CognitiveTieringTests(unittest.TestCase):
    def ref(self, object_id: str, recorded_at: str, **kwargs) -> TierRecordRef:
        return TierRecordRef(
            object_id=object_id,
            revision=kwargs.pop("revision", 1),
            recorded_at=recorded_at,
            project_id=kwargs.pop("project_id", "project:px"),
            content_sha256=kwargs.pop("content_sha256", SHA),
            kind=kwargs.pop("kind", "memory"),
            title=kwargs.pop("title", object_id),
            summary=kwargs.pop("summary", "summary"),
            subjects=kwargs.pop("subjects", ("subject:pacify-x",)),
            relations=kwargs.pop("relations", ("relation:depends-on",)),
            retrieval_active=kwargs.pop("retrieval_active", True),
            retain_until=kwargs.pop("retain_until", None),
            **kwargs,
        )

    def test_temperature_and_identity_preserving_paths(self) -> None:
        self.assertEqual(("hot", False), memory_temperature("2026-09-20T01:00:00Z", now_utc=NOW))
        self.assertEqual(("warm", False), memory_temperature("2026-09-19T01:00:00Z", now_utc=NOW))
        self.assertEqual(("cold", False), memory_temperature("2026-09-13T01:00:00Z", now_utc=NOW))
        self.assertEqual(
            ("warm", True),
            memory_temperature(
                "2026-09-01T01:00:00Z",
                now_utc=NOW,
                retain_until="2026-09-21T00:00:00Z",
            ),
        )
        root = Path("Cognitive/Memory")
        ref = self.ref("memory:stable/id", "2026-09-13T01:00:00Z")
        cold = plan_record(ref, memory_root=root, now_utc=NOW)
        warm = plan_record(ref, memory_root=root, now_utc=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(cold.object_id, warm.object_id)
        self.assertEqual(cold.canonical_record, warm.canonical_record)
        self.assertEqual("cold", cold.temperature)
        self.assertEqual("warm", warm.temperature)
        self.assertTrue(cold.cold_subject_shards)
        self.assertTrue(cold.cold_relation_shards)

    def test_capsules_are_bounded_projections_not_authority(self) -> None:
        refs = [
            self.ref("decision:1", "2026-09-20T01:00:00Z", kind="decision"),
            self.ref("goal:1", "2026-09-20T02:00:00Z", kind="goal"),
            self.ref("action:1", "2026-09-20T03:00:00Z", kind="action"),
            self.ref("skill:1", "2026-09-20T04:00:00Z", kind="skill"),
        ]
        daily = build_daily_capsule("project:px", date(2026, 9, 20), refs, event_seq=42)
        self.assertFalse(daily["authority_granted"])
        self.assertEqual(["decision:1"], daily["decision_ids"])
        self.assertEqual(["goal:1"], daily["goal_ids"])
        self.assertEqual(["action:1"], daily["action_ids"])
        self.assertEqual(["skill:1"], daily["skill_ids"])
        week = build_week_capsule("project:px", "2026-W38", [daily])
        self.assertFalse(week["authority_granted"])
        self.assertEqual(daily["record_ids"], week["record_ids"])
        project = build_project_capsule("project:px", refs, max_records=8)
        self.assertFalse(project["authority_granted"])
        self.assertEqual(4, len(project["record_ids"]))

    def test_future_timestamp_and_invalid_cold_window_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            memory_temperature("2026-09-21T00:00:00Z", now_utc=NOW)
        with self.assertRaises(ValueError):
            memory_temperature("2026-09-19T00:00:00Z", now_utc=NOW, cold_after_days=1)


if __name__ == "__main__":
    unittest.main()
