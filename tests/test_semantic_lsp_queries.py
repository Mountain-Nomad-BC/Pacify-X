from runtime.semantic_code_types import Position
from runtime.semantic_lsp_queries import LspQueryService
from runtime.semantic_lsp_uri import uri_to_relative_path
from tests.semantic_lsp_test_support import start_fake_client


def _project(root):
    (root / "a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
    (root / "b.py").write_text("from a import Alpha\nvalue = Alpha()\n", encoding="utf-8")


def test_symbols_definition_references_and_rename_plan(tmp_path):
    _project(tmp_path)
    client = start_fake_client(tmp_path)
    try:
        query = LspQueryService(client)
        symbols = query.document_symbols("a.py")
        assert [s.name for s in symbols] == ["Alpha"]
        definition = query.definitions("b.py", Position(1, 9))
        assert uri_to_relative_path(tmp_path, definition[0].uri) == "a.py"
        references = query.references("b.py", Position(1, 9))
        assert len(references) >= 3
        plan = query.rename("b.py", Position(1, 9), "Beta")
        assert set(plan.expected_sha256) == {"a.py", "b.py"}
        assert client.documents.current("b.py") is None
    finally:
        client.shutdown()
