from runtime.semantic_code_document import snapshot_bytes
from runtime.semantic_lsp_diagnostics import DiagnosticPublication, LspDiagnosticStore, normalized_diagnostics
from runtime.semantic_lsp_normalize import normalize_document_symbols
from runtime.semantic_lsp_types import PositionEncoding
from runtime.semantic_lsp_uri import relative_path_to_uri
from tests.semantic_lsp_test_support import start_fake_client, wait_until


def test_publish_diagnostics_are_version_aware_and_normalized(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = '😀'\nBROKEN_LSP\n", encoding="utf-8")
    client = start_fake_client(tmp_path)
    try:
        doc = client.documents.open_path("a.py")
        assert wait_until(lambda: client.diagnostics.get(doc.uri, minimum_version=doc.version) is not None)
        publication = client.diagnostics.get(doc.uri, minimum_version=doc.version)
        records = normalized_diagnostics(tmp_path, publication, encoding=client.capabilities.position_encoding)
        assert len(records) == 1
        assert records[0].location.start.line == 1
    finally:
        client.shutdown()


def test_stale_diagnostic_publication_is_ignored():
    store = LspDiagnosticStore()
    store.publish({"uri": "file:///x", "version": 1, "diagnostics": []}, current_version=2)
    assert store.get("file:///x") is None


def test_document_symbol_normalization_respects_utf16(tmp_path):
    text = "x='😀'\nclass Alpha:\n    pass\n"
    (tmp_path / "a.py").write_text(text, encoding="utf-8")
    snap = snapshot_bytes("a.py", text.encode(), max_bytes=10000)
    payload = [{
        "name": "Alpha", "kind": 5,
        "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 12}},
        "selectionRange": {"start": {"line": 1, "character": 6}, "end": {"line": 1, "character": 11}},
    }]
    records = normalize_document_symbols(tmp_path, "a.py", payload, language="python", encoding=PositionEncoding.UTF16, snapshot=snap)
    assert records[0].name == "Alpha"
    assert records[0].declaration.start.column == 6
