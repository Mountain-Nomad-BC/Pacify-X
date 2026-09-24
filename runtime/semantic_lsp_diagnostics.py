"""Thread-safe, version-aware store for ``publishDiagnostics`` notifications."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_types import DiagnosticRecord, DiagnosticSeverity, Position, TextRange, stable_id
from .semantic_lsp_encoding import position_to_offset
from .semantic_lsp_types import LspPosition, PositionEncoding
from .semantic_lsp_uri import uri_to_relative_path


@dataclass(frozen=True, slots=True)
class DiagnosticPublication:
    uri: str
    version: int | None
    diagnostics: tuple[dict[str, Any], ...]


class LspDiagnosticStore:
    def __init__(self, *, max_files: int = 1024, max_diagnostics_per_file: int = 500):
        if max_files <= 0 or max_diagnostics_per_file <= 0:
            raise ValueError("diagnostic budgets must be positive")
        self.max_files = max_files
        self.max_diagnostics_per_file = max_diagnostics_per_file
        self._lock = RLock()
        self._by_uri: dict[str, DiagnosticPublication] = {}
        self._order: list[str] = []

    def publish(self, params: Any, *, current_version: int | None = None) -> None:
        if not isinstance(params, dict) or not isinstance(params.get("uri"), str):
            return
        uri = params["uri"]
        raw_version = params.get("version")
        version = raw_version if isinstance(raw_version, int) and not isinstance(raw_version, bool) else None
        if current_version is not None and version is not None and version < current_version:
            return
        raw = params.get("diagnostics", [])
        if not isinstance(raw, list):
            return
        diagnostics = tuple(item for item in raw[: self.max_diagnostics_per_file] if isinstance(item, dict))
        with self._lock:
            if uri not in self._by_uri:
                self._order.append(uri)
            self._by_uri[uri] = DiagnosticPublication(uri, version, diagnostics)
            while len(self._order) > self.max_files:
                oldest = self._order.pop(0)
                self._by_uri.pop(oldest, None)

    def get(self, uri: str, *, minimum_version: int | None = None) -> DiagnosticPublication | None:
        with self._lock:
            item = self._by_uri.get(uri)
        if item is None:
            return None
        if minimum_version is not None and item.version is not None and item.version < minimum_version:
            return None
        return item

    def clear(self, uri: str) -> None:
        with self._lock:
            self._by_uri.pop(uri, None)
            self._order = [item for item in self._order if item != uri]


def _wave1_position(text: str, offset: int) -> Position:
    line = text.count("\n", 0, offset)
    start = text.rfind("\n", 0, offset) + 1
    return Position(line, offset - start)


def _range(value: Any, text: str, encoding: PositionEncoding) -> TextRange:
    if not isinstance(value, dict):
        raise ValueError("diagnostic range must be an object")
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError("diagnostic range positions are required")
    lsp_start = LspPosition(int(start["line"]), int(start["character"]))
    lsp_end = LspPosition(int(end["line"]), int(end["character"]))
    a = position_to_offset(text, lsp_start, encoding)
    b = position_to_offset(text, lsp_end, encoding)
    return TextRange(_wave1_position(text, a), _wave1_position(text, b))


def normalized_diagnostics(
    root: Path,
    publication: DiagnosticPublication,
    *,
    encoding: PositionEncoding,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
    snapshot: DocumentSnapshot | None = None,
) -> tuple[DiagnosticRecord, ...]:
    relative = uri_to_relative_path(root, publication.uri)
    snapshot = snapshot or read_document_snapshot(root, relative, max_bytes=limits.max_file_bytes)
    records: list[DiagnosticRecord] = []
    for index, item in enumerate(publication.diagnostics):
        try:
            severity_raw = item.get("severity", 3)
            severity_num = severity_raw if isinstance(severity_raw, int) and not isinstance(severity_raw, bool) else 3
            severity = DiagnosticSeverity(max(1, min(int(severity_num), 4)))
            message = str(item.get("message", ""))[:8192]
            source = str(item.get("source") or "lsp")[:256]
            code_raw = item.get("code")
            code = None if code_raw is None else str(code_raw)[:256]
            location = _range(item.get("range"), snapshot.text, encoding)
        except (KeyError, TypeError, ValueError):
            continue
        records.append(
            DiagnosticRecord(
                diagnostic_id=stable_id("diag", relative, index, message, location.start.line, location.start.column),
                relative_path=relative,
                severity=severity,
                message=message,
                location=location,
                source=source,
                code=code,
            )
        )
    return tuple(records)
