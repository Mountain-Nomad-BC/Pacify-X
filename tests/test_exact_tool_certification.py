from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime.exact_tool_certification import ToolCase, _normalized, _run, certify_exact_tools
from runtime.python_surface_certification import certify_python_surfaces


ROOT = Path(__file__).resolve().parents[1]


class ExactToolCertificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = certify_exact_tools(ROOT)
        cls.python_surfaces = certify_python_surfaces(ROOT, cls.result)

    def test_every_admitted_tool_executes_from_its_hash_bound_file(self) -> None:
        result = self.result
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["admitted_tools"], 56)
        self.assertEqual(result["directly_loaded"], 56)
        self.assertEqual(result["positive_cases"], 56)
        self.assertEqual(result["passed_tools"], 56)
        self.assertEqual(result["negative_cases"], 56)
        self.assertEqual(result["deterministic_repeat_cases"], 56)
        self.assertEqual(result["domain_wrappers"], 7)
        self.assertEqual(result["passed_domain_wrappers"], 7)
        for record in result["results"]:
            target = ROOT / record["target"]
            self.assertEqual(record["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())

    def test_every_admitted_tool_has_negative_certification_case(self) -> None:
        result = self.result
        denied = {record["id"] for record in result["results"] if record["negative_behavior"] is not None}
        self.assertEqual(denied, {record["id"] for record in result["results"]})

    def test_tool_without_boundary_case_cannot_be_fully_certified(self) -> None:
        for record in self.result["results"]:
            self.assertEqual(record["certification_strength"], "negative-path-certified")
            self.assertTrue(record["fixture_classes"]["malformed_input"])
            self.assertTrue(record["fixture_classes"]["wrong_type"])

    def test_tool_side_effects_are_measured(self) -> None:
        for record in self.result["results"]:
            behavior = record["positive_behavior"]
            self.assertIn("observed_filesystem_effects", behavior)
            self.assertIn("unexpected_filesystem_effects", behavior)
            self.assertEqual(behavior["unexpected_filesystem_effects"], [])

    def test_tool_repeat_case_is_deterministic(self) -> None:
        for record in self.result["results"]:
            self.assertTrue(record["deterministic_repeat"], record["id"])

    def test_fixture_path_normalization_handles_windows_aliases_and_case(self) -> None:
        short = r"C:\Users\RUNNER~1\AppData\Local\Temp\fixture"
        long = r"C:\Users\runneradmin\AppData\Local\Temp\fixture"
        first = _normalized({"path": short + r"\clean-repo\a.py"}, (short, long))
        second = _normalized({"path": long.upper() + "/clean-repo/a.py"}, (short, long))
        self.assertEqual(first, second)
        self.assertEqual(first["path"], "<fixture-root>/clean-repo/a.py")

    def test_tool_timeout_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "stall.py"
            script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
            result = _run(script, ToolCase((), json_output=False), root, 0.05)
            self.assertFalse(result["passed"])
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["failure_class"], "timeout")

    def test_cache_receipts_are_hash_sealed_and_forgery_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "progress.json"
            cache = Path(directory) / "cache"
            first = certify_exact_tools(ROOT, receipt_path=receipt, cache_dir=cache, allow_cache=True)
            self.assertTrue(first["valid"], first["errors"])
            self.assertTrue(receipt.is_file())
            cache_file = next(cache.glob("*.json"))
            forged = json.loads(cache_file.read_text(encoding="utf-8"))
            forged["result"]["passed"] = False
            cache_file.write_text(json.dumps(forged), encoding="utf-8")
            second = certify_exact_tools(ROOT, cache_dir=cache, allow_cache=True)
            self.assertTrue(second["valid"], second["errors"])
            self.assertFalse(next(item for item in second["results"] if item["cache_key"] == cache_file.stem)["cache_hit"])

    def test_every_python_file_is_owned_classified_and_validation_bound(self) -> None:
        result = self.python_surfaces
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["python_file_count"], result["syntax_valid_count"])
        self.assertEqual(result["role_counts"].get("unknown", 0), 0)
        self.assertEqual(result["role_counts"]["installed-skill-tool"], 83)
        self.assertEqual(result["direct_behavior_count"], 63)


if __name__ == "__main__":
    unittest.main()
