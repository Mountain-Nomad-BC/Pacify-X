from runtime.semantic_code_document import snapshot_bytes
from runtime.semantic_lsp_capabilities import LspCapabilities
from runtime.semantic_lsp_documents import LspDocumentManager, _single_replacement
from runtime.semantic_lsp_types import PositionEncoding
from tests.semantic_lsp_test_support import start_fake_client


def test_incremental_sync_handles_utf16_unicode(tmp_path):
    path = tmp_path / "a.py"
    path.write_bytes("emoji = '😀'\nvalue = 1\n".encode("utf-8"))
    client = start_fake_client(tmp_path)
    try:
        doc = client.documents.open_path("a.py")
        path.write_bytes("emoji = '😀😀'\nvalue = 22\n".encode("utf-8"))
        updated = client.documents.sync_path("a.py")
        remote = client.request("px/test/getDocument", {"uri": updated.uri})
        assert remote["text"] == path.read_bytes().decode("utf-8")
        assert updated.version == doc.version + 1
    finally:
        client.shutdown()


def test_opened_path_closes_transient_document(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    client = start_fake_client(tmp_path)
    try:
        with client.documents.opened_path("a.py") as doc:
            assert client.request("px/test/getDocument", {"uri": doc.uri}) is not None
        assert client.request("px/test/getDocument", {"uri": doc.uri}) is None
    finally:
        client.shutdown()


def test_single_replacement_reconstructs_target():
    old = "abc😀def"
    new = "abcZZ😀dQf"
    start, end, replacement = _single_replacement(old, new)
    assert old[:start] + replacement + old[end:] == new


class _RecordingTransport:
    def __init__(self):
        self.notifications = []

    def notify(self, method, params=None):
        self.notifications.append((method, params))


def test_incremental_sync_falls_back_when_minimal_diff_splits_crlf(tmp_path):
    transport = _RecordingTransport()
    manager = LspDocumentManager(
        tmp_path,
        transport,
        LspCapabilities(text_sync_kind=2, open_close=True, position_encoding=PositionEncoding.UTF16),
        language_id_for_path=lambda _path: "python",
    )
    old = snapshot_bytes("a.py", b"a\r\nb\n", max_bytes=1000)
    new = snapshot_bytes("a.py", b"a\rX\nb\n", max_bytes=1000)
    manager.open_snapshot(old)
    manager.sync_snapshot(new)
    method, params = transport.notifications[-1]
    assert method == "textDocument/didChange"
    change = params["contentChanges"][0]
    assert change["text"] == new.text
    assert change["range"]["start"] == {"line": 0, "character": 0}
