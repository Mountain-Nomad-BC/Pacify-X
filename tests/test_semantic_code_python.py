from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_document import read_document_snapshot
from runtime.semantic_code_python import PythonAstSemanticBackend
from runtime.semantic_code_types import SymbolKind


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_python_backend_extracts_nested_symbols_and_decorators():
    snap = read_document_snapshot(FIXTURE, "pkg/models.py", max_bytes=100_000)
    doc = PythonAstSemanticBackend().analyze(snap)
    by_qname = {item.qualified_name: item for item in doc.symbols}
    assert "pkg.models.Device.status" in by_qname
    assert by_qname["pkg.models.Device.status"].kind == SymbolKind.METHOD
    assert by_qname["pkg.models.Device.label"].kind == SymbolKind.PROPERTY
    assert by_qname["pkg.models.DEFAULT_NAME"].kind == SymbolKind.CONSTANT
    assert "property" in by_qname["pkg.models.Device.label"].decorators


def test_python_backend_preserves_unicode_ast_columns():
    snap = read_document_snapshot(FIXTURE, "pkg/unicode_sample.py", max_bytes=100_000)
    doc = PythonAstSemanticBackend().analyze(snap)
    symbol = next(item for item in doc.symbols if item.name == "café")
    assert snap.slice(symbol.body).startswith("def café")


def test_syntax_failure_becomes_diagnostic_not_exception():
    snap = read_document_snapshot(FIXTURE, "broken.py", max_bytes=100_000)
    doc = PythonAstSemanticBackend().analyze(snap)
    assert not doc.symbols
    assert len(doc.diagnostics) == 1
    assert doc.diagnostics[0].code == "syntax-error"
