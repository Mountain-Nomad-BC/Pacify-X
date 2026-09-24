"""Hard acquisition and response budgets for semantic code operations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from time import monotonic


@dataclass(frozen=True, slots=True)
class SemanticCodeLimits:
    max_files: int = 5_000
    max_total_bytes: int = 64 * 1024 * 1024
    max_file_bytes: int = 2 * 1024 * 1024
    max_symbols: int = 100_000
    max_references: int = 500_000
    max_results: int = 200
    max_graph_nodes: int = 2_000
    max_graph_edges: int = 10_000
    max_query_chars: int = 1_024
    max_duration_seconds: float = 30.0

    def __post_init__(self) -> None:
        integer_fields = (
            "max_files", "max_total_bytes", "max_file_bytes", "max_symbols",
            "max_references", "max_results", "max_graph_nodes", "max_graph_edges",
            "max_query_chars",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        duration = self.max_duration_seconds
        if type(duration) not in (int, float) or not math.isfinite(duration):
            raise ValueError("max_duration_seconds must be finite numeric data")
        if duration <= 0 or duration > 300:
            raise ValueError("max_duration_seconds must be > 0 and <= 300")
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("max_file_bytes cannot exceed max_total_bytes")


class BudgetExceeded(RuntimeError):
    def __init__(self, code: str, *, limit: int | float, observed: int | float):
        self.code = code
        self.limit = limit
        self.observed = observed
        super().__init__(f"{code}: observed={observed} limit={limit}")


class Deadline:
    def __init__(self, seconds: float):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("deadline seconds must be positive and finite")
        self._started = monotonic()
        self._seconds = float(seconds)

    @property
    def elapsed(self) -> float:
        return monotonic() - self._started

    def check(self) -> None:
        elapsed = self.elapsed
        if elapsed >= self._seconds:
            raise BudgetExceeded(
                "semantic_code_deadline_exceeded",
                limit=self._seconds,
                observed=elapsed,
            )


def enforce_count(code: str, observed: int, limit: int) -> None:
    if observed > limit:
        raise BudgetExceeded(code, limit=limit, observed=observed)
