from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".px" / "skills" / "data-sort-dry-run-picker" / "scripts" / "sort_picker.py"
SPEC = importlib.util.spec_from_file_location("sort_picker", SCRIPT)
assert SPEC and SPEC.loader
sort_picker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sort_picker)


class SortPickerTests(unittest.TestCase):
    def test_large_integer_jsonl_uses_deterministic_sample_and_three_finalists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.jsonl"
            source.write_text("".join(json.dumps({"id": index % 97, "payload": index}) + "\n" for index in range(3000)), encoding="utf-8")
            first = sort_picker.build_receipt(source, input_format="jsonl", key_path="id", coerce="auto", sample_limit=500, repeats=2, seed=42)
            second = sort_picker.build_receipt(source, input_format="jsonl", key_path="id", coerce="auto", sample_limit=500, repeats=2, seed=42)
            self.assertEqual(first["input"]["records"], 3000)
            self.assertEqual(first["sample"]["strategy"], "deterministic-reservoir")
            self.assertEqual(first["sample"]["sha256"], second["sample"]["sha256"])
            self.assertEqual(len(first["pilot"]["advanced"]), 3)
            self.assertIsNotNone(first["selected"])
            self.assertTrue(all(row["correct"] for row in first["benchmark"]["results"]))

    def test_csv_numeric_key_is_coerced_and_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            source.write_text("rank,name\n3,c\n1,a\n2,b\n", encoding="utf-8")
            receipt = sort_picker.build_receipt(source, input_format="csv", key_path="rank", coerce="integer", sample_limit=100, repeats=1, seed=1)
            self.assertEqual(receipt["input"]["records"], 3)
            self.assertRegex(receipt["input"]["sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(receipt["sample"]["strategy"], "full")

    def test_mixed_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.jsonl"
            source.write_text('{"key": 1}\n{"key": "x"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mixed key types"):
                sort_picker.build_receipt(source, input_format="jsonl", key_path="key", coerce="none", sample_limit=100, repeats=1, seed=1)


if __name__ == "__main__":
    unittest.main()
