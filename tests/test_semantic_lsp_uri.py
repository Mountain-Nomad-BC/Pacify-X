from pathlib import Path
import pytest

from runtime.semantic_lsp_uri import LspUriError, path_to_file_uri, relative_path_to_uri, uri_to_relative_path


def test_uri_round_trip_inside_project(tmp_path):
    file = tmp_path / "a b.py"
    file.write_text("x=1\n", encoding="utf-8")
    uri = relative_path_to_uri(tmp_path, "a b.py")
    assert uri_to_relative_path(tmp_path, uri) == "a b.py"


def test_uri_escape_rejected(tmp_path):
    outside = tmp_path.parent / "outside-lsp-test.py"
    outside.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(LspUriError, match="escapes"):
            uri_to_relative_path(tmp_path, path_to_file_uri(outside))
    finally:
        outside.unlink(missing_ok=True)
