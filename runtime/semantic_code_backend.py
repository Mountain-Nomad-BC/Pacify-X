"""Backend contract for semantic source analysis.

Wave 1 ships a deterministic Python AST backend.  Wave 2 can add LSP-backed
implementations without changing callers or semantic evidence models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import PurePosixPath
from typing import Iterable

from .semantic_code_document import DocumentSnapshot
from .semantic_code_types import SemanticDocument


class SemanticBackend(ABC):
    key: str
    language: str
    suffixes: tuple[str, ...]

    @abstractmethod
    def analyze(self, snapshot: DocumentSnapshot) -> SemanticDocument:
        raise NotImplementedError

    def supports_path(self, relative_path: str) -> bool:
        suffix = PurePosixPath(relative_path).suffix.lower()
        return suffix in self.suffixes

    def supports_language(self, language: str) -> bool:
        return language.casefold() == self.language.casefold()


class NullSemanticBackend(SemanticBackend):
    key = "null"
    language = "unknown"
    suffixes: tuple[str, ...] = ()

    def analyze(self, snapshot: DocumentSnapshot) -> SemanticDocument:
        return SemanticDocument(
            relative_path=snapshot.relative_path,
            language=self.language,
            sha256=snapshot.raw_sha256,
            size_bytes=snapshot.size_bytes,
        )


def validate_backend(backend: SemanticBackend) -> None:
    if not isinstance(backend.key, str) or not backend.key.strip():
        raise ValueError("semantic backend key must be non-empty")
    if not isinstance(backend.language, str) or not backend.language.strip():
        raise ValueError("semantic backend language must be non-empty")
    if not isinstance(backend.suffixes, tuple):
        raise ValueError("semantic backend suffixes must be a tuple")
    seen: set[str] = set()
    for suffix in backend.suffixes:
        if not isinstance(suffix, str) or not suffix.startswith("."):
            raise ValueError("semantic backend suffixes must start with '.'")
        folded = suffix.casefold()
        if folded in seen:
            raise ValueError(f"duplicate backend suffix: {suffix}")
        seen.add(folded)


def backend_suffixes(backends: Iterable[SemanticBackend]) -> tuple[str, ...]:
    return tuple(sorted({suffix.casefold() for b in backends for suffix in b.suffixes}))
