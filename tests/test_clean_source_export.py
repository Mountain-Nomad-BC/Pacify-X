from __future__ import annotations

from pathlib import Path
import tempfile
import zipfile

from scripts.clean_source_export import create_clean_export


def test_clean_export_is_byte_deterministic_and_non_destructive():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "source"
        root.mkdir()
        (root / "keep.txt").write_text("keep\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git/config").write_text("private\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__/x.pyc").write_bytes(b"cache")
        first = Path(directory) / "first.zip"
        second = Path(directory) / "second.zip"
        one = create_clean_export(root, first)
        two = create_clean_export(root, second)
        assert one["archive_sha256"] == two["archive_sha256"]
        assert one["hard_delete"] is False
        assert (root / ".git/config").is_file()
        with zipfile.ZipFile(first) as archive:
            assert archive.namelist() == ["keep.txt"]
