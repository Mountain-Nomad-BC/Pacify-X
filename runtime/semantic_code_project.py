"""Project-scoped semantic session with isolated state and refresh semantics."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from .semantic_code_cache import SemanticDocumentCache
from .semantic_code_concurrency import SingleFlight
from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_index import SemanticProjectIndex, build_semantic_project_index
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_paths import canonical_project_root
from .semantic_code_query import SymbolQuery, find_references, find_symbols, symbol_overview
from .semantic_code_registry import SemanticBackendRegistry
from .semantic_code_types import SymbolRecord


class SemanticProjectSession:
    def __init__(
        self,
        root: Path,
        *,
        registry: SemanticBackendRegistry | None = None,
        limits: SemanticCodeLimits = SemanticCodeLimits(),
        cache: SemanticDocumentCache | None = None,
        read_only: bool = True,
    ) -> None:
        self.root = canonical_project_root(root)
        self.registry = registry or SemanticBackendRegistry()
        self.limits = limits
        self.cache = cache or SemanticDocumentCache(
            max_items=min(1024, limits.max_files),
            max_bytes=limits.max_total_bytes,
        )
        self.read_only = bool(read_only)
        self._lock = RLock()
        self._flight: SingleFlight[SemanticProjectIndex] = SingleFlight()
        self._index: SemanticProjectIndex | None = None
        self._closed = False

    @property
    def project_key(self) -> str:
        return self.root.as_posix()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("semantic project session is closed")

    def refresh(self) -> SemanticProjectIndex:
        self._ensure_open()

        def build() -> SemanticProjectIndex:
            value = build_semantic_project_index(
                self.root,
                registry=self.registry,
                limits=self.limits,
                cache=self.cache,
            )
            with self._lock:
                self._index = value
            return value

        return self._flight.call(self.project_key + ":refresh", build)

    def index(self, *, refresh: bool = False) -> SemanticProjectIndex:
        self._ensure_open()
        with self._lock:
            current = self._index
        if current is None or refresh:
            return self.refresh()
        return current

    def snapshot(self, relative_path: str) -> DocumentSnapshot:
        self._ensure_open()
        return read_document_snapshot(
            self.root, relative_path, max_bytes=self.limits.max_file_bytes
        )

    def find(self, query: SymbolQuery, *, refresh: bool = False) -> tuple[SymbolRecord, ...]:
        return find_symbols(self.index(refresh=refresh), query, limits=self.limits)

    def find_unique(self, query: SymbolQuery, *, refresh: bool = False) -> SymbolRecord:
        results = self.find(query, refresh=refresh)
        if not results:
            raise LookupError(f"semantic symbol not found: {query.pattern}")
        if len(results) != 1:
            raise LookupError(
                f"semantic symbol is not unique: {query.pattern}; matches={len(results)}"
            )
        return results[0]

    def references(self, symbol_id: str, *, max_results: int = 100):
        return find_references(self.index(), symbol_id, max_results=max_results)

    def overview(self, relative_path: str, *, max_depth: int = 4, max_results: int = 200):
        return symbol_overview(
            self.index(), relative_path, max_depth=max_depth, max_results=max_results
        )

    def invalidate(self) -> None:
        with self._lock:
            self._index = None

    def close(self) -> None:
        with self._lock:
            self._index = None
            self.cache.clear()
            self._closed = True
