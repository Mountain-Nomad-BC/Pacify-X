import pytest

from runtime.semantic_lsp_types import PositionEncoding
from runtime.semantic_lsp_uri import path_to_file_uri
from runtime.semantic_lsp_workspace import WorkspaceEditError, render_workspace_edit, workspace_edit_plan


def _edit(uri, start, end, text):
    return {"changes": {uri: [{"range": {"start": {"line": 0, "character": start}, "end": {"line": 0, "character": end}}, "newText": text}]}}


def test_workspace_edit_is_revision_bound_and_rendered(tmp_path):
    path = tmp_path / "a.py"; path.write_bytes(b"Alpha = 1\n")
    uri = path_to_file_uri(path)
    plan = workspace_edit_plan(tmp_path, _edit(uri, 0, 5, "Beta"), operation="rename", source="fake", encoding=PositionEncoding.UTF16)
    assert render_workspace_edit(tmp_path, plan, encoding=PositionEncoding.UTF16)["a.py"] == "Beta = 1\n"


def test_workspace_edit_rejects_external_uri(tmp_path):
    outside = tmp_path.parent / "outside-wave2.py"; outside.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(ValueError):
            workspace_edit_plan(tmp_path, _edit(path_to_file_uri(outside), 0, 1, "y"), operation="x", source="fake", encoding=PositionEncoding.UTF16)
    finally:
        outside.unlink(missing_ok=True)


def test_workspace_edit_rejects_resource_operations(tmp_path):
    with pytest.raises(WorkspaceEditError, match="resource"):
        workspace_edit_plan(tmp_path, {"documentChanges": [{"kind": "create", "uri": path_to_file_uri(tmp_path / 'x.py')}]}, operation="x", source="fake", encoding=PositionEncoding.UTF16)


def test_workspace_edit_rejects_overlap(tmp_path):
    path = tmp_path / "a.py"; path.write_text("abcdef\n", encoding="utf-8")
    uri = path_to_file_uri(path)
    payload = {"changes": {uri: [
        {"range": {"start": {"line": 0, "character": 1}, "end": {"line": 0, "character": 4}}, "newText": "X"},
        {"range": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 5}}, "newText": "Y"},
    ]}}
    with pytest.raises(WorkspaceEditError, match="overlapping"):
        workspace_edit_plan(tmp_path, payload, operation="x", source="fake", encoding=PositionEncoding.UTF16)
