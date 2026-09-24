"""Revision-guarded semantic edit planning without implicit writes."""

from __future__ import annotations

from dataclasses import dataclass

from .semantic_code_document import DocumentSnapshot
from .semantic_code_types import SymbolKind, SymbolRecord, TextRange, stable_sha256

_EDITABLE_KINDS = frozenset({
    SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.PROPERTY
})


def _require_editable(symbol: SymbolRecord) -> None:
    if symbol.kind not in _EDITABLE_KINDS:
        raise ValueError(
            f"wave-1 semantic edits require a structural definition, got {symbol.kind.value}"
        )


@dataclass(frozen=True, slots=True)
class TextEdit:
    text_range: TextRange
    new_text: str


@dataclass(frozen=True, slots=True)
class SemanticEditPlan:
    relative_path: str
    expected_sha256: str
    operation: str
    target_symbol_ids: tuple[str, ...]
    edits: tuple[TextEdit, ...]
    plan_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "expected_sha256": self.expected_sha256,
            "operation": self.operation,
            "target_symbol_ids": list(self.target_symbol_ids),
            "edits": [
                {
                    "start": {"line": item.text_range.start.line, "column": item.text_range.start.column},
                    "end": {"line": item.text_range.end.line, "column": item.text_range.end.column},
                    "new_text": item.new_text,
                }
                for item in self.edits
            ],
            "plan_sha256": self.plan_sha256,
        }


def _build_plan(
    snapshot: DocumentSnapshot,
    *,
    operation: str,
    targets: tuple[SymbolRecord, ...],
    edits: tuple[TextEdit, ...],
) -> SemanticEditPlan:
    if not edits:
        raise ValueError("semantic edit plan requires at least one edit")
    if any(target.relative_path != snapshot.relative_path for target in targets):
        raise ValueError("all semantic edit targets must belong to the snapshot file")
    ordered = sorted(edits, key=lambda item: (
        snapshot.offset(item.text_range.start), snapshot.offset(item.text_range.end)
    ))
    previous_end = -1
    for edit in ordered:
        start = snapshot.offset(edit.text_range.start)
        end = snapshot.offset(edit.text_range.end)
        if start < previous_end:
            raise ValueError("semantic edit ranges overlap")
        previous_end = end
    target_ids = tuple(sorted({item.symbol_id for item in targets}))
    digest_payload = {
        "relative_path": snapshot.relative_path,
        "expected_sha256": snapshot.raw_sha256,
        "operation": operation,
        "target_symbol_ids": target_ids,
        "edits": [
            (
                edit.text_range.start.line,
                edit.text_range.start.column,
                edit.text_range.end.line,
                edit.text_range.end.column,
                edit.new_text,
            )
            for edit in ordered
        ],
    }
    return SemanticEditPlan(
        relative_path=snapshot.relative_path,
        expected_sha256=snapshot.raw_sha256,
        operation=operation,
        target_symbol_ids=target_ids,
        edits=tuple(ordered),
        plan_sha256=stable_sha256(digest_payload),
    )


def plan_replace_symbol(
    snapshot: DocumentSnapshot, symbol: SymbolRecord, replacement: str
) -> SemanticEditPlan:
    _require_editable(symbol)
    if not isinstance(replacement, str) or not replacement.strip():
        raise ValueError("replacement must be non-empty text")
    return _build_plan(
        snapshot,
        operation="replace_symbol",
        targets=(symbol,),
        edits=(TextEdit(symbol.body, replacement),),
    )


def plan_insert_before_symbol(
    snapshot: DocumentSnapshot, symbol: SymbolRecord, text: str
) -> SemanticEditPlan:
    _require_editable(symbol)
    if not isinstance(text, str) or not text:
        raise ValueError("insert text must be non-empty")
    point = TextRange(symbol.body.start, symbol.body.start)
    return _build_plan(
        snapshot,
        operation="insert_before_symbol",
        targets=(symbol,),
        edits=(TextEdit(point, text),),
    )


def plan_insert_after_symbol(
    snapshot: DocumentSnapshot, symbol: SymbolRecord, text: str
) -> SemanticEditPlan:
    _require_editable(symbol)
    if not isinstance(text, str) or not text:
        raise ValueError("insert text must be non-empty")
    point = TextRange(symbol.body.end, symbol.body.end)
    return _build_plan(
        snapshot,
        operation="insert_after_symbol",
        targets=(symbol,),
        edits=(TextEdit(point, text),),
    )


def render_edit_plan(snapshot: DocumentSnapshot, plan: SemanticEditPlan) -> str:
    if snapshot.relative_path != plan.relative_path:
        raise ValueError("semantic edit plan path does not match snapshot")
    if snapshot.raw_sha256 != plan.expected_sha256:
        raise ValueError("semantic edit plan source revision is stale")
    edits = []
    for edit in plan.edits:
        edits.append((
            snapshot.offset(edit.text_range.start),
            snapshot.offset(edit.text_range.end),
            edit.new_text,
        ))
    text = snapshot.text
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
