from __future__ import annotations

from runtime.semantic_code_cache import SemanticDocumentCache
from runtime.semantic_code_types import SemanticDocument


def _doc(name: str, size: int) -> SemanticDocument:
    return SemanticDocument(name, "python", name * 64, size)


def test_cache_is_lru_and_bounded():
    cache = SemanticDocumentCache(max_items=2, max_bytes=20)
    one = _doc("a.py", 8)
    two = _doc("b.py", 8)
    three = _doc("c.py", 8)
    cache.put(one, "python-ast")
    cache.put(two, "python-ast")
    assert cache.get("a.py", one.sha256, "python-ast") is one
    cache.put(three, "python-ast")
    assert cache.get("b.py", two.sha256, "python-ast") is None
    assert cache.stats().evictions == 1
