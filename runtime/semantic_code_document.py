"""Immutable source snapshots with revision and offset conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from .semantic_code_paths import normalize_relative_path, resolve_project_path
from .semantic_code_types import Position, TextRange


class SemanticDocumentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    relative_path: str
    text: str
    raw_sha256: str
    size_bytes: int
    _line_starts: tuple[int, ...]

    @property
    def line_count(self) -> int:
        return len(self._line_starts)

    def offset(self, position: Position) -> int:
        if position.line >= len(self._line_starts):
            raise SemanticDocumentError("position line exceeds document")
        start = self._line_starts[position.line]
        if position.line + 1 < len(self._line_starts):
            end = self._line_starts[position.line + 1]
        else:
            end = len(self.text)
        offset = start + position.column
        if offset > end:
            raise SemanticDocumentError("position column exceeds line")
        return offset

    def slice(self, text_range: TextRange) -> str:
        return self.text[self.offset(text_range.start):self.offset(text_range.end)]

    def line_text(self, zero_based_line: int) -> str:
        if zero_based_line < 0 or zero_based_line >= self.line_count:
            raise SemanticDocumentError("line exceeds document")
        start = self._line_starts[zero_based_line]
        end = (
            self._line_starts[zero_based_line + 1]
            if zero_based_line + 1 < self.line_count
            else len(self.text)
        )
        return self.text[start:end]


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return tuple(starts)


def snapshot_bytes(relative_path: str, raw: bytes, *, max_bytes: int) -> DocumentSnapshot:
    relative = normalize_relative_path(relative_path)
    if len(raw) > max_bytes:
        raise SemanticDocumentError(
            f"document exceeds semantic byte budget: {len(raw)} > {max_bytes}"
        )
    if b"\x00" in raw:
        raise SemanticDocumentError("binary document rejected")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SemanticDocumentError("semantic source must be UTF-8") from error
    return DocumentSnapshot(
        relative_path=relative,
        text=text,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        _line_starts=_line_starts(text),
    )


def read_document_snapshot(
    root: Path, relative_path: str, *, max_bytes: int
) -> DocumentSnapshot:
    path = resolve_project_path(root, relative_path, require_file=True)
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > max_bytes:
                raise SemanticDocumentError(
                    f"document exceeds semantic byte budget: {before.st_size} > {max_bytes}"
                )
            raw = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
    except OSError as error:
        raise SemanticDocumentError("document could not be acquired") from error

    if len(raw) > max_bytes:
        raise SemanticDocumentError(
            f"document exceeds semantic byte budget: {len(raw)} > {max_bytes}"
        )
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(raw) != after.st_size:
        raise SemanticDocumentError("document changed during acquisition")
    return snapshot_bytes(relative_path, raw, max_bytes=max_bytes)
