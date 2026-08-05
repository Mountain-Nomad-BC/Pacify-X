from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from scripts.inventory.build_archive_inventory import (
    BombThresholds,
    build_inventory,
    main,
)


def write_zip(path: Path, members: list[tuple[ZipInfo | str, bytes]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as handle:
        for name, payload in members:
            handle.writestr(name, payload)


def mark_entries_encrypted(path: Path) -> None:
    """Set encryption metadata for inventory tests without reading any payload."""
    data = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while (cursor := data.find(signature, cursor)) >= 0:
            flags = struct.unpack_from("<H", data, cursor + flag_offset)[0]
            struct.pack_into("<H", data, cursor + flag_offset, flags | 0x1)
            cursor += 4
    path.write_bytes(data)


class ArchiveInventoryTests(unittest.TestCase):
    def test_cli_writes_one_deterministic_map_per_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ZipFile(root / "one.zip", "w") as archive:
                archive.writestr("one.txt", "one")
            with ZipFile(root / "two.zip", "w") as archive:
                archive.writestr("two.txt", "two")
            output = root / "inventory.json"
            maps = root / "maps"
            status = main(
                [
                    "--root",
                    f"fixture={root}",
                    "--output",
                    str(output),
                    "--maps-dir",
                    str(maps),
                ]
            )
            self.assertEqual(status, 0)
            first = sorted(path.read_bytes() for path in maps.glob("*.json"))
            self.assertEqual(len(first), 2)
            status = main(
                [
                    "--root",
                    f"fixture={root}",
                    "--output",
                    str(output),
                    "--maps-dir",
                    str(maps),
                ]
            )
            self.assertEqual(status, 0)
            self.assertEqual(
                first, sorted(path.read_bytes() for path in maps.glob("*.json"))
            )

    def test_safe_archive_has_hash_sizes_ratio_and_no_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "packs" / "safe.zip"
            write_zip(archive, [("docs/readme.txt", b"hello world")])

            report = build_inventory([("source", root)])
            item = report["archives"][0]

            self.assertEqual(item["path"], "packs/safe.zip")
            self.assertEqual(
                item["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest()
            )
            self.assertEqual(item["size_bytes"], archive.stat().st_size)
            self.assertEqual(item["entry_count"], 1)
            self.assertGreater(item["compressed_bytes"], 0)
            self.assertEqual(item["uncompressed_bytes"], 11)
            self.assertIsInstance(item["compression_ratio"], float)
            self.assertFalse(item["extracted"])
            self.assertEqual(item["disposition"], "inventory_only")
            self.assertEqual(list(root.rglob("*")), [root / "packs", archive])

    def test_optional_entry_map_is_sanitized_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "mapped.zip"
            write_zip(
                archive,
                [("z/file.py", b"print('z')"), ("a/readme.md", b"read me")],
            )

            first = build_inventory([("source", root)], include_entries=True)
            second = build_inventory([("source", root)], include_entries=True)
            entries = first["archives"][0]["entries"]

            self.assertEqual(first, second)
            self.assertEqual(
                [item["path"] for item in entries], ["a/readme.md", "z/file.py"]
            )
            self.assertEqual(entries[0]["crc32"], "7b7278e1")
            self.assertFalse(entries[0]["encrypted"])
            self.assertFalse(entries[0]["symlink"])

    def test_detects_malicious_paths_symlink_nested_archive_and_encryption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "malicious.zip"
            symlink = ZipInfo("link")
            symlink.create_system = 3
            symlink.external_attr = 0o120777 << 16
            write_zip(
                archive,
                [
                    ("../escape.txt", b"escape"),
                    ("/absolute.txt", b"absolute"),
                    ("C:\\drive.txt", b"drive"),
                    ("nested/archive.zip", b"not opened"),
                    (symlink, b"target"),
                ],
            )
            mark_entries_encrypted(archive)

            item = build_inventory([("source", root)])["archives"][0]

            self.assertEqual(item["traversal"], ["__parent__/escape.txt"])
            self.assertEqual(item["absolute_paths"], ["absolute.txt", "drive.txt"])
            self.assertEqual(item["zip_symlinks"], ["link"])
            self.assertEqual(item["nested_archives"], ["nested/archive.zip"])
            self.assertEqual(item["encrypted_entry_count"], 5)
            self.assertEqual(item["disposition"], "quarantine_recommended")
            self.assertFalse((root / "escape.txt").exists())

    def test_configurable_bomb_thresholds_flag_archive_and_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_zip(root / "compressed.zip", [("large.txt", b"A" * 2_000)])
            thresholds = BombThresholds(
                max_entries=10,
                max_uncompressed_bytes=1_000,
                max_compression_ratio=2.0,
                max_entry_uncompressed_bytes=1_000,
                max_entry_compression_ratio=2.0,
            )

            report = build_inventory([("source", root)], thresholds=thresholds)
            item = report["archives"][0]

            self.assertTrue(item["suspicious_bomb"])
            self.assertIn("uncompressed_bytes_exceeded", item["bomb_reasons"])
            self.assertIn("compression_ratio_exceeded", item["bomb_reasons"])
            self.assertEqual(item["suspicious_entries"][0]["path"], "large.txt")
            self.assertEqual(report["bomb_thresholds"]["max_entries"], 10)

    def test_bad_zip_is_retained_as_error_without_throwing_or_moving(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "broken.zip"
            archive.write_bytes(b"not a zip")

            item = build_inventory([("source", root)])["archives"][0]

            self.assertEqual(item["errors"], ["zip_open_failed:BadZipFile"])
            self.assertEqual(item["disposition"], "review_required")
            self.assertTrue(archive.exists())
            self.assertFalse(item["extracted"])

    def test_inventory_order_and_json_are_deterministic_across_multiple_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            alpha = base / "alpha"
            zulu = base / "zulu"
            write_zip(alpha / "z.zip", [("z.txt", b"z")])
            write_zip(alpha / "a.zip", [("a.txt", b"a")])
            write_zip(zulu / "m.zip", [("m.txt", b"m")])

            first = build_inventory([("zulu", zulu), ("alpha", alpha)])
            second = build_inventory([("alpha", alpha), ("zulu", zulu)])

            self.assertEqual(first, second)
            self.assertEqual(
                [(item["root"], item["path"]) for item in first["archives"]],
                [("alpha", "a.zip"), ("alpha", "z.zip"), ("zulu", "m.zip")],
            )

    def test_cli_accepts_repeated_labeled_roots_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            first.mkdir()
            second.mkdir()
            write_zip(first / "one.zip", [("one.txt", b"1")])
            write_zip(second / "two.zip", [("two.txt", b"2")])
            output = base / "reports" / "inventory.json"

            result = main(
                [
                    "--root",
                    f"first={first}",
                    "--root",
                    f"second={second}",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(result, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["archive_count"], 2)
            self.assertNotIn(str(first), output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
