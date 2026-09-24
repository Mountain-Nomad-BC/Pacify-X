"""Containment-safe parsing and rendering of server-proposed WorkspaceEdits."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .semantic_code_document import read_document_snapshot
from .semantic_code_limits import SemanticCodeLimits
from .semantic_lsp_encoding import range_to_offsets
from .semantic_lsp_normalize import parse_range
from .semantic_lsp_types import LspTextEdit, PositionEncoding, WorkspaceEditPlan
from .semantic_lsp_uri import uri_to_relative_path


class WorkspaceEditError(ValueError):
    pass


def _parse_text_edit(uri: str, value: Any, version: int | None) -> LspTextEdit:
    if not isinstance(value, dict) or not isinstance(value.get("newText"), str):
        raise WorkspaceEditError("workspace text edit requires range and newText")
    annotation = value.get("annotationId")
    if annotation is not None and not isinstance(annotation, str):
        raise WorkspaceEditError("workspace edit annotationId must be text")
    return LspTextEdit(uri, parse_range(value.get("range")), value["newText"], version, annotation)


def workspace_edit_plan(
    root: Path,
    payload: Any,
    *,
    operation: str,
    source: str,
    encoding: PositionEncoding,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
) -> WorkspaceEditPlan:
    if not isinstance(payload, dict):
        raise WorkspaceEditError("workspace edit must be an object")
    edits: list[LspTextEdit] = []

    changes = payload.get("changes")
    if changes is not None:
        if not isinstance(changes, dict):
            raise WorkspaceEditError("workspace edit changes must be an object")
        for uri, raw_edits in changes.items():
            if not isinstance(uri, str) or not isinstance(raw_edits, list):
                raise WorkspaceEditError("workspace edit changes are malformed")
            uri_to_relative_path(root, uri)
            edits.extend(_parse_text_edit(uri, item, None) for item in raw_edits)

    document_changes = payload.get("documentChanges")
    if document_changes is not None:
        if not isinstance(document_changes, list):
            raise WorkspaceEditError("documentChanges must be a list")
        for change in document_changes:
            if not isinstance(change, dict):
                raise WorkspaceEditError("documentChanges entry must be an object")
            if "kind" in change:
                raise WorkspaceEditError("Wave 2 rejects create/rename/delete resource operations")
            text_document = change.get("textDocument")
            raw_edits = change.get("edits")
            if not isinstance(text_document, dict) or not isinstance(text_document.get("uri"), str) or not isinstance(raw_edits, list):
                raise WorkspaceEditError("TextDocumentEdit is malformed")
            uri = text_document["uri"]
            uri_to_relative_path(root, uri)
            raw_version = text_document.get("version")
            version = raw_version if isinstance(raw_version, int) and not isinstance(raw_version, bool) else None
            edits.extend(_parse_text_edit(uri, item, version) for item in raw_edits)

    if not edits:
        raise WorkspaceEditError("workspace edit contains no supported text edits")
    if len(edits) > limits.max_results * 20:
        raise WorkspaceEditError("workspace edit exceeds edit-count budget")

    expected: dict[str, str] = {}
    by_relative: dict[str, list[LspTextEdit]] = defaultdict(list)
    for edit in edits:
        relative = uri_to_relative_path(root, edit.uri)
        by_relative[relative].append(edit)
    for relative, file_edits in by_relative.items():
        snapshot = read_document_snapshot(root, relative, max_bytes=limits.max_file_bytes)
        expected[relative] = snapshot.raw_sha256
        spans: list[tuple[int, int]] = []
        for edit in file_edits:
            try:
                spans.append(range_to_offsets(snapshot.text, edit.range, encoding))
            except ValueError as exc:
                raise WorkspaceEditError(f"invalid edit range in {relative}: {exc}") from exc
        spans.sort()
        for previous, current in zip(spans, spans[1:]):
            if current[0] < previous[1] or (current[0] == previous[0] and current[1] == previous[1]):
                raise WorkspaceEditError(f"overlapping or duplicate workspace edits in {relative}")

    ordered = tuple(sorted(edits, key=lambda item: (uri_to_relative_path(root, item.uri), item.range.start, item.range.end, item.new_text)))
    return WorkspaceEditPlan(operation=operation, edits=ordered, expected_sha256=expected, source=source)


def render_workspace_edit(
    root: Path,
    plan: WorkspaceEditPlan,
    *,
    encoding: PositionEncoding,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
) -> dict[str, str]:
    by_relative: dict[str, list[LspTextEdit]] = defaultdict(list)
    for edit in plan.edits:
        by_relative[uri_to_relative_path(root, edit.uri)].append(edit)
    rendered: dict[str, str] = {}
    for relative in sorted(by_relative):
        snapshot = read_document_snapshot(root, relative, max_bytes=limits.max_file_bytes)
        expected = plan.expected_sha256.get(relative)
        if expected != snapshot.raw_sha256:
            raise WorkspaceEditError(f"workspace edit source revision is stale: {relative}")
        offset_edits: list[tuple[int, int, str]] = []
        for edit in by_relative[relative]:
            start, end = range_to_offsets(snapshot.text, edit.range, encoding)
            offset_edits.append((start, end, edit.new_text))
        offset_edits.sort(key=lambda item: (item[0], item[1]), reverse=True)
        text = snapshot.text
        last_start = len(text) + 1
        for start, end, replacement in offset_edits:
            if end > last_start:
                raise WorkspaceEditError(f"workspace edits overlap after normalization: {relative}")
            text = text[:start] + replacement + text[end:]
            last_start = start
        if len(text.encode("utf-8")) > limits.max_file_bytes:
            raise WorkspaceEditError(f"workspace edit candidate exceeds file budget: {relative}")
        rendered[relative] = text
    return rendered
