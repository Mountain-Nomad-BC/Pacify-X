"""Lossless conversion between Python code-point offsets and negotiated LSP positions."""
from __future__ import annotations

from .semantic_lsp_types import LspPosition, LspRange, PositionEncoding


class LspPositionError(ValueError):
    pass


def _line_bounds(text: str, line: int) -> tuple[int, int]:
    if type(line) is not int or line < 0:
        raise LspPositionError("line must be a non-negative integer")
    start = 0
    current = 0
    while current < line:
        newline = text.find("\n", start)
        if newline < 0:
            raise LspPositionError("LSP line exceeds document")
        start = newline + 1
        current += 1
    newline = text.find("\n", start)
    end = len(text) if newline < 0 else newline
    if end > start and text[end - 1] == "\r":
        end -= 1
    return start, end


def _units(value: str, encoding: PositionEncoding) -> int:
    if encoding == PositionEncoding.UTF32:
        return len(value)
    if encoding == PositionEncoding.UTF16:
        return len(value.encode("utf-16-le")) // 2
    if encoding == PositionEncoding.UTF8:
        return len(value.encode("utf-8"))
    raise LspPositionError(f"unsupported LSP position encoding: {encoding}")


def offset_to_position(text: str, offset: int, encoding: PositionEncoding = PositionEncoding.UTF16) -> LspPosition:
    if type(offset) is not int or offset < 0 or offset > len(text):
        raise LspPositionError("offset outside document")
    line = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    # Positions inside a CRLF line ending are not valid text positions.
    if offset > line_start and offset <= len(text) and text[offset - 1:offset] == "\r" and text[offset:offset + 1] == "\n":
        raise LspPositionError("offset falls inside CRLF line ending")
    return LspPosition(line, _units(text[line_start:offset], encoding))


def position_to_offset(text: str, position: LspPosition, encoding: PositionEncoding = PositionEncoding.UTF16) -> int:
    start, end = _line_bounds(text, position.line)
    line_text = text[start:end]
    target = position.character
    if target == 0:
        return start
    if encoding == PositionEncoding.UTF32:
        if target > len(line_text):
            raise LspPositionError("LSP character exceeds line")
        return start + target
    total = 0
    for index, char in enumerate(line_text):
        total += _units(char, encoding)
        if total == target:
            return start + index + 1
        if total > target:
            raise LspPositionError("LSP character splits an encoded character")
    if total == target:
        return end
    raise LspPositionError("LSP character exceeds line")


def range_to_offsets(text: str, text_range: LspRange, encoding: PositionEncoding = PositionEncoding.UTF16) -> tuple[int, int]:
    start = position_to_offset(text, text_range.start, encoding)
    end = position_to_offset(text, text_range.end, encoding)
    if end < start:
        raise LspPositionError("LSP range end precedes start")
    return start, end


def offsets_to_range(text: str, start: int, end: int, encoding: PositionEncoding = PositionEncoding.UTF16) -> LspRange:
    if end < start:
        raise LspPositionError("offset range end precedes start")
    return LspRange(offset_to_position(text, start, encoding), offset_to_position(text, end, encoding))
