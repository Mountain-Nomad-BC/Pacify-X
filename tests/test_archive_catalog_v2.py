import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.map_archives import build_catalog


class ArchiveCatalogV2Tests(unittest.TestCase):
    def test_each_zip_is_mapped_and_identical_archives_share_content_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one.zip"
            with ZipFile(first, "w") as archive:
                archive.writestr("a/file.txt", "value")
            (root / "nested").mkdir()
            second = root / "nested/two.zip"; second.write_bytes(first.read_bytes())
            result = build_catalog(root)
        self.assertEqual(result["source_occurrence_count"], 2)
        self.assertEqual(result["unique_archive_count"], 1)
        self.assertEqual(len(result["archives"][0]["entries"]), 1)
        self.assertNotIn("one.zip", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
