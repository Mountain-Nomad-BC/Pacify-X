from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.intake_lifecycle import (
    close_intake,
    open_intake,
    quarantine_closed_intake,
    record_snapshot,
)


class ClosedIntakeQuarantineTests(unittest.TestCase):
    def test_closed_intake_moves_only_after_equality_and_preserves_every_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "intake"
            source.mkdir()
            (source / "one.txt").write_text("preserve me", encoding="utf-8")
            state = workspace / "state"
            open_intake(state, source_alias="intake", opened_by="test")
            record_snapshot(source, state, source_alias="intake")
            record_snapshot(source, state, source_alias="intake")
            close_intake(
                source,
                state,
                source_alias="intake",
                approved_by="test",
                minimum_stability_seconds=0,
            )
            destination = workspace / "quarantine" / "closed-intake"
            receipt = quarantine_closed_intake(
                source,
                destination,
                state,
                workspace=workspace,
                source_alias="intake",
            )
            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "one.txt").read_text(encoding="utf-8"), "preserve me"
            )
            self.assertTrue((destination / "QUARANTINE_MANIFEST.json").is_file())
            self.assertEqual(receipt["source_file_count"], 1)
            self.assertTrue(receipt["pre_move_equality_verified"])
            self.assertTrue(receipt["post_move_inventory_reconciled"])
            self.assertFalse(receipt["hard_delete"])

    def test_open_or_drifted_intake_cannot_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "intake"
            source.mkdir()
            (source / "one.txt").write_text("first", encoding="utf-8")
            state = workspace / "state"
            open_intake(state, source_alias="intake", opened_by="test")
            with self.assertRaisesRegex(ValueError, "not explicitly closed"):
                quarantine_closed_intake(
                    source,
                    workspace / "quarantine" / "open",
                    state,
                    workspace=workspace,
                    source_alias="intake",
                )
            record_snapshot(source, state, source_alias="intake")
            record_snapshot(source, state, source_alias="intake")
            close_intake(
                source,
                state,
                source_alias="intake",
                approved_by="test",
                minimum_stability_seconds=0,
            )
            (source / "one.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "drifted"):
                quarantine_closed_intake(
                    source,
                    workspace / "quarantine" / "drifted",
                    state,
                    workspace=workspace,
                    source_alias="intake",
                )


if __name__ == "__main__":
    unittest.main()
