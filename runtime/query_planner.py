"""Canonical retrieval-query planning hints with exact-identifier protection.

The planner emits deterministic hints only.  ``runtime.retrieval`` remains the
canonical ranking/fusion owner and authorization remains outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

_MAX_QUERY_BYTES = 16384
_MAX_ENTRIES = 4096
_MAX_ALIASES = 128
_ID_VALUE = r"[A-Za-z0-9_.:/-]{1,512}"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_text(value: object, label: str, maximum: int = 2048) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    text = value.strip()
    if len(text.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds byte budget")
    return text


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    canonical: str
    aliases: tuple[str, ...] = ()
    category: str = "terminology"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_text(self.canonical, "canonical")
        _bounded_text(self.category, "category", 128)
        if type(self.aliases) is not tuple or len(self.aliases) > _MAX_ALIASES:
            raise ValueError("aliases must be a bounded tuple")
        if any(type(item) is not str or not item.strip() or len(item.encode("utf-8")) > 512 for item in self.aliases):
            raise ValueError("aliases must contain bounded nonempty text")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("lexicon aliases must be unique")
        _canonical(dict(self.metadata))


@dataclass(frozen=True, slots=True)
class QueryPlan:
    raw_query: str
    normalized_query: str
    exact_identifiers: tuple[str, ...]
    exact_keys: tuple[str, ...]
    aliases_resolved: tuple[tuple[str, str], ...]
    expansions: tuple[str, ...]
    facets: Mapping[str, tuple[str, ...]]
    direct_blockers: tuple[str, ...]
    plan_sha256: str
    authority_granted: bool = False

    @property
    def plan_hash(self) -> str:  # compatibility with source material terminology
        return self.plan_sha256


class QueryPlanner:
    """Produces canonical query hints only; it never scores or retrieves data."""

    EXACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("record_id", re.compile(rf"\b(?:record|record_id|json_id)\s*[:=]\s*({_ID_VALUE})", re.I)),
        ("document_id", re.compile(rf"\b(?:doc|doc_id|document|document_id)\s*[:=]\s*({_ID_VALUE})", re.I)),
        ("source_id", re.compile(rf"\b(?:source|source_id)\s*[:=]\s*({_ID_VALUE})", re.I)),
        ("capability_id", re.compile(rf"\b(?:capability|capability_id)\s*[:=]\s*({_ID_VALUE})", re.I)),
        ("action_id", re.compile(rf"\b(?:action|action_id)\s*[:=]\s*({_ID_VALUE})", re.I)),
        ("sha256", re.compile(r"\b([a-fA-F0-9]{64})\b")),
    )

    def __init__(self, entries: Iterable[LexiconEntry] = ()) -> None:
        rows = tuple(entries)
        if len(rows) > _MAX_ENTRIES or any(type(row) is not LexiconEntry for row in rows):
            raise ValueError("lexicon exceeds budget or contains invalid entries")
        aliases: dict[str, LexiconEntry] = {}
        for entry in rows:
            for alias in (entry.canonical, *entry.aliases):
                key = self._norm(alias)
                owner = aliases.get(key)
                if owner is not None and owner.canonical != entry.canonical:
                    raise ValueError(f"ambiguous query alias {alias!r}: {owner.canonical} vs {entry.canonical}")
                aliases[key] = entry
        self._aliases = aliases
        self.lexicon_sha256 = _sha([
            {
                "canonical": row.canonical,
                "aliases": list(row.aliases),
                "category": row.category,
                "metadata": dict(row.metadata),
            }
            for row in sorted(rows, key=lambda item: (item.category, item.canonical))
        ])

    @staticmethod
    def _norm(value: str) -> str:
        if type(value) is not str:
            raise ValueError("query text must be text")
        lowered = value.casefold().strip()
        lowered = re.sub(r"[^a-z0-9_.:+/#-]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered)

    def plan(self, query: str) -> QueryPlan:
        if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > _MAX_QUERY_BYTES:
            raise ValueError("query must be bounded nonempty text")
        normalized = self._norm(query)
        exact_values: set[str] = set()
        exact_keys: set[str] = set()
        facets: dict[str, set[str]] = {}
        for facet, pattern in self.EXACT_PATTERNS:
            for match in pattern.findall(query):
                raw = str(match)
                value = raw.casefold() if facet == "sha256" else raw
                exact_values.add(value)
                exact_keys.add(f"{facet}:{value}")
                facets.setdefault(facet, set()).add(value)

        aliases_resolved: set[tuple[str, str]] = set()
        expansions: set[str] = set()
        for alias, entry in self._aliases.items():
            if re.search(rf"(?<![a-z0-9_.:-]){re.escape(alias)}(?![a-z0-9_.:-])", normalized):
                aliases_resolved.add((alias, entry.canonical))
                expansions.add(entry.canonical)
                expansions.update(entry.aliases)
                facets.setdefault(entry.category, set()).add(entry.canonical)

        blocker_rules = {
            "requires_citations": ("cite", "citation", "source", "evidence", "prove"),
            "deep_analysis": ("root cause", "deep dive", "compare all", "analyze deeply"),
            "currentness_sensitive": ("latest", "current", "today", "recent", "newest"),
        }
        blockers = sorted(
            label for label, phrases in blocker_rules.items()
            if any(phrase in normalized for phrase in phrases)
        )
        payload = {
            "normalized_query": normalized,
            "exact_identifiers": sorted(exact_values),
            "exact_keys": sorted(exact_keys),
            "aliases_resolved": [list(item) for item in sorted(aliases_resolved)],
            "expansions": sorted(expansions),
            "facets": {key: sorted(values) for key, values in sorted(facets.items())},
            "direct_blockers": blockers,
            "lexicon_sha256": self.lexicon_sha256,
        }
        return QueryPlan(
            raw_query=query,
            normalized_query=normalized,
            exact_identifiers=tuple(payload["exact_identifiers"]),
            exact_keys=tuple(payload["exact_keys"]),
            aliases_resolved=tuple(tuple(item) for item in payload["aliases_resolved"]),
            expansions=tuple(payload["expansions"]),
            facets={key: tuple(values) for key, values in payload["facets"].items()},
            direct_blockers=tuple(blockers),
            plan_sha256=_sha(payload),
            authority_granted=False,
        )

    @staticmethod
    def retrieval_metadata(plan: QueryPlan) -> dict[str, Any]:
        if type(plan) is not QueryPlan:
            raise ValueError("typed QueryPlan required")
        return {
            "query_plan_sha256": plan.plan_sha256,
            "exact_identifiers": list(plan.exact_identifiers),
            "exact_keys": list(plan.exact_keys),
            "aliases_resolved": [list(item) for item in plan.aliases_resolved],
            "query_expansions": list(plan.expansions),
            "facets": {key: list(values) for key, values in plan.facets.items()},
            "direct_blockers": list(plan.direct_blockers),
            "authority_granted": False,
        }
