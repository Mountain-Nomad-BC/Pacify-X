from __future__ import annotations

from pathlib import Path
import shutil
import pytest

from runtime.semantic_code_document import read_document_snapshot
from runtime.semantic_code_edits import plan_insert_after_symbol, plan_replace_symbol, render_edit_plan
from runtime.semantic_code_index import build_semantic_project_index


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_replace_plan_is_revision_bound_and_preserves_decorator_boundary(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    index = build_semantic_project_index(root)
    symbol = next(item for item in index.symbols if item.qualified_name == "pkg.models.Device.label")
    snap = read_document_snapshot(root, "pkg/models.py", max_bytes=100_000)
    plan = plan_replace_symbol(
        snap,
        symbol,
        "    @property\n    def label(self) -> str:\n        return self.name\n",
    )
    candidate = render_edit_plan(snap, plan)
    assert "@@property" not in candidate
    assert "return self.name\n" in candidate


def test_non_structural_symbol_cannot_be_used_for_wave1_edit():
    index = build_semantic_project_index(FIXTURE)
    constant = next(item for item in index.symbols if item.name == "DEFAULT_NAME")
    snap = read_document_snapshot(FIXTURE, "pkg/models.py", max_bytes=100_000)
    with pytest.raises(ValueError):
        plan_replace_symbol(snap, constant, 'DEFAULT_NAME = "x"')
