import json
from pathlib import Path
import tempfile
import unittest

from scripts.extract_structured_text import extract


class StructuredTextExtractionTests(unittest.TestCase):
    def test_all_text_formats_are_preserved_and_binary_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.jsonl"; output = root / "output.jsonl"
            base = {"source_tree": "x", "probable_domain": "general", "domain_confidence": 1.0, "structure": {}}
            rows = [
                {**base, "id": "md", "path": "a.md", "sha256": "a", "content_kind": "text"},
                {**base, "id": "json", "path": "a.json", "sha256": "b", "content_kind": "text"},
                {**base, "id": "bin", "path": "a.bin", "sha256": "c", "content_kind": "binary"},
            ]
            inventory.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            count, _ = extract(inventory, output)
            result = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(count, 2)
        self.assertEqual({item["format"] for item in result}, {".md", ".json"})


if __name__ == "__main__":
    unittest.main()
