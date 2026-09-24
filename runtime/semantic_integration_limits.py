"""Bounded resource limits for PACIFY-X semantic integration Wave 3."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SemanticIntegrationLimits:
    max_projects: int = 32
    max_modes: int = 8
    max_operations: int = 128
    max_query_bytes: int = 64 * 1024
    max_results: int = 50
    max_context_bytes: int = 64 * 1024
    max_sources: int = 512
    max_evidence_items: int = 256
    max_memory_references: int = 2048
    max_relocations: int = 512
    max_aliases: int = 2048
    max_receipt_bytes: int = 256 * 1024
    max_concurrent_project_queries: int = 8

    def __post_init__(self) -> None:
        fields = self.__dataclass_fields__
        for name in fields:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_results > self.max_sources:
            raise ValueError("max_results cannot exceed max_sources")
