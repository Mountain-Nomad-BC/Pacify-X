"""Bounded LRU cache for immutable semantic document analyses."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

from .semantic_code_types import SemanticDocument


@dataclass(frozen=True, slots=True)
class CacheStats:
    items: int
    bytes: int
    hits: int
    misses: int
    evictions: int


class SemanticDocumentCache:
    def __init__(self, *, max_items: int = 512, max_bytes: int = 64 * 1024 * 1024):
        if type(max_items) is not int or max_items < 1:
            raise ValueError("max_items must be a positive integer")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, str, str], SemanticDocument] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._lock = RLock()

    def get(self, relative_path: str, sha256: str, backend_key: str) -> SemanticDocument | None:
        key = (relative_path, sha256, backend_key)
        with self._lock:
            value = self._items.get(key)
            if value is None:
                self._misses += 1
                return None
            self._items.move_to_end(key)
            self._hits += 1
            return value

    def put(self, document: SemanticDocument, backend_key: str) -> None:
        key = (document.relative_path, document.sha256, backend_key)
        size = max(1, document.size_bytes)
        if size > self.max_bytes:
            return
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._bytes -= max(1, previous.size_bytes)
            self._items[key] = document
            self._bytes += size
            self._items.move_to_end(key)
            while len(self._items) > self.max_items or self._bytes > self.max_bytes:
                _, removed = self._items.popitem(last=False)
                self._bytes -= max(1, removed.size_bytes)
                self._evictions += 1

    def invalidate_path(self, relative_path: str) -> int:
        with self._lock:
            keys = [key for key in self._items if key[0] == relative_path]
            for key in keys:
                removed = self._items.pop(key)
                self._bytes -= max(1, removed.size_bytes)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                items=len(self._items),
                bytes=self._bytes,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )
