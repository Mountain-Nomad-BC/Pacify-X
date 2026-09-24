"""Thread-safe backend registry with explicit collision handling."""

from __future__ import annotations

from pathlib import PurePosixPath
from threading import RLock

from .semantic_code_backend import SemanticBackend, validate_backend
from .semantic_code_python import PythonAstSemanticBackend


class BackendRegistrationError(ValueError):
    pass


class SemanticBackendRegistry:
    def __init__(self, *, include_builtins: bool = True):
        self._lock = RLock()
        self._by_key: dict[str, SemanticBackend] = {}
        self._by_suffix: dict[str, str] = {}
        self._by_language: dict[str, list[str]] = {}
        if include_builtins:
            self.register(PythonAstSemanticBackend())

    def register(self, backend: SemanticBackend, *, replace: bool = False) -> None:
        validate_backend(backend)
        key = backend.key.casefold()
        language = backend.language.casefold()
        with self._lock:
            if key in self._by_key and not replace:
                raise BackendRegistrationError(f"backend key already registered: {backend.key}")
            if replace and key in self._by_key:
                self.unregister(key)
            collisions = [
                suffix for suffix in backend.suffixes
                if suffix.casefold() in self._by_suffix
            ]
            if collisions and not replace:
                raise BackendRegistrationError(
                    "backend suffix already registered: " + ", ".join(sorted(collisions))
                )
            if replace:
                for suffix in collisions:
                    old_key = self._by_suffix.pop(suffix.casefold())
                    old = self._by_key.get(old_key)
                    if old is not None:
                        self._by_key.pop(old_key, None)
            self._by_key[key] = backend
            for suffix in backend.suffixes:
                self._by_suffix[suffix.casefold()] = key
            self._by_language.setdefault(language, []).append(key)
            self._by_language[language] = sorted(set(self._by_language[language]))

    def unregister(self, key: str) -> SemanticBackend | None:
        folded = key.casefold()
        with self._lock:
            backend = self._by_key.pop(folded, None)
            if backend is None:
                return None
            for suffix, owner in tuple(self._by_suffix.items()):
                if owner == folded:
                    self._by_suffix.pop(suffix, None)
            language = backend.language.casefold()
            owners = [item for item in self._by_language.get(language, []) if item != folded]
            if owners:
                self._by_language[language] = owners
            else:
                self._by_language.pop(language, None)
            return backend

    def for_path(self, relative_path: str) -> SemanticBackend | None:
        suffix = PurePosixPath(relative_path).suffix.casefold()
        with self._lock:
            key = self._by_suffix.get(suffix)
            return self._by_key.get(key) if key is not None else None

    def for_language(self, language: str) -> tuple[SemanticBackend, ...]:
        with self._lock:
            keys = self._by_language.get(language.casefold(), ())
            return tuple(self._by_key[key] for key in keys)

    def get(self, key: str) -> SemanticBackend | None:
        with self._lock:
            return self._by_key.get(key.casefold())

    def backends(self) -> tuple[SemanticBackend, ...]:
        with self._lock:
            return tuple(self._by_key[key] for key in sorted(self._by_key))

    def suffixes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._by_suffix))
