"""Policy-grounded hybrid retrieval over caller-supplied metadata indexes.

This module is the single canonical retrieval owner.  Adapters may translate
their corpus into :class:`RetrievalSource` records, but must not implement a
second ranking engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Iterable, Mapping


TOKEN = re.compile(r"[a-z0-9_-]+")
RETRIEVAL_OWNER = "runtime.retrieval.retrieve"
RETRIEVAL_OWNER_REVISION = "2.0.0"
SIGNAL_REVISIONS = {
    "lexical": "token-jaccard-v1",
    "dense_vector": "caller-score-v1",
    "metadata": "metadata-token-jaccard-v1",
    "structured": "structured-token-jaccard-v1",
    "graph": "caller-or-link-score-v1",
    "freshness": "caller-score-v1",
    "trust": "caller-score-v1",
}
SIGNAL_WEIGHTS = {
    "lexical": 0.30,
    "dense_vector": 0.20,
    "metadata": 0.10,
    "structured": 0.10,
    "graph": 0.10,
    "freshness": 0.10,
    "trust": 0.10,
}


@dataclass(frozen=True, slots=True)
class RetrievalSource:
    source_id: str
    title: str
    text: str
    visibility: tuple[str, ...]
    lineage: str
    kind: str = "document"
    links: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    structured: Mapping[str, object] = field(default_factory=dict)
    dense_score: float | None = None
    graph_score: float | None = None
    freshness: float | None = None
    trust: float | None = None
    source_revision: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    source_id: str
    title: str
    excerpt: str
    citation: str
    lineage: str
    score: float
    component_scores: Mapping[str, float] = field(default_factory=dict)
    signal_status: Mapping[str, str] = field(default_factory=dict)
    signal_revisions: Mapping[str, str] = field(default_factory=dict)
    source_revision: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalDecision:
    strategy: str
    mode: str
    hits: tuple[RetrievalHit, ...]
    filtered_source_ids: tuple[str, ...]
    context_bytes: int
    trace: tuple[str, ...]
    canonical_owner: str = RETRIEVAL_OWNER
    owner_revision: str = RETRIEVAL_OWNER_REVISION
    signal_availability: Mapping[str, str] = field(default_factory=dict)


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


def _bounded_score(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return score


def _overlap(query_terms: set[str], value: object) -> float:
    terms = _terms(json.dumps(value, sort_keys=True, default=str))
    union = query_terms | terms
    return len(query_terms & terms) / len(union) if union else 0.0


def _score_source(
    query_terms: set[str], source: RetrievalSource
) -> tuple[float, dict[str, float], dict[str, str]]:
    haystack = _terms(source.title + " " + source.text)
    union = query_terms | haystack
    lexical = len(query_terms & haystack) / len(union) if union else 0.0
    raw: dict[str, float | None] = {
        "lexical": lexical,
        "dense_vector": _bounded_score("dense_score", source.dense_score),
        "metadata": _overlap(query_terms, source.metadata) if source.metadata else None,
        "structured": _overlap(query_terms, source.structured)
        if source.structured
        else None,
        "graph": _bounded_score("graph_score", source.graph_score),
        "freshness": _bounded_score("freshness", source.freshness),
        "trust": _bounded_score("trust", source.trust),
    }
    if raw["graph"] is None and source.links:
        raw["graph"] = _overlap(query_terms, source.links)
    status = {
        name: ("available" if value is not None else "unavailable")
        for name, value in raw.items()
    }
    components = {
        name: round(float(value) * SIGNAL_WEIGHTS[name], 8)
        for name, value in raw.items()
        if value is not None
    }
    return round(sum(components.values()), 8), components, status


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
    ranked: list[
        tuple[float, RetrievalSource, dict[str, float], dict[str, str]]
    ] = []
    aggregate = {name: "unavailable" for name in SIGNAL_WEIGHTS}
    for source in visible:
        score, components, status = _score_source(query_terms, source)
        for name, value in status.items():
            if value == "available":
                aggregate[name] = "available"
        if score > 0:
            ranked.append((score, source, components, status))
    ranked.sort(key=lambda item: (-item[0], item[1].source_id))
    hits: list[RetrievalHit] = []
    used = 0
    for score, source, components, status in ranked:
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
                components,
                status,
                SIGNAL_REVISIONS,
                source.source_revision,
            )
        )
        used += size
        if len(hits) >= max_results:
            break
    trace = (
        f"strategy={strategy}",
        f"canonical_owner={RETRIEVAL_OWNER}",
        f"owner_revision={RETRIEVAL_OWNER_REVISION}",
        f"identity_scope_count={len(scope)}",
        f"visible={len(visible)}",
        f"filtered={len(filtered)}",
        "client_role_authoritative=false",
        f"context_budget={max_context_bytes}",
        *(f"signal.{name}={aggregate[name]}" for name in sorted(aggregate)),
    )
    mode = "read_only" if hits else "degraded_no_match"
    return RetrievalDecision(
        strategy,
        mode,
        tuple(hits),
        tuple(sorted(filtered)),
        used,
        trace,
        signal_availability=aggregate,
    )
