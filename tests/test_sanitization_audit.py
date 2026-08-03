from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.audit_sanitization import audit


class SanitizationAuditTests(unittest.TestCase):
    def test_clean_tree_passes_and_embedded_word_does_not_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "brief.txt").write_text("governed retrieval system with deterministic rails", encoding="utf-8")
            result = audit(root)
            self.assertTrue(result["valid"])

    def test_private_token_and_zip_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = "re" + "my"
            (root / "mention.txt").write_text(token, encoding="utf-8")
            (root / "archive.zip").write_bytes(b"PK")
            result = audit(root)
            self.assertFalse(result["valid"])
            self.assertEqual(result["identifier_hit_count"], 1)
            self.assertEqual(result["active_zip_count"], 1)

    def test_brand_token_inside_domain_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "domain.txt").write_text("rh" + "eemglobal.example", encoding="utf-8")
            self.assertEqual(audit(root)["identifier_hit_count"], 1)

    def test_legacy_abbreviated_placeholder_is_non_certifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "legacy.txt").write_text("governed" + "_" + "retrieval", encoding="utf-8")
            result = audit(root)
            self.assertFalse(result["valid"])
            self.assertEqual(result["legacy_placeholder_hit_count"], 1)

    def test_legacy_placeholder_inside_identifier_is_non_certifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = "governed" + "_" + "retrieval"
            (root / "legacy.txt").write_text(legacy + "_rebuild", encoding="utf-8")
            self.assertEqual(audit(root)["legacy_placeholder_hit_count"], 1)

    def test_canonical_identifier_across_chunk_boundary_is_not_a_legacy_hit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = "governed" + "_" + "retrieval"
            canonical = legacy + "_system_with_deterministic_rails"
            prefix = "x" * (1024 * 1024 - len(legacy))
            (root / "boundary.txt").write_text(prefix + canonical, encoding="utf-8")
            result = audit(root)
            self.assertTrue(result["valid"])
            self.assertEqual(result["legacy_placeholder_hit_count"], 0)

    def test_sanitation_summary_preserves_individual_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            gates = audit(Path(directory))["gates"]
            self.assertEqual(gates["brand_identifier_sanitation"]["status"], "passed")
            self.assertEqual(gates["secret_scanning"]["status"], "not_run")

    def test_not_run_secret_scan_cannot_be_reported_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(audit(Path(directory))["gates"]["secret_scanning"]["disposition"], "not_run")

    def test_scanner_exclusions_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = audit(Path(directory), excluded_names=frozenset({"ignored"}))
            self.assertIn("ignored", result["gates"]["archive_detection"]["exclusions"])


if __name__ == "__main__":
    unittest.main()
