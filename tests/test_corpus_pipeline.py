from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


class CorpusPipelineTests(unittest.TestCase):
    def run_script(self, relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(ROOT / relative), *arguments], text=True, capture_output=True, check=False)

    def test_inventory_is_deterministic_reconciled_and_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / "source"
            source.mkdir()
            (source / "a.md").write_text("---\nname: example\n---\n# Build\ninputs: source\n```python\npython task.py\n```\n", encoding="utf-8")
            (source / "same.md").write_bytes((source / "a.md").read_bytes())
            (source / "binary.bin").write_bytes(b"\x00\x01")
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            for output in (first, second):
                result = self.run_script("scripts/inventory/build_file_inventory.py", "--root", f"fixture={source}", "--output", str(output))
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            summary = json.loads(first.with_name("file_inventory_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["record_count"], 3)
            self.assertTrue(summary["roots"][0]["reconciled"])
            records = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
            markdown = next(item for item in records if item["path"] == "a.md")
            self.assertEqual(markdown["structure"]["frontmatter"]["name"], "example")
            self.assertIn("python", markdown["structure"]["code_languages"])

    def test_dedup_classification_and_review_clusters_cover_every_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / "source"
            source.mkdir()
            (source / "one.md").write_text("# Repair\n", encoding="utf-8")
            (source / "two.md").write_text("# Repair\n", encoding="utf-8")
            inventory = temp / "inventory.jsonl"
            self.assertEqual(self.run_script("scripts/inventory/build_file_inventory.py", "--root", f"fixture={source}", "--output", str(inventory)).returncode, 0)
            exact = temp / "exact.json"
            self.assertEqual(self.run_script("scripts/deduplicate/hash_exact_duplicates.py", "--inventory", str(inventory), "--output", str(exact)).returncode, 0)
            self.assertEqual(json.loads(exact.read_text(encoding="utf-8"))["group_count"], 1)
            classified = temp / "classified.jsonl"
            result = self.run_script("scripts/classify/classify_assets.py", "--inventory", str(inventory), "--exact-duplicates", str(exact), "--output", str(classified))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            summary = json.loads(classified.with_name("asset_classification_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["unknown_count"], 0)
            clusters = temp / "clusters.json"
            self.assertEqual(self.run_script("scripts/classify/build_review_clusters.py", "--input", str(classified), "--output", str(clusters)).returncode, 0)
            self.assertEqual(json.loads(clusters.read_text(encoding="utf-8"))["asset_count"], 2)

    def test_partition_merge_is_sorted_and_rejects_duplicate_ids(self) -> None:
        from scripts.inventory.merge_inventory_partitions import merge

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left.jsonl"
            right = root / "right.jsonl"
            left.write_text(
                json.dumps({"id": "b", "source_tree": "left", "path": "b", "content_kind": "text", "probable_domain": "general", "extension": ".md"}) + "\n",
                encoding="utf-8",
            )
            right.write_text(
                json.dumps({"id": "a", "source_tree": "right", "path": "a", "content_kind": "text", "probable_domain": "general", "extension": ".txt"}) + "\n",
                encoding="utf-8",
            )
            output = root / "merged.jsonl"
            summary = merge([right, left], output, root / "summary.json")
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["id"] for row in rows], ["b", "a"])
            self.assertEqual(summary["record_count"], 2)

            right.write_text(
                json.dumps({"id": "b", "source_tree": "right", "path": "a"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate inventory id"):
                merge([left, right], output, root / "summary.json")

    def test_partition_campaign_reconciles_records_and_logged_errors(self) -> None:
        from scripts.inventory.build_partition_campaign_report import build_report

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = root / "part-a"
            part.mkdir()
            (part / "inventory.jsonl").write_text("{}\n", encoding="utf-8")
            (part / "file_inventory_errors.jsonl").write_text("{}\n", encoding="utf-8")
            (part / "file_inventory_summary.json").write_text(json.dumps({
                "record_count": 1, "error_count": 1, "inventory_sha256": "abc",
                "roots": [{"files_discovered": 2, "reconciled": True}],
            }), encoding="utf-8")
            report = build_report(root)
            self.assertTrue(report["reconciled"])
            self.assertEqual(report["files_discovered"], 2)


if __name__ == "__main__":
    unittest.main()
