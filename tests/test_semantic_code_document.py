from __future__ import annotations

import pytest

from runtime.semantic_code_document import SemanticDocumentError, snapshot_bytes
from runtime.semantic_code_types import Position, TextRange


def test_snapshot_offsets_and_unicode_are_character_based():
    snap = snapshot_bytes("x.py", "α = 1\nβ = 2\n".encode(), max_bytes=100)
    assert snap.slice(TextRange(Position(1, 0), Position(1, 1))) == "β"
    assert snap.line_count == 3


def test_snapshot_rejects_binary_and_invalid_utf8():
    with pytest.raises(SemanticDocumentError):
        snapshot_bytes("x.py", b"a\x00b", max_bytes=100)
    with pytest.raises(SemanticDocumentError):
        snapshot_bytes("x.py", b"\xff", max_bytes=100)
