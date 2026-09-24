"""Build immutable, bounded semantic indexes for project source code."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterable

from .bounded_walk import WalkLimits, bounded_walk
from .semantic_code_cache import SemanticDocumentCache
from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_limits import Deadline, SemanticCodeLimits, enforce_count
from .semantic_code_paths import canonical_project_root
from .semantic_code_registry import SemanticBackendRegistry
from .semantic_code_types import (
    DiagnosticRecord,
    ImportRecord,
    ReferenceRecord,
    ReferenceResolution,
    SemanticDocument,
    SymbolRecord,
    stable_sha256,
)


DEFAULT_EXCLUDED_PARTS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".px",
})


@dataclass(frozen=True, slots=True)
class SemanticProjectIndex:
    project_root: str
    revision: str
    documents: tuple[SemanticDocument, ...]
    symbols: tuple[SymbolRecord, ...]
    references: tuple[ReferenceRecord, ...]
    imports: tuple[ImportRecord, ...]
    diagnostics: tuple[DiagnosticRecord, ...]
    analyzed_files: int
    analyzed_bytes: int

    def symbol_map(self) -> dict[str, SymbolRecord]:
        return {item.symbol_id: item for item in self.symbols}

    def document_map(self) -> dict[str, SemanticDocument]:
        return {item.relative_path: item for item in self.documents}

    def as_summary(self) -> dict[str, object]:
        return {
            "project_root": self.project_root,
            "revision": self.revision,
            "analyzed_files": self.analyzed_files,
            "analyzed_bytes": self.analyzed_bytes,
            "symbol_count": len(self.symbols),
            "reference_count": len(self.references),
            "diagnostic_count": len(self.diagnostics),
        }


def _excluded(relative: str, suffixes: set[str], extra_parts: frozenset[str]) -> bool:
    path = PurePosixPath(relative)
    if any(part in extra_parts for part in path.parts):
        return True
    name = path.name
    suffix = path.suffix.casefold()
    # bounded_walk cannot tell the exclusion callback whether an entry is a file.
    # Restrict obvious non-source leaf names while preserving extensionless directories.
    if "." in name and not name.startswith(".") and suffix and suffix not in suffixes:
        return True
    return False


def _resolve_references(
    symbols: tuple[SymbolRecord, ...],
    references: tuple[ReferenceRecord, ...],
) -> tuple[ReferenceRecord, ...]:
    by_name: dict[str, list[SymbolRecord]] = {}
    by_qualified: dict[str, list[SymbolRecord]] = {}
    by_tail: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        by_name.setdefault(symbol.name, []).append(symbol)
        by_qualified.setdefault(symbol.qualified_name, []).append(symbol)
        parts = symbol.qualified_name.split(".")
        for offset in range(len(parts)):
            by_tail.setdefault(".".join(parts[offset:]), []).append(symbol)

    source_symbols = {item.symbol_id: item for item in symbols}
    result: list[ReferenceRecord] = []
    for reference in references:
        candidates: list[SymbolRecord] = []
        if reference.name in by_qualified:
            candidates.extend(by_qualified[reference.name])
        if "." in reference.name:
            candidates.extend(by_tail.get(reference.name, ()))
            leaf = reference.name.rsplit(".", 1)[-1]
            candidates.extend(by_name.get(leaf, ()))
        else:
            candidates.extend(by_name.get(reference.name, ()))

        unique = {item.symbol_id: item for item in candidates}
        source = source_symbols.get(reference.source_symbol_id or "")
        if source is not None and len(unique) > 1:
            same_file = {
                key: value for key, value in unique.items()
                if value.relative_path == source.relative_path
            }
            if same_file:
                unique = same_file
        target_ids = tuple(sorted(unique))
        if len(target_ids) == 1:
            resolution = ReferenceResolution.RESOLVED
        elif target_ids:
            resolution = ReferenceResolution.AMBIGUOUS
        else:
            resolution = ReferenceResolution.UNRESOLVED
        result.append(replace(
            reference,
            target_symbol_ids=target_ids,
            resolution=resolution,
        ))
    return tuple(result)


def build_semantic_project_index(
    root: Path,
    *,
    registry: SemanticBackendRegistry | None = None,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
    cache: SemanticDocumentCache | None = None,
    excluded_parts: Iterable[str] = DEFAULT_EXCLUDED_PARTS,
) -> SemanticProjectIndex:
    root = canonical_project_root(root)
    registry = registry or SemanticBackendRegistry()
    suffixes = set(registry.suffixes())
    excluded_set = frozenset(str(item) for item in excluded_parts)
    deadline = Deadline(limits.max_duration_seconds)

    walk = bounded_walk(
        root,
        limits=WalkLimits(
            max_files=max(limits.max_files * 4, limits.max_files),
            max_depth=96,
            max_bytes=max(limits.max_total_bytes * 64, 512 * 1024 * 1024),
            max_entries=max(limits.max_files * 200, 100_000),
            max_directories=max(limits.max_files * 20, 10_000),
            max_duration_seconds=limits.max_duration_seconds,
        ),
        symlink_policy="skip",
        exclude=lambda relative: _excluded(relative, suffixes, excluded_set),
    )

    documents: list[SemanticDocument] = []
    total_bytes = 0
    for entry in walk.files:
        deadline.check()
        backend = registry.for_path(entry.relative)
        if backend is None:
            continue
        enforce_count("semantic_code_max_files_exceeded", len(documents) + 1, limits.max_files)
        if entry.size is not None and entry.size > limits.max_file_bytes:
            continue
        snapshot = read_document_snapshot(root, entry.relative, max_bytes=limits.max_file_bytes)
        if total_bytes + snapshot.size_bytes > limits.max_total_bytes:
            raise ValueError(
                "semantic source byte budget exceeded before analysis: "
                f"{total_bytes + snapshot.size_bytes} > {limits.max_total_bytes}"
            )
        total_bytes += snapshot.size_bytes
        document = cache.get(entry.relative, snapshot.raw_sha256, backend.key) if cache else None
        if document is None:
            document = backend.analyze(snapshot)
            if cache is not None:
                cache.put(document, backend.key)
        documents.append(document)

    documents.sort(key=lambda item: item.relative_path)
    symbols = tuple(
        sorted(
            (symbol for document in documents for symbol in document.symbols),
            key=lambda item: (item.relative_path, item.declaration.start, item.qualified_name),
        )
    )
    enforce_count("semantic_code_max_symbols_exceeded", len(symbols), limits.max_symbols)
    raw_references = tuple(
        sorted(
            (reference for document in documents for reference in document.references),
            key=lambda item: (item.relative_path, item.location.start, item.name),
        )
    )
    enforce_count(
        "semantic_code_max_references_exceeded", len(raw_references), limits.max_references
    )
    references = _resolve_references(symbols, raw_references)
    imports = tuple(
        sorted(
            (item for document in documents for item in document.imports),
            key=lambda item: (item.relative_path, item.location.start, item.module),
        )
    )
    diagnostics = tuple(
        sorted(
            (item for document in documents for item in document.diagnostics),
            key=lambda item: (item.relative_path, item.location.start, item.diagnostic_id),
        )
    )
    revision = stable_sha256({
        "documents": [(item.relative_path, item.sha256, item.language) for item in documents],
        "symbols": [item.symbol_id for item in symbols],
        "references": [
            (item.reference_id, item.target_symbol_ids, item.resolution.value)
            for item in references
        ],
    })
    return SemanticProjectIndex(
        project_root=root.as_posix(),
        revision=revision,
        documents=tuple(documents),
        symbols=symbols,
        references=references,
        imports=imports,
        diagnostics=diagnostics,
        analyzed_files=len(documents),
        analyzed_bytes=total_bytes,
    )
