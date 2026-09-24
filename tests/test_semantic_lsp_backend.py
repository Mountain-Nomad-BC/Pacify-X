from dataclasses import replace

import pytest

from runtime.semantic_code_document import snapshot_bytes
from runtime.semantic_lsp_backend import LspSemanticBackend
from tests.semantic_lsp_test_support import start_fake_client


def test_lsp_backend_can_analyze_candidate_snapshot_without_writing_it(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("class Old:\n    pass\n", encoding="utf-8")
    client = start_fake_client(tmp_path)
    try:
        candidate = snapshot_bytes("a.py", b"class New:\n    pass\n", max_bytes=10000)
        analysis = LspSemanticBackend(client).analyze(candidate)
        assert [item.name for item in analysis.symbols] == ["New"]
        assert "class Old" in path.read_text(encoding="utf-8")
    finally:
        client.shutdown()


def test_lsp_backend_refuses_unsaved_candidate_when_server_declares_no_sync(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("class Old:\n    pass\n", encoding="utf-8")
    client = start_fake_client(tmp_path)
    try:
        client.capabilities = replace(client.capabilities, text_sync_kind=0)
        candidate = snapshot_bytes("a.py", b"class New:\n    pass\n", max_bytes=10000)
        with pytest.raises(RuntimeError, match="cannot truthfully analyze an unsaved candidate"):
            LspSemanticBackend(client).analyze(candidate)
    finally:
        client.shutdown()
