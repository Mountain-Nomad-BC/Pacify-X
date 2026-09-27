"""Librarian answer composition: turn a governed route result into a grounded briefing.

The librarian is a *small* model operating over PX's deterministic system map. Its
apparent expertise does not come from its weights: it comes from a strict division of
labour (directive sections 4, 8, 16, 19, 20):

    deterministic layer (this module)
        - resolve the task into a canonical intent/capability envelope
        - rank real capabilities by exact/structural/semantic evidence
        - assemble a *minimum sufficient* context pack for the downstream model
        - attach source locations, confidence, and provenance to every claim

    small model (the 4B librarian)
        - phrases, disambiguates, and summarises the briefing
        - may request more evidence; may NOT invent entities, paths, or capabilities

This module is deliberately the improved successor to the older reference pattern:
it is deterministic-first, provenance-carrying, confidence-labelled, and it never
manufactures a capability, citation, or location that PX did not actually resolve.

Public entry points:
    compose_briefing(root, request, ...)   -> LibrarianBriefing
    build_context_pack(briefing, ...)      -> provider-ready messages + citation ledger
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .capability_routing import (
    RankedCandidate,
    RouteResult,
    route_task,
)
from .librarian_semantic_map import (
    resolve_entity,
)
from .registry import skill_discovery_sources

BRIEFING_SCHEMA = "px.librarian-briefing/1.0"
MAX_BRIEFING_ITEMS = 8
MAX_EXCERPT = 400
MAX_REQUEST = 4096

# A candidate is admitted only with *discriminating* evidence. The router's final score is
# dominated by structural completeness bonuses (graph proximity, freshness, contract
# coverage) that every canonical skill earns, and its lexical component carries a generic
# baseline (~4.6) from system-wide words such as "capability". Neither separates a real
# match from noise. Admission therefore requires a matched term that is specific to the
# request -- i.e. a reason attached to a query term rather than a system-wide concept.
MIN_ADMITTED_SCORE = 2.0
MIN_DISCRIMINATING_EVIDENCE = 0.5
_DISCRIMINATING_COMPONENTS = (
    "intent_similarity",
    "capability_match",
    "technology_match",
    "domain_match",
    "task_type_match",
    "alias_confidence",
    "output_compatibility",
    "project_context_match",
)
# Match reasons whose left-hand side is a term from the request rather than a universal
# system concept present on every capability record.
_GENERIC_MATCH_TOKENS = frozenset(
    {"capability", "capabilities", "skill", "skills", "px", "system", "tools", "tool"}
)


def _specific_match_terms(candidate: RankedCandidate, request: str) -> tuple[str, ...]:
    """Match reasons whose term actually occurs in the request and is not generic."""

    request_tokens = {
        token.strip(".,?!:;'").casefold()
        for token in request.replace("-", " ").split()
        if len(token) >= 3
    }
    found: list[str] = []
    for reason in getattr(candidate, "reasons", ()) or ():
        if "=" not in str(reason):
            continue
        _, _, right = str(reason).partition("=")
        for token in right.replace(",", " ").split():
            cleaned = token.strip().casefold()
            if cleaned in _GENERIC_MATCH_TOKENS or len(cleaned) < 3:
                continue
            if cleaned in request_tokens and cleaned not in found:
                found.append(cleaned)
    return tuple(found)


def _discriminating_evidence(candidate: RankedCandidate, request: str) -> float:
    """Sum of components that actually distinguish this candidate, plus specific terms."""

    scores = dict(getattr(candidate, "component_scores", {}) or {})
    total = 0.0
    for name in _DISCRIMINATING_COMPONENTS:
        value = scores.get(name, 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    total += len(_specific_match_terms(candidate, request)) * 1.0
    return total

# Confidence vocabulary. The librarian must never present inference as certainty.
CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_INFERRED = "inferred"
CONFIDENCE_UNSUPPORTED = "unsupported"

_UNSUPPORTED_MESSAGE = (
    "PX could not resolve this request to an admitted capability or indexed source. "
    "The correct answer is that it is unsupported here, not an invented one."
)


@dataclass(frozen=True, slots=True)
class BriefingItem:
    """One grounded capability the librarian may speak about."""

    capability_id: str
    kind: str
    score: float
    confidence: str
    source_paths: tuple[str, ...]
    matched_terms: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    lifecycle_state: str
    authority_class: str
    reason: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "score": round(self.score, 6),
            "confidence": self.confidence,
            "source_paths": list(self.source_paths),
            "matched_terms": list(self.matched_terms),
            "matched_capabilities": list(self.matched_capabilities),
            "lifecycle_state": self.lifecycle_state,
            "authority_class": self.authority_class,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LibrarianBriefing:
    """A deterministic, provenance-carrying briefing for the resident librarian lane."""

    schema_version: str
    request: str
    supported: bool
    intent: tuple[str, ...]
    domain: tuple[str, ...]
    execution_depth: str
    confidence_requirements: str
    items: tuple[BriefingItem, ...]
    semantic_hits: tuple[dict[str, object], ...]
    examined: int
    truncated: bool
    unsupported_reason: str | None
    route_sha256: str
    briefing_sha256: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request": self.request,
            "supported": self.supported,
            "intent": list(self.intent),
            "domain": list(self.domain),
            "execution_depth": self.execution_depth,
            "confidence_requirements": self.confidence_requirements,
            "items": [item.as_mapping() for item in self.items],
            "semantic_hits": list(self.semantic_hits),
            "examined": self.examined,
            "truncated": self.truncated,
            "unsupported_reason": self.unsupported_reason,
            "route_sha256": self.route_sha256,
            "briefing_sha256": self.briefing_sha256,
        }


def _confidence_for(score: float, matched: tuple[str, ...], authority: str) -> str:
    """Deterministic confidence label. Never upgrades weak evidence."""

    strong = len(matched)
    if score >= 6.0 and strong >= 3:
        return CONFIDENCE_VERIFIED
    if score >= 4.0 and strong >= 2:
        return CONFIDENCE_HIGH
    if score >= 2.0 and strong >= 1:
        return CONFIDENCE_MEDIUM
    if authority == "read_only" and strong == 0:
        return CONFIDENCE_INFERRED
    return CONFIDENCE_INFERRED


def _item_from_ranked(candidate: RankedCandidate, request: str = "") -> BriefingItem:
    reasons = tuple(str(r) for r in (getattr(candidate, "reasons", ()) or ()))
    scores = dict(getattr(candidate, "component_scores", {}) or {})
    paths = tuple(getattr(candidate, "source_paths", ()) or ())
    score = float(getattr(candidate, "final_score", 0.0) or 0.0)
    matched = _specific_match_terms(candidate, request) if request else ()
    confidence = (
        _confidence_for(score, matched, "read_only")
        if matched
        else CONFIDENCE_INFERRED
    )
    reason = (
        f"ranked by PX capability router (final_score={round(score, 3)}); "
        f"{len(paths)} source path(s); reasons={'; '.join(reasons[:3]) or 'none'}"
    )
    return BriefingItem(
        capability_id=str(candidate.canonical_id or candidate.candidate_id),
        kind=str(candidate.kind),
        score=score,
        confidence=confidence,
        source_paths=paths,
        matched_terms=matched,
        matched_capabilities=tuple(sorted(scores)) or (),
        lifecycle_state=str(getattr(candidate, "disposition", "unknown") or "unknown"),
        authority_class="read_only",
        reason=reason,
    )


def _cached_skill_index(root: Path):
    # Return the skill navigation index, computed once per source revision.
    #
    # Profiling one briefing showed the real duplicated cost is NOT the semantic map (about 20 ms),
    # but skill_navigation_index: it is computed twice per briefing (~197 ms of cumulative profile
    # time) and drives four skill_navigator.navigate calls (~248 ms). The index is a pure function
    # of the catalogue and an explicit revision, so recomputing it is duplicated work.
    #
    # The cache key is the catalogue mtime, so a stale index can never be served.

    from .registry import skill_navigation_index

    key_source = root / "registry" / "skill_catalog.toml"
    key = str(key_source.stat().st_mtime_ns) if key_source.is_file() else None
    cached = _SKILL_INDEX_CACHE.get("value")
    if cached is not None and key is not None and _SKILL_INDEX_CACHE.get("key") == key:
        return cached
    built = skill_navigation_index(root)
    _SKILL_INDEX_CACHE["value"] = built
    _SKILL_INDEX_CACHE["key"] = key
    return built


_SKILL_INDEX_CACHE: dict = {}


def compose_briefing(
    root: Path,
    request: str,
    *,
    max_items: int = MAX_BRIEFING_ITEMS,
) -> LibrarianBriefing:
    """Resolve a request into a grounded briefing, or an honest unsupported result."""

    if type(request) is not str or not request.strip() or len(request.encode("utf-8")) > MAX_REQUEST:
        raise ValueError("librarian request must be bounded nonempty text")
    if type(max_items) is not int or not 1 <= max_items <= MAX_BRIEFING_ITEMS:
        raise ValueError(f"max_items must be 1..{MAX_BRIEFING_ITEMS}")
    root = root.resolve(strict=True)

    result: RouteResult = route_task(
        request,
        skill_discovery_sources(root),
        constraints=(),
        max_risk="R4",
        canonical_records={item.capability_id: item for item in _cached_skill_index(root)},
    )
    envelope = result.envelope
    ranked: Iterable[RankedCandidate] = result.ranked

    # The capability router answers "which skill applies". The semantic map answers
    # "what is it, where is it, what owns it, what does it relate to" across the
    # registry/contracts/knowledge roots. A librarian briefing carries both.
    semantic_hits: tuple[dict[str, object], ...] = ()
    try:
        from .librarian_semantic_map import load_semantic_map

        semantic_map = load_semantic_map(root)
        semantic_hits = tuple(
            {
                "entity_id": match.entity.entity_id,
                "kind": match.entity.kind,
                "namespace": match.entity.namespace,
                "object_type": match.entity.object_type,
                "status": match.entity.status,
                "source_path": match.entity.source_path,
                "governing_contract": match.entity.contract,
                "score": round(match.score, 6),
                "matched_terms": list(match.matched_terms),
                "related": sorted({r.target for r in match.entity.relations})[:8],
            }
            for match in resolve_entity(semantic_map, request)[:max_items]
        )
    except (OSError, ValueError):
        # A missing/malformed semantic root degrades to router-only evidence, honestly.
        semantic_hits = ()

    items = tuple(
        _item_from_ranked(c, request)
        for c in list(ranked)
        if float(getattr(c, "final_score", 0.0) or 0.0) >= MIN_ADMITTED_SCORE
        and _discriminating_evidence(c, request) >= MIN_DISCRIMINATING_EVIDENCE
    )[:max_items]
    supported = bool(items)
    body = {
        "schema_version": BRIEFING_SCHEMA,
        "request": request,
        "supported": supported,
        "intent": list(envelope.intent),
        "domain": list(envelope.domain),
        "execution_depth": envelope.execution_depth,
        "confidence_requirements": envelope.confidence_requirements,
        "items": [item.as_mapping() for item in items],
        "semantic_hits": list(semantic_hits),
        "examined": int(len(list(getattr(result, "discovery", ()) or ())) or len(items)),
        "truncated": len(list(getattr(result, "ranked", ()) or ())) > len(items),
        "unsupported_reason": None if supported else _UNSUPPORTED_MESSAGE,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return LibrarianBriefing(
        schema_version=BRIEFING_SCHEMA,
        request=request,
        supported=supported,
        intent=tuple(envelope.intent),
        domain=tuple(envelope.domain),
        execution_depth=envelope.execution_depth,
        confidence_requirements=envelope.confidence_requirements,
        items=items,
        semantic_hits=semantic_hits,
        examined=body["examined"],
        truncated=body["truncated"],
        unsupported_reason=body["unsupported_reason"],
        route_sha256=str(getattr(result, "receipt_sha256", "") or ""),
        briefing_sha256=digest,
    )


def build_context_pack(
    briefing: LibrarianBriefing,
    *,
    user_question: str,
    max_chars: int = 12000,
) -> dict[str, object]:
    """Assemble the minimum-sufficient, provenance-carrying context for the librarian.

    The small model receives *only* resolved facts plus an explicit instruction to
    refuse invention. The citation ledger makes every statement traceable.
    """

    if type(user_question) is not str or not user_question.strip():
        raise ValueError("context pack requires the original user question")
    if type(max_chars) is not int or not 512 <= max_chars <= 120000:
        raise ValueError("max_chars must be a bounded integer")

    lines: list[str] = []
    ledger: list[dict[str, object]] = []
    for index, item in enumerate(briefing.items, start=1):
        marker = f"[{index}]"
        lines.append(
            f"{marker} {item.capability_id} ({item.kind}, confidence={item.confidence})"
        )
        if item.matched_terms:
            lines.append(f"    matched: {', '.join(item.matched_terms[:8])}")
        for path in item.source_paths[:4]:
            lines.append(f"    source: {path}")
        ledger.append(
            {
                "marker": marker,
                "capability_id": item.capability_id,
                "confidence": item.confidence,
                "source_paths": list(item.source_paths),
            }
        )

    # Semantic-map evidence: entity identity, location, owning contract, relations.
    offset = len(briefing.items)
    for index, hit in enumerate(briefing.semantic_hits, start=offset + 1):
        marker = f"[{index}]"
        lines.append(
            f"{marker} {hit['entity_id']} "
            f"(kind={hit['kind']}, namespace={hit['namespace']}, status={hit['status']})"
        )
        if hit.get("object_type"):
            lines.append(f"    type: {hit['object_type']}")
        lines.append(f"    source: {hit.get('source_path', '')}")
        if hit.get("governing_contract"):
            lines.append(f"    contract: {hit['governing_contract']}")
        related_raw = hit.get("related")
        related: list[str] = [str(r) for r in related_raw] if isinstance(related_raw, list) else []
        if related:
            lines.append(f"    related: {', '.join(related[:5])}")
        ledger.append(
            {
                "marker": marker,
                "entity_id": str(hit["entity_id"]),
                "confidence": "verified",
                "source_paths": [str(hit.get("source_path", ""))],
                "governing_contract": hit.get("governing_contract"),
            }
        )

    evidence = "\n".join(lines)[:max_chars]
    if not briefing.supported:
        evidence = briefing.unsupported_reason or _UNSUPPORTED_MESSAGE

    system = (
        "You are the Pacify-X librarian. You are an expert navigator of ONE system that "
        "has already been mapped for you. Rules you must never break:\n"
        "1. Only describe capabilities, paths, and components listed in the EVIDENCE block.\n"
        "2. Never invent a capability, file, symbol, or behaviour that is not in EVIDENCE.\n"
        "3. If the evidence does not answer the question, say exactly that and offer the "
        "closest supported capability.\n"
        "4. Cite each statement with its [n] marker.\n"
        "5. State confidence per claim using the labels given (verified/high/medium/inferred).\n"
        "6. You may propose an action, but you may not claim one was executed.\n"
        "Be concise, precise, and concrete."
    )
    return {
        "schema_version": "px.librarian-context-pack/1.0",
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"QUESTION:\n{user_question}\n\nEVIDENCE (authoritative, from PX):\n{evidence}"
                ),
            },
        ],
        "citation_ledger": ledger,
        "briefing_sha256": briefing.briefing_sha256,
        "supported": briefing.supported,
        "max_chars_applied": len(evidence),
    }
