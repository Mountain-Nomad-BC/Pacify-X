from io import BytesIO
import pytest

from runtime.semantic_lsp_framing import LspFramingError, encode_message, read_message


def test_round_trip_unicode_message():
    raw = encode_message({"jsonrpc": "2.0", "method": "x", "params": {"emoji": "😀"}})
    assert read_message(BytesIO(raw), max_message_bytes=4096)["params"]["emoji"] == "😀"


def test_rejects_duplicate_content_length():
    raw = b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}"
    with pytest.raises(LspFramingError, match="exactly one"):
        read_message(BytesIO(raw), max_message_bytes=4096)


def test_rejects_oversized_inbound_and_outbound():
    raw = b"Content-Length: 10\r\n\r\n0123456789"
    with pytest.raises(LspFramingError, match="exceeds"):
        read_message(BytesIO(raw), max_message_bytes=5)
    with pytest.raises(LspFramingError, match="outbound"):
        encode_message({"x": "0123456789"}, max_message_bytes=5)


def test_rejects_partial_body():
    with pytest.raises(LspFramingError, match="EOF inside"):
        read_message(BytesIO(b"Content-Length: 9\r\n\r\n{}"), max_message_bytes=4096)
