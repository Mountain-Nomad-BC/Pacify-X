"""Collision-checked registry for known language-server adapters."""
from __future__ import annotations

from pathlib import PurePosixPath
from threading import RLock
from typing import Mapping

from .semantic_lsp_adapters import Adapter, BUILTIN_ADAPTERS


class LspAdapterRegistry:
    def __init__(self, *, include_builtins: bool = True):
        self._lock = RLock()
        self._by_key: dict[str, Adapter] = {}
        self._by_suffix: dict[str, str] = {}
        if include_builtins:
            for adapter in BUILTIN_ADAPTERS:
                self.register(adapter)

    def register(self, adapter: Adapter, *, replace: bool = False) -> None:
        key = adapter.key.casefold()
        if not key or not adapter.suffixes:
            raise ValueError("adapter key and suffixes are required")
        with self._lock:
            if key in self._by_key and not replace:
                raise ValueError(f"adapter already registered: {adapter.key}")
            collisions = [s for s in adapter.suffixes if s.casefold() in self._by_suffix and self._by_suffix[s.casefold()] != key]
            if collisions and not replace:
                raise ValueError("adapter suffix collision: " + ", ".join(sorted(collisions)))
            if replace and key in self._by_key:
                self.unregister(key)
            self._by_key[key] = adapter
            for suffix in adapter.suffixes:
                self._by_suffix[suffix.casefold()] = key

    def unregister(self, key: str) -> Adapter | None:
        folded = key.casefold()
        with self._lock:
            item = self._by_key.pop(folded, None)
            if item is not None:
                for suffix, owner in tuple(self._by_suffix.items()):
                    if owner == folded:
                        self._by_suffix.pop(suffix, None)
            return item

    def get(self, key: str) -> Adapter | None:
        with self._lock:
            return self._by_key.get(key.casefold())

    def for_path(self, relative_path: str) -> Adapter | None:
        suffix = PurePosixPath(relative_path).suffix.casefold()
        with self._lock:
            key = self._by_suffix.get(suffix)
            return self._by_key.get(key) if key else None

    def adapters(self) -> tuple[Adapter, ...]:
        with self._lock:
            return tuple(self._by_key[key] for key in sorted(self._by_key))

    def discovery(self, *, environment: Mapping[str, str] | None = None) -> dict[str, tuple[tuple[str, ...], ...]]:
        return {adapter.key: adapter.discover_argv(environment=environment) for adapter in self.adapters()}
