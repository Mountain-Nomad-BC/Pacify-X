"""Policy-grounded hybrid retrieval over caller-supplied metadata indexes.

This module is the single canonical retrieval/fusion owner. Adapters may
produce candidate signals, but they do not own ranking, generation admission,
or authority decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from typing import Iterable, Mapping

TOKEN = re.compile(r"[a-z0-9_-]+")
RETRIEVAL_OWNER = "runtime.retrieval.retrieve"
RETRIEVAL_OWNER_REVISION = "2.2.0"
SIGNAL_REVISIONS = {
    "lexical": "token-jaccard-v1",
    "dense_vector": "generation-bound-caller-score-v2",
    "metadata": "metadata-token-jaccard-v1",
    "structured": "structured-token-jaccard-v1",
    "graph": "caller-or-link-score-v1",
    "freshness": "caller-score-v1",
    "trust": "caller-score-v1",
    "rerank": "bounded-subordinate-score-v1",
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
    retrieval_generation_id: str | None = None


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
    retrieval_generation_id: str | None = None
    exact_identifier: bool = False


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
    retrieval_generation_id: str | None = None
    query_plan_sha256: str | None = None


def integration_healthcheck() -> dict[str, object]:
    source = RetrievalSource("health", "Health", "bounded retrieval health", ("public",), "self-test")
    decision = retrieve("retrieval health", (source,), identity_scope=())
    return {"valid": len(decision.hits) == 1, "mode": decision.mode, "effects": ["read_local"]}


def _terms(value: str) -> set[str]:
    return set(TOKEN.findall(value.casefold()))


def _bounded_score(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or type(value) is bool:
        raise ValueError(f"{name} must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return score


def _overlap(query_terms: set[str], value: object) -> float:
    terms = _terms(json.dumps(value, sort_keys=True, default=str))
    union = query_terms | terms
    return len(query_terms & terms) / len(union) if union else 0.0


def _score_source(query_terms: set[str], source: RetrievalSource) -> tuple[float, dict[str, float], dict[str, str]]:
    haystack = _terms(source.title + " " + source.text)
    union = query_terms | haystack
    lexical = len(query_terms & haystack) / len(union) if union else 0.0
    raw: dict[str, float | None] = {
        "lexical": lexical,
        "dense_vector": _bounded_score("dense_score", source.dense_score),
        "metadata": _overlap(query_terms, source.metadata) if source.metadata else None,
        "structured": _overlap(query_terms, source.structured) if source.structured else None,
        "graph": _bounded_score("graph_score", source.graph_score),
        "freshness": _bounded_score("freshness", source.freshness),
        "trust": _bounded_score("trust", source.trust),
    }
    if raw["graph"] is None and source.links:
        raw["graph"] = _overlap(query_terms, source.links)
    status = {name: ("available" if value is not None else "unavailable") for name, value in raw.items()}
    components = {
        name: round(float(value) * SIGNAL_WEIGHTS[name], 8)
        for name, value in raw.items() if value is not None
    }
    return round(sum(components.values()), 8), components, status


def _clip_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = value.encode("utf-8")[:max_bytes]
    while raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ""


def _generation_contract(sources: Iterable[RetrievalSource], requested: str | None) -> str | None:
    dense_generations = {s.retrieval_generation_id for s in sources if s.dense_score is not None and s.retrieval_generation_id is not None}
    if len(dense_generations) > 1:
        raise ValueError("dense retrieval evidence from multiple generations cannot be fused")
    if requested is not None:
        if type(requested) is not str or len(requested) != 64 or any(c not in "0123456789abcdef" for c in requested):
            raise ValueError("retrieval_generation_id must be a lowercase SHA-256")
        for source in sources:
            if source.dense_score is not None and source.retrieval_generation_id != requested:
                raise ValueError("dense evidence does not match the requested retrieval generation")
        return requested
    return next(iter(dense_generations), None)


def retrieve(
    query: str,
    sources: Iterable[RetrievalSource],
    *,
    identity_scope: Iterable[str],
    client_claimed_role: str | None = None,
    max_results: int = 5,
    max_context_bytes: int = 16384,
    retrieval_generation_id: str | None = None,
    exact_source_ids: Iterable[str] = (),
    rerank_scores: Mapping[str, float] | None = None,
    rerank_weight: float = 0.15,
    query_plan: object | None = None,
) -> RetrievalDecision:
    if type(query) is not str or not query.strip() or type(max_results) is not int or max_results < 1 or type(max_context_bytes) is not int or max_context_bytes < 1:
        raise ValueError("query and positive integer retrieval budgets are required")
    source_rows = tuple(sources)
    if any(type(source) is not RetrievalSource for source in source_rows):
        raise ValueError("sources must contain RetrievalSource records")
    effective_generation_id = _generation_contract(source_rows, retrieval_generation_id)
    if type(rerank_weight) not in (int,float) or type(rerank_weight) is bool or not math.isfinite(float(rerank_weight)) or not 0 <= float(rerank_weight) <= 1:
        raise ValueError("rerank_weight must be finite in [0,1]")
    exact = set(exact_source_ids)
    query_plan_sha256: str | None = None
    effective_query = query
    if query_plan is not None:
        from .query_planner import QueryPlan
        if type(query_plan) is not QueryPlan:
            raise ValueError("query_plan must be a typed QueryPlan")
        if query_plan.authority_granted:
            raise ValueError("query plans may not grant authority")
        query_plan_sha256 = query_plan.plan_sha256
        exact.update(query_plan.exact_identifiers)
        effective_query = " ".join((query_plan.normalized_query, *query_plan.expansions)).strip() or query
    if any(type(value) is not str or not value or len(value.encode()) > 1024 for value in exact):
        raise ValueError("exact source IDs must be bounded nonempty text")
    rerank = dict(rerank_scores or {})
    if len(rerank) > 1000:
        raise ValueError("rerank score set is over budget")
    for key, value in rerank.items():
        if type(key) is not str or not key or _bounded_score("rerank score", value) is None:
            raise ValueError("rerank score mapping is invalid")

    scope = set(identity_scope)
    query_terms = _terms(effective_query)
    strategy = "graph" if query_terms & {"dependency", "relationship", "graph", "linked"} else ("manifest" if query_terms & {"manifest", "registry", "capability"} else "hybrid_keyword")
    visible: list[RetrievalSource] = []
    filtered: list[str] = []
    for source in source_rows:
        allowed = not source.visibility or "public" in source.visibility or bool(scope & set(source.visibility))
        (visible if allowed else filtered).append(source if allowed else source.source_id)
    visible_ids={s.source_id for s in visible}
    unknown_rerank=set(rerank)-visible_ids
    if unknown_rerank:
        raise ValueError("rerank scores may only reference visible retrieval sources")

    ranked: list[tuple[int, float, RetrievalSource, dict[str, float], dict[str, str]]] = []
    aggregate = {name: "unavailable" for name in SIGNAL_WEIGHTS}
    if rerank:
        aggregate["rerank"] = "available"
    for source in visible:
        score, components, status = _score_source(query_terms, source)
        for name, value in status.items():
            if value == "available": aggregate[name] = "available"
        if source.source_id in rerank:
            rr=float(rerank[source.source_id])
            score=round(score*(1-float(rerank_weight))+rr*float(rerank_weight),8)
            components={**components,"rerank":round(rr*float(rerank_weight),8)}
            status={**status,"rerank":"available"}
        exact_priority=0 if source.source_id in exact else 1
        if score > 0 or exact_priority == 0:
            ranked.append((exact_priority, score, source, components, status))
    ranked.sort(key=lambda item: (item[0], -item[1], item[2].source_id))

    hits: list[RetrievalHit] = []
    used = 0
    for exact_priority, score, source, components, status in ranked:
        remaining=max_context_bytes-used
        if remaining <= 0 and exact_priority != 0:
            continue
        normalized=" ".join(source.text.split())[:1000]
        if exact_priority == 0:
            excerpt=_clip_utf8(normalized, max(0,remaining))
        else:
            size=len(normalized.encode("utf-8"))
            if size > remaining:
                continue
            excerpt=normalized
        size=len(excerpt.encode("utf-8"))
        hits.append(RetrievalHit(source.source_id, source.title, excerpt, f"source:{source.source_id}", source.lineage, score, components, status, SIGNAL_REVISIONS, source.source_revision, source.retrieval_generation_id, exact_priority == 0))
        used += size
        if len(hits) >= max_results:
            break
    trace = (
        f"strategy={strategy}", f"canonical_owner={RETRIEVAL_OWNER}", f"owner_revision={RETRIEVAL_OWNER_REVISION}",
        f"identity_scope_count={len(scope)}", f"visible={len(visible)}", f"filtered={len(filtered)}",
        "client_role_authoritative=false", f"context_budget={max_context_bytes}",
        f"retrieval_generation={effective_generation_id or 'legacy-unbound'}",
        f"query_plan={query_plan_sha256 or 'legacy-unplanned'}",
        *(f"signal.{name}={aggregate[name]}" for name in sorted(aggregate)),
    )
    mode = "read_only" if hits else "degraded_no_match"
    return RetrievalDecision(strategy, mode, tuple(hits), tuple(sorted(filtered)), used, trace, signal_availability=aggregate, retrieval_generation_id=effective_generation_id, query_plan_sha256=query_plan_sha256)
