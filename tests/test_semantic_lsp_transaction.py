import os
from pathlib import Path
import pytest

import runtime.semantic_lsp_transaction as txn
from runtime.semantic_lsp_transaction import apply_workspace_edit_plan
from runtime.semantic_lsp_types import PositionEncoding
from runtime.semantic_lsp_uri import path_to_file_uri
from runtime.semantic_lsp_workspace import workspace_edit_plan


def _rename_plan(root):
    payload = {"changes": {}}
    for name in ("a.py", "b.py"):
        path = root / name
        payload["changes"][path_to_file_uri(path)] = [{"range": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 11}}, "newText": "Beta"}]
    return workspace_edit_plan(root, payload, operation="rename", source="test", encoding=PositionEncoding.UTF16)


def _project(root):
    (root / "a.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
    (root / "b.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")


def test_preview_is_side_effect_free(tmp_path):
    _project(tmp_path); plan = _rename_plan(tmp_path)
    result = apply_workspace_edit_plan(tmp_path, plan, encoding=PositionEncoding.UTF16, write=False)
    assert result.written is False
    assert "class Beta" in result.text["a.py"]
    assert not (tmp_path / ".px").exists()


def test_multi_file_write_applies_under_revision_checks(tmp_path):
    _project(tmp_path); plan = _rename_plan(tmp_path)
    result = apply_workspace_edit_plan(tmp_path, plan, encoding=PositionEncoding.UTF16, write=True)
    assert result.written
    assert "class Beta" in (tmp_path / "a.py").read_text()
    assert "class Beta" in (tmp_path / "b.py").read_text()


def test_stale_plan_changes_nothing(tmp_path):
    _project(tmp_path); plan = _rename_plan(tmp_path)
    (tmp_path / "b.py").write_text("class Gamma:\n    pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        apply_workspace_edit_plan(tmp_path, plan, encoding=PositionEncoding.UTF16, write=True)
    assert "Alpha" in (tmp_path / "a.py").read_text()
    assert "Gamma" in (tmp_path / "b.py").read_text()


def test_second_commit_failure_rolls_back_first(tmp_path, monkeypatch):
    _project(tmp_path); plan = _rename_plan(tmp_path)
    real_replace = txn.os.replace
    failed = {"done": False}
    def flaky(src, dst):
        if Path(dst).name == "b.py" and "lsp-stage" in Path(src).name and not failed["done"]:
            failed["done"] = True
            raise OSError("synthetic second commit failure")
        return real_replace(src, dst)
    monkeypatch.setattr(txn.os, "replace", flaky)
    with pytest.raises(OSError, match="synthetic"):
        apply_workspace_edit_plan(tmp_path, plan, encoding=PositionEncoding.UTF16, write=True)
    assert "class Alpha" in (tmp_path / "a.py").read_text()
    assert "class Alpha" in (tmp_path / "b.py").read_text()
