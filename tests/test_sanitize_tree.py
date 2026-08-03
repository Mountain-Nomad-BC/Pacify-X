from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.sanitize_tree import SanitizationPreflightError, _sanitized_component, sanitize_tree


class SanitizeTreeTests(unittest.TestCase):
    def test_preview_and_apply_sanitize_content_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = "re" + "my"
            path = root / f"{token}.txt"
            path.write_text(f"about {token}", encoding="utf-8")
            preview = sanitize_tree(root)
            self.assertEqual(preview["content_change_count"], 1)
            self.assertEqual(preview["path_change_count"], 1)
            applied = sanitize_tree(root, apply=True, preservation_root=root.parent / f"{root.name}-quarantine")
            self.assertEqual(applied["binary_hit_count"], 0)
            cleaned = root / "governed_retrieval_system_with_deterministic_rails.txt"
            self.assertTrue(cleaned.is_file())
            self.assertEqual(cleaned.read_text(encoding="utf-8"), "about governed_retrieval_system_with_deterministic_rails")

    def test_brand_token_is_removed_even_when_attached_to_a_domain_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = "rh" + "eem" + "global.example"
            path = root / "url.txt"
            path.write_text(token, encoding="utf-8")
            sanitize_tree(root, apply=True, preservation_root=root.parent / f"{root.name}-quarantine")
            self.assertEqual(path.read_text(encoding="utf-8"), "enterpriseglobal.example")

    def test_legacy_alias_inside_longer_identifier_is_expanded_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = "governed" + "_" + "retrieval"
            canonical = legacy + "_system_with_deterministic_rails"
            path = root / "identifier.txt"
            path.write_text(legacy + "_rebuild\n" + canonical, encoding="utf-8")
            sanitize_tree(root, apply=True, preservation_root=root.parent / f"{root.name}-quarantine")
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                canonical + "_rebuild\n" + canonical,
            )

    def test_overlong_expansion_uses_deterministic_sanitized_component(self) -> None:
        legacy = ("governed" + "_" + "retrieval" + "_") * 20 + "record.md"
        first = _sanitized_component(legacy)
        self.assertEqual(first, _sanitized_component(legacy))
        self.assertLessEqual(len(first), 240)
        self.assertTrue(first.startswith("sanitized-"))
        self.assertTrue(first.endswith(".md"))

    def test_colliding_sanitized_paths_preserve_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = "governed" + "_" + "retrieval"
            canonical = legacy + "_system_with_deterministic_rails"
            (root / f"{legacy}.txt").write_text("legacy source", encoding="utf-8")
            (root / f"{canonical}.txt").write_text("canonical source", encoding="utf-8")
            result = sanitize_tree(root, apply=True, preservation_root=root.parent / f"{root.name}-quarantine")
            self.assertEqual(result["path_change_count"], 1)
            self.assertEqual(len(list(root.glob("*.txt"))), 2)
            self.assertFalse(any(legacy + ".txt" == path.name for path in root.glob("*.txt")))

    def test_explicit_exclusion_keeps_bounded_run_out_of_named_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            excluded = root / "large-target"
            excluded.mkdir()
            token = "re" + "my"
            (excluded / "source.txt").write_text(token, encoding="utf-8")
            result = sanitize_tree(
                root, apply=True, excluded_names=frozenset({excluded.name}),
                preservation_root=root.parent / f"{root.name}-quarantine",
            )
            self.assertEqual(result["content_change_count"], 0)
            self.assertEqual((excluded / "source.txt").read_text(encoding="utf-8"), token)

    def test_apply_fails_closed_and_reports_preservation_scan_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("ordinary text", encoding="utf-8")
            preservation = root.parent / f"{root.name}-quarantine"
            with mock.patch("scripts.sanitize_tree._text_requires_change", side_effect=OSError("denied")):
                with self.assertRaises(SanitizationPreflightError) as raised:
                    sanitize_tree(root, apply=True, preservation_root=preservation)
            self.assertEqual(len(raised.exception.errors), 1)
            self.assertIn("source.txt: OSError", raised.exception.errors[0])
            self.assertEqual(source.read_text(encoding="utf-8"), "ordinary text")


if __name__ == "__main__":
    unittest.main()
