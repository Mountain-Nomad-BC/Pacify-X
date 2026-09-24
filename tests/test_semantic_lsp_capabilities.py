from runtime.semantic_lsp_capabilities import parse_capabilities
from runtime.semantic_lsp_types import PositionEncoding


def test_empty_option_object_means_capability_enabled():
    caps = parse_capabilities({"documentSymbolProvider": {}, "renameProvider": {"prepareProvider": True}})
    assert caps.document_symbols is True
    assert caps.rename is True and caps.prepare_rename is True


def test_sync_and_encoding_are_normalized():
    caps = parse_capabilities({"positionEncoding": "utf-8", "textDocumentSync": {"change": 2, "openClose": False}})
    assert caps.position_encoding == PositionEncoding.UTF8
    assert caps.text_sync_kind == 2 and caps.open_close is False


def test_unknown_encoding_falls_back_to_utf16():
    assert parse_capabilities({"positionEncoding": "made-up"}).position_encoding == PositionEncoding.UTF16
