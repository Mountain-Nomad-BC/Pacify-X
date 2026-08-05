from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.intake_lifecycle import (
    close_intake,
    intake_status,
    load_events,
    open_intake,
    record_snapshot,
    require_closed_stable,
)


class IntakeLifecycleTests(unittest.TestCase):
    def test_intake_is_append_only_and_requires_two_stable_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            state = root / "state"
            source.mkdir()
            (source / "note.md").write_text("first\n", encoding="utf-8")
            open_intake(state, source_alias="staged", opened_by="user")
            record_snapshot(source, state, source_alias="staged")
            with self.assertRaisesRegex(ValueError, "two recorded snapshots"):
                close_intake(
                    source,
                    state,
                    source_alias="staged",
                    approved_by="user",
                    minimum_stability_seconds=0,
                )
            record_snapshot(source, state, source_alias="staged")
            close_intake(
                source,
                state,
                source_alias="staged",
                approved_by="user",
                minimum_stability_seconds=0,
            )
            self.assertEqual(intake_status(state)["status"], "closed")
            self.assertEqual(
                require_closed_stable(source, state, source_alias="staged")[
                    "file_count"
                ],
                1,
            )
            self.assertEqual(
                [event["event"] for event in load_events(state)],
                ["open", "snapshot", "snapshot", "close"],
            )

    def test_mutation_denies_closure_and_post_close_processing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            state = root / "state"
            source.mkdir()
            note = source / "note.md"
            note.write_text("first\n", encoding="utf-8")
            open_intake(state, source_alias="staged", opened_by="user")
            record_snapshot(source, state, source_alias="staged")
            note.write_text("second\n", encoding="utf-8")
            record_snapshot(source, state, source_alias="staged")
            with self.assertRaisesRegex(ValueError, "not identical"):
                close_intake(
                    source,
                    state,
                    source_alias="staged",
                    approved_by="user",
                    minimum_stability_seconds=0,
                )

    def test_closed_tree_drift_requires_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            state = root / "state"
            source.mkdir()
            note = source / "note.md"
            note.write_text("stable\n", encoding="utf-8")
            open_intake(state, source_alias="staged", opened_by="user")
            record_snapshot(source, state, source_alias="staged")
            record_snapshot(source, state, source_alias="staged")
            close_intake(
                source,
                state,
                source_alias="staged",
                approved_by="user",
                minimum_stability_seconds=0,
            )
            note.write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "drifted"):
                require_closed_stable(source, state, source_alias="staged")


if __name__ == "__main__":
    unittest.main()
