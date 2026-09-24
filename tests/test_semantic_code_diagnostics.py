from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_diagnostics import attach_diagnostic_owners, validate_candidate_text
from runtime.semantic_code_index import build_semantic_project_index


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_candidate_diagnostics_detect_syntax_failure():
    diagnostics = validate_candidate_text("x.py", "def x(:\n    pass\n")
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "python-ast"


def test_project_diagnostics_are_returned_without_crashing_on_broken_file():
    index = build_semantic_project_index(FIXTURE)
    diagnostics = attach_diagnostic_owners(index)
    assert any(item.relative_path == "broken.py" for item in diagnostics)
