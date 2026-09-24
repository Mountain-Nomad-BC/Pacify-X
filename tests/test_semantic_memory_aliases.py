import math
import pytest

from runtime.semantic_integration_limits import SemanticIntegrationLimits
from runtime.semantic_memory_aliases import MemoryAliasRegistry


def test_aliases_are_exact_and_collision_safe():
    registry = MemoryAliasRegistry()
    registry.add("topic/old-name", "p", "m1")
    assert registry.resolve("topic/old-name").uri() == "pxmem://p/m1"
    assert registry.resolve("old-name") is None
    assert registry.candidates("topic/old-nam")[0].memory_id == "m1"
    with pytest.raises(ValueError):
        registry.add("topic/old-name", "p", "m2")


def test_alias_budget_is_enforced_without_rebinding_cost():
    registry = MemoryAliasRegistry(limits=SemanticIntegrationLimits(max_aliases=1))
    first = registry.add("a", "p", "m1")
    assert registry.add("a", "p", "m1") == first
    with pytest.raises(ValueError, match="budget"):
        registry.add("b", "p", "m2")


def test_fuzzy_controls_are_strictly_bounded():
    registry = MemoryAliasRegistry()
    registry.add("architecture/core", "p", "m1")
    for limit in (0, True):
        with pytest.raises(ValueError):
            registry.candidates("architecture/cor", limit=limit)  # type: ignore[arg-type]
    for threshold in (True, math.nan, -1.0, 2.0):
        with pytest.raises(ValueError):
            registry.candidates("architecture/cor", threshold=threshold)  # type: ignore[arg-type]


def test_alias_target_must_be_a_valid_memory_identity():
    registry = MemoryAliasRegistry()
    with pytest.raises(ValueError):
        registry.add("alias", "", "m1")
