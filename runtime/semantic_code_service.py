"""Client-neutral facade over PACIFY-X semantic code intelligence."""

from __future__ import annotations

from pathlib import Path

from .semantic_code_diagnostics import attach_diagnostic_owners
from .semantic_code_edits import (
    SemanticEditPlan,
    plan_insert_after_symbol,
    plan_insert_before_symbol,
    plan_replace_symbol,
)
from .semantic_code_lifecycle import SemanticSessionManager
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_query import SymbolQuery
from .semantic_code_receipts import semantic_receipt
from .semantic_code_transaction import apply_semantic_edit_plan
from .semantic_code_types import SymbolKind


class SemanticCodeService:
    def __init__(self, *, max_sessions: int = 8, allow_writes: bool = False):
        self.sessions = SemanticSessionManager(max_sessions=max_sessions)
        self.allow_writes = bool(allow_writes)

    def _session(self, root: Path):
        return self.sessions.open(root, read_only=not self.allow_writes)

    def project_summary(self, root: Path, *, refresh: bool = False) -> dict[str, object]:
        index = self._session(root).index(refresh=refresh)
        result = index.as_summary()
        result["receipt"] = semantic_receipt(
            operation="semantic.project.summary",
            project_revision=index.revision,
            source_revision=None,
            result=result,
        )
        return result

    def find_symbols(
        self,
        root: Path,
        pattern: str,
        *,
        relative_path: str | None = None,
        kinds: tuple[str, ...] = (),
        substring: bool = False,
        case_sensitive: bool = True,
        max_results: int = 50,
        refresh: bool = False,
    ) -> dict[str, object]:
        session = self._session(root)
        parsed_kinds = tuple(SymbolKind(item) for item in kinds)
        query = SymbolQuery(
            pattern=pattern,
            relative_path=relative_path,
            kinds=parsed_kinds,
            substring=substring,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )
        index = session.index(refresh=refresh)
        matches = session.find(query)
        payload = [item.as_dict() for item in matches]
        return {
            "project_revision": index.revision,
            "matches": payload,
            "receipt": semantic_receipt(
                operation="semantic.symbol.find",
                project_revision=index.revision,
                source_revision=None,
                result=payload,
            ),
        }

    def symbol_overview(
        self, root: Path, relative_path: str, *, max_depth: int = 4, max_results: int = 200
    ) -> dict[str, object]:
        session = self._session(root)
        index = session.index()
        overview = session.overview(relative_path, max_depth=max_depth, max_results=max_results)
        payload = list(overview)
        return {
            "project_revision": index.revision,
            "relative_path": relative_path,
            "symbols": payload,
            "receipt": semantic_receipt(
                operation="semantic.symbol.overview",
                project_revision=index.revision,
                source_revision=None,
                result={"relative_path": relative_path, "symbols": payload},
            ),
        }

    def find_references(
        self, root: Path, symbol_id: str, *, max_results: int = 100
    ) -> dict[str, object]:
        session = self._session(root)
        index = session.index()
        refs = session.references(symbol_id, max_results=max_results)
        payload = [item.as_dict() for item in refs]
        return {
            "project_revision": index.revision,
            "references": payload,
            "receipt": semantic_receipt(
                operation="semantic.reference.find",
                project_revision=index.revision,
                source_revision=None,
                result={"symbol_id": symbol_id, "references": payload},
            ),
        }

    def diagnostics(self, root: Path, *, relative_path: str | None = None) -> dict[str, object]:
        session = self._session(root)
        index = session.index()
        diagnostics = attach_diagnostic_owners(index)
        if relative_path is not None:
            diagnostics = tuple(
                item for item in diagnostics if item.relative_path == relative_path
            )
        payload = [item.as_dict() for item in diagnostics]
        return {
            "project_revision": index.revision,
            "diagnostics": payload,
            "receipt": semantic_receipt(
                operation="semantic.diagnostics.file",
                project_revision=index.revision,
                source_revision=None,
                result={"relative_path": relative_path, "diagnostics": payload},
            ),
        }

    def _unique_symbol(self, root: Path, pattern: str, relative_path: str):
        session = self._session(root)
        symbol = session.find_unique(SymbolQuery(
            pattern=pattern,
            relative_path=relative_path,
            max_results=2,
        ))
        return session, symbol

    def plan_replace_symbol(
        self, root: Path, *, pattern: str, relative_path: str, replacement: str
    ) -> SemanticEditPlan:
        session, symbol = self._unique_symbol(root, pattern, relative_path)
        return plan_replace_symbol(session.snapshot(relative_path), symbol, replacement)

    def plan_insert_before_symbol(
        self, root: Path, *, pattern: str, relative_path: str, text: str
    ) -> SemanticEditPlan:
        session, symbol = self._unique_symbol(root, pattern, relative_path)
        return plan_insert_before_symbol(session.snapshot(relative_path), symbol, text)

    def plan_insert_after_symbol(
        self, root: Path, *, pattern: str, relative_path: str, text: str
    ) -> SemanticEditPlan:
        session, symbol = self._unique_symbol(root, pattern, relative_path)
        return plan_insert_after_symbol(session.snapshot(relative_path), symbol, text)

    def apply_plan(self, root: Path, plan: SemanticEditPlan, *, write: bool = False):
        session = self._session(root)
        if write and (not self.allow_writes or session.read_only):
            raise PermissionError("semantic code writes are not enabled for this service")
        result = apply_semantic_edit_plan(
            root,
            plan,
            write=write,
            registry=session.registry,
            limits=session.limits,
        )
        if write:
            session.invalidate()
        return result
