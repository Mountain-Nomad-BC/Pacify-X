from pathlib import Path
import tempfile
import unittest

from scripts.quarantine_paths import quarantine_paths


class QuarantinePathTests(unittest.TestCase):
    def test_explicit_paths_move_outside_project_with_hash_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project = workspace / "project"
            project.mkdir()
            (project / "old.txt").write_text("preserve", encoding="utf-8")
            payload = quarantine_paths(
                workspace,
                project,
                workspace / "temp/quarantine/run",
                workspace / "temp/quarantine/run-manifest.json",
                [Path("old.txt")],
                "fixture",
            )
            self.assertTrue(payload["inventory_reconciled"])
            self.assertFalse(payload["hard_delete"])
            self.assertFalse((project / "old.txt").exists())
            self.assertEqual(
                (workspace / "temp/quarantine/run/old.txt").read_text(encoding="utf-8"),
                "preserve",
            )

    def test_project_root_and_inside_project_destination_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project = workspace / "project"
            project.mkdir()
            with self.assertRaises(ValueError):
                quarantine_paths(
                    workspace,
                    project,
                    project / "quarantine",
                    workspace / "manifest.json",
                    [Path(".")],
                    "fixture",
                )


if __name__ == "__main__":
    unittest.main()
