from __future__ import annotations

import ast
from pathlib import Path

from docs.architecture.tools import build_atlas
from scripts import clean_source_export


def test_repository_atlas_owner_targets_canonical_tree(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def capture(repo, out, reference, max_files, max_bytes, allow_repo_output):
        calls.append((repo, out, reference, max_files, max_bytes, allow_repo_output))

    monkeypatch.setattr(build_atlas, "build", capture)
    clean_source_export._rebuild_repository_atlas(tmp_path)
    atlas = tmp_path / "docs/architecture"
    assert calls == [
        (tmp_path, atlas, atlas / "reference", 100_000, 2 * 1024**3, True)
    ]


def test_atlas_rebuild_is_last_canonical_reconciliation_effect() -> None:
    source = Path(clean_source_export.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    owner = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_rebuild_candidate_projections_unlocked"
    )
    last = owner.body[-1]
    assert isinstance(last, ast.Expr)
    assert isinstance(last.value, ast.Call)
    assert isinstance(last.value.func, ast.Name)
    assert last.value.func.id == "_rebuild_repository_atlas"


def test_atlas_inventory_excludes_mutable_control_roots() -> None:
    assert ".tmp" in build_atlas.SKIP_DIRS
    assert ".engineering-bootstrap" in build_atlas.SKIP_DIRS
    assert "evidence" in build_atlas.SKIP_DIRS
