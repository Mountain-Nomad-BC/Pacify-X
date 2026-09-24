import pytest

from runtime.semantic_lsp_encoding import LspPositionError, offset_to_position, position_to_offset
from runtime.semantic_lsp_types import LspPosition, PositionEncoding


@pytest.mark.parametrize("encoding", list(PositionEncoding))
def test_position_round_trip_for_unicode(encoding):
    text = "a😀é\nβz\n"
    for offset in range(len(text) + 1):
        if offset and offset < len(text) and text[offset - 1] == "\r" and text[offset] == "\n":
            continue
        position = offset_to_position(text, offset, encoding)
        assert position_to_offset(text, position, encoding) == offset


def test_utf16_counts_non_bmp_as_two_units():
    assert offset_to_position("😀x", 1, PositionEncoding.UTF16) == LspPosition(0, 2)
    with pytest.raises(LspPositionError, match="splits"):
        position_to_offset("😀x", LspPosition(0, 1), PositionEncoding.UTF16)


def test_crlf_end_is_not_addressable_as_text_character():
    text = "abc\r\ndef"
    assert position_to_offset(text, LspPosition(0, 3)) == 3
    with pytest.raises(LspPositionError):
        position_to_offset(text, LspPosition(0, 4))
