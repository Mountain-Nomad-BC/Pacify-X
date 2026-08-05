"""Policy-grounded retrieval over caller-supplied metadata indexes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


TOKEN = re.compile(r"[a-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class RetrievalSource:
    source_id: str
    title: str
    text: str
    visibility: tuple[str, ...]
    lineage: str
    kind: str = "document"
    links: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    source_id: str
    title: str
    excerpt: str
    citation: str
    lineage: str
    score: int


@dataclass(frozen=True, slots=True)
class RetrievalDecision:
    strategy: str
    mode: str
    hits: tuple[RetrievalHit, ...]
    filtered_source_ids: tuple[str, ...]
    context_bytes: int
    trace: tuple[str, ...]


def integration_healthcheck() -> dict[str, object]:
    """Exercise the adapter boundary without external I/O or persisted state."""
    source = RetrievalSource(
        "health", "Health", "bounded retrieval health", ("public",), "self-test"
    )
    decision = retrieve("retrieval health", (source,), identity_scope=())
    return {
        "valid": len(decision.hits) == 1,
        "mode": decision.mode,
        "effects": ["read_local"],
    }


def _terms(value: str) -> set[str]:
    return set(TOKEN.findall(value.casefold()))


def retrieve(
    query: str,
    sources: Iterable[RetrievalSource],
    *,
    identity_scope: Iterable[str],
    client_claimed_role: str | None = None,
    max_results: int = 5,
    max_context_bytes: int = 16384,
) -> RetrievalDecision:
    if not query.strip() or max_results < 1 or max_context_bytes < 1:
        raise ValueError("query and positive retrieval budgets are required")
    scope = set(identity_scope)
    query_terms = _terms(query)
    strategy = (
        "graph"
        if query_terms & {"dependency", "relationship", "graph", "linked"}
        else (
            "manifest"
            if query_terms & {"manifest", "registry", "capability"}
            else "hybrid_keyword"
        )
    )
    visible: list[RetrievalSource] = []
    filtered: list[str] = []
    for source in sources:
        allowed = (
            not source.visibility
            or "public" in source.visibility
            or bool(scope & set(source.visibility))
        )
        if allowed:
            visible.append(source)
        else:
            filtered.append(source.source_id)
    ranked: list[tuple[int, RetrievalSource]] = []
    for source in visible:
        haystack = _terms(source.title + " " + source.text)
        score = 3 * len(query_terms & _terms(source.title)) + len(
            query_terms & haystack
        )
        if strategy == "graph" and source.links:
            score += 2
        if strategy == "manifest" and source.kind in {"manifest", "registry"}:
            score += 2
        if score:
            ranked.append((score, source))
    ranked.sort(key=lambda item: (-item[0], item[1].source_id))
    hits: list[RetrievalHit] = []
    used = 0
    for score, source in ranked:
        excerpt = " ".join(source.text.split())[:1000]
        size = len(excerpt.encode("utf-8"))
        if used + size > max_context_bytes:
            continue
        hits.append(
            RetrievalHit(
                source.source_id,
                source.title,
                excerpt,
                f"source:{source.source_id}",
                source.lineage,
                score,
            )
        )
        used += size
        if len(hits) >= max_results:
            break
    trace = (
        f"strategy={strategy}",
        f"identity_scope_count={len(scope)}",
        f"visible={len(visible)}",
        f"filtered={len(filtered)}",
        "client_role_authoritative=false",
        f"context_budget={max_context_bytes}",
    )
    mode = "read_only" if hits else "degraded_no_match"
    return RetrievalDecision(
        strategy, mode, tuple(hits), tuple(sorted(filtered)), used, trace
    )
