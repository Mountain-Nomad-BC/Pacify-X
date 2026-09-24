"""Exact legacy-memory aliases for safe migration to durable ``pxmem://`` identities."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import math

from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_memory_refs import MemoryReference

_ALIAS_MAX_BYTES = 4096


def _alias_text(value: str) -> str:
    if type(value) is not str:
        raise TypeError("memory alias must be text")
    normalized = value.strip()
    if not normalized or len(normalized.encode("utf-8")) > _ALIAS_MAX_BYTES:
        raise ValueError("memory alias must be bounded nonempty text")
    return normalized


@dataclass(frozen=True, slots=True)
class MemoryAlias:
    alias: str
    project_id: str
    memory_id: str

    def __post_init__(self) -> None:
        normalized = _alias_text(self.alias)
        if normalized != self.alias:
            raise ValueError("MemoryAlias.alias must already be stripped")
        # Reuse canonical memory-reference validation for target identities.
        MemoryReference(self.project_id, self.memory_id)


class MemoryAliasRegistry:
    """In-memory exact alias table.

    Exact lookup is the only operation that returns a target identity.  Fuzzy matching
    produces suggestions for an operator/reviewer; it can never authorize a rewrite.
    """

    def __init__(
        self, *, limits: SemanticIntegrationLimits = SemanticIntegrationLimits()
    ) -> None:
        self.limits = limits
        self._aliases: dict[str, MemoryAlias] = {}

    def add(self, alias: str, project_id: str, memory_id: str) -> MemoryAlias:
        normalized = _alias_text(alias)
        item = MemoryAlias(normalized, project_id, memory_id)
        existing = self._aliases.get(normalized)
        if existing is not None and existing != item:
            raise ValueError("memory alias is already bound to another identity")
        if existing is None and len(self._aliases) >= self.limits.max_aliases:
            raise ValueError("memory alias budget exceeded")
        self._aliases[normalized] = item
        return item

    def resolve(self, alias: str) -> MemoryReference | None:
        normalized = _alias_text(alias)
        item = self._aliases.get(normalized)
        return None if item is None else MemoryReference(item.project_id, item.memory_id)

    def candidates(
        self,
        alias: str,
        *,
        limit: int = 5,
        threshold: float = 0.65,
    ) -> tuple[MemoryAlias, ...]:
        normalized = _alias_text(alias)
        if type(limit) is not int or not 1 <= limit <= self.limits.max_aliases:
            raise ValueError("candidate limit must be a positive bounded integer")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("candidate threshold must be numeric")
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value) or not 0.0 <= threshold_value <= 1.0:
            raise ValueError("candidate threshold must be finite and between 0 and 1")

        scored: list[tuple[float, str, MemoryAlias]] = []
        folded = normalized.casefold()
        for item in self._aliases.values():
            score = SequenceMatcher(
                None, folded, item.alias.casefold(), autojunk=False
            ).ratio()
            if score >= threshold_value:
                scored.append((score, item.alias, item))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item for _, _, item in scored[:limit])
