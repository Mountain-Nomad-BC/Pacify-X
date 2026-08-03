"""Deterministic navigation over compact capability metadata.

The navigator ranks registry summaries only. It does not import, load, or execute
the selected capability packages.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence

TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "use", "with"}


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS}


@dataclass(frozen=True)
class CapabilitySummary:
    capability_id: str
    purpose: str
    triggers: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    risk: str = "R1"
    status: str = "admitted"
    dependencies: tuple[str, ...] = ()
    capability_tags: tuple[str, ...] = ()
    freshness: float = 1.0
    cost: float = 0.0
    latency: float = 0.0
    redundancy_group: str | None = None
    kind: str = "skill"
    concepts: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavigationCandidate:
    capability_id: str
    score: float
    matched_terms: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    risk: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavigationResult:
    candidates: tuple[NavigationCandidate, ...]
    examined: int
    truncated: bool
    reason: str
    excluded: tuple[tuple[str, str], ...] = ()
    index_revision: str = ""


@dataclass(frozen=True)
class SelectionReason:
    capability_id: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WorkingSet:
    capability_ids: tuple[str, ...]
    decisions: tuple[SelectionReason, ...]
    rejected: tuple[tuple[str, str], ...]


RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}


def capability_index_revision(capability_index: Iterable[CapabilitySummary]) -> str:
    """Hash sorted metadata only; never load a skill body to compute a revision."""
    payload = [asdict(item) for item in sorted(capability_index, key=lambda value: value.capability_id)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _field_tokens(item: CapabilitySummary) -> dict[str, set[str]]:
    def combined(values: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for value in values:
            result.update(_tokens(value))
        return result
    return {
        "id": _tokens(item.capability_id.replace("-", " ")),
        "purpose": _tokens(item.purpose),
        "triggers": combined(item.triggers),
        "aliases": combined(item.aliases),
        "concepts": combined(item.concepts),
        "synonyms": combined(item.synonyms),
        "tags": combined(item.capability_tags),
        "relations": combined(item.relations),
    }


def navigate(
    goal: str,
    capability_index: Iterable[CapabilitySummary],
    available_inputs: Mapping[str, object] | None = None,
    *,
    max_candidates: int = 3,
    allowed_statuses: Sequence[str] = ("admitted", "active"),
    constraints: Mapping[str, object] | None = None,
    include_kinds: Sequence[str] = (),
) -> NavigationResult:
    if not goal.strip():
        raise ValueError("goal must not be empty")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")

    summaries = tuple(sorted(capability_index, key=lambda item: item.capability_id))
    supplied = set((available_inputs or {}).keys())
    policy = constraints or {}
    available_tools = {str(value) for value in policy.get("available_tools", ())} if isinstance(policy.get("available_tools", ()), (list, tuple, set)) else set()
    tools_declared = "available_tools" in policy
    max_risk = str(policy.get("max_risk", "R4"))
    if max_risk not in RISK_ORDER:
        raise ValueError("max_risk must be R0 through R4")
    kinds = {value.casefold() for value in include_kinds}
    goal_terms = _tokens(goal)
    ranked: list[NavigationCandidate] = []
    excluded: list[tuple[str, str]] = []
    eligible: list[CapabilitySummary] = []
    for summary in summaries:
        if summary.status not in allowed_statuses:
            excluded.append((summary.capability_id, f"lifecycle status {summary.status} is not selectable"))
            continue
        if kinds and summary.kind.casefold() not in kinds:
            excluded.append((summary.capability_id, f"kind {summary.kind} is not requested"))
            continue
        if RISK_ORDER.get(summary.risk, RISK_ORDER["R4"]) > RISK_ORDER[max_risk]:
            excluded.append((summary.capability_id, f"risk {summary.risk} exceeds {max_risk}"))
            continue
        missing_tools = sorted(set(summary.tools) - available_tools) if tools_declared else []
        if missing_tools:
            excluded.append((summary.capability_id, "missing tools: " + ", ".join(missing_tools)))
            continue
        eligible.append(summary)

    fields = {item.capability_id: _field_tokens(item) for item in eligible}
    document_frequency: Counter[str] = Counter()
    for item_fields in fields.values():
        for term in set().union(*item_fields.values()):
            document_frequency[term] += 1
    weights = {"id": 4.0, "aliases": 4.0, "triggers": 3.0, "synonyms": 3.0, "concepts": 2.5, "purpose": 2.0, "tags": 2.0, "relations": 1.0}
    total = max(len(eligible), 1)
    normalized_goal = " ".join(sorted(goal_terms))
    goal_phrase = " ".join(TOKEN.findall(goal.casefold()))
    for summary in eligible:
        item_fields = fields[summary.capability_id]
        matched = goal_terms & set().union(*item_fields.values())
        if not matched:
            continue
        score = 0.0
        reasons: list[str] = []
        for field, field_terms in item_fields.items():
            field_matches = sorted(goal_terms & field_terms)
            if not field_matches:
                continue
            contribution = sum(weights[field] * math.log(1.0 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)) for term in field_matches)
            score += contribution
            reasons.append(f"{field}={','.join(field_matches)}")
        searchable = " ".join((summary.capability_id.replace("-", " "), summary.purpose, *summary.triggers, *summary.aliases, *summary.synonyms)).casefold()
        exact_phrases = {" ".join(TOKEN.findall(value.casefold())) for value in (*summary.aliases, *summary.synonyms)}
        if goal_phrase in exact_phrases:
            score += 100.0
            reasons.append("exact governed alias")
        if normalized_goal and normalized_goal in " ".join(sorted(_tokens(searchable))):
            score += 1.0
            reasons.append("normalized phrase coverage")
        missing = tuple(sorted(set(summary.required_inputs) - supplied))
        ranked.append(NavigationCandidate(summary.capability_id, round(score, 6), tuple(sorted(matched)), missing, summary.risk, tuple(reasons)))

    ranked.sort(key=lambda item: (-item.score, len(item.missing_inputs), item.capability_id))
    selected = tuple(ranked[:max_candidates])
    return NavigationResult(
        candidates=selected,
        examined=len(summaries),
        truncated=len(ranked) > max_candidates,
        reason="bounded weighted metadata and policy match" if selected else "no admitted capability matched",
        excluded=tuple(sorted(excluded)),
        index_revision=capability_index_revision(summaries),
    )


def select_working_set(
    goal: str,
    capability_index: Iterable[CapabilitySummary],
    *,
    default_limit: int = 3,
    hard_limit: int = 8,
    dependency_depth: int = 3,
) -> WorkingSet:
    """Rank a minimal metadata-only working set and include bounded dependencies."""
    if default_limit < 1 or hard_limit < default_limit or dependency_depth < 0:
        raise ValueError("invalid selection budget")
    records = {item.capability_id: item for item in capability_index if item.status in {"admitted", "active"}}
    navigation = navigate(goal, records.values(), max_candidates=hard_limit)
    chosen: list[str] = []
    decisions: list[SelectionReason] = []
    rejected: list[tuple[str, str]] = []
    groups: set[str] = set()

    def add(capability_id: str, depth: int, reason: str) -> bool:
        if capability_id in chosen:
            return True
        item = records.get(capability_id)
        if item is None:
            rejected.append((capability_id, "dependency is unavailable")); return False
        if depth > dependency_depth:
            rejected.append((capability_id, "dependency depth exceeds budget")); return False
        if item.redundancy_group and item.redundancy_group in groups:
            rejected.append((capability_id, "redundant capability group")); return False
        chosen_before = len(chosen)
        decisions_before = len(decisions)
        groups_before = set(groups)
        rejected_before = len(rejected)
        for dependency in sorted(item.dependencies):
            if not add(dependency, depth + 1, f"required by {capability_id}"):
                del chosen[chosen_before:]
                del decisions[decisions_before:]
                groups.clear(); groups.update(groups_before)
                del rejected[rejected_before:]
                rejected.append((capability_id, f"dependency bundle does not fit: {dependency}"))
                return False
        if len(chosen) >= min(default_limit, hard_limit):
            del chosen[chosen_before:]
            del decisions[decisions_before:]
            groups.clear(); groups.update(groups_before)
            del rejected[rejected_before:]
            rejected.append((capability_id, "dependency bundle exceeds active skill budget")); return False
        safety = {"R0": 1.0, "R1": 0.8, "R2": 0.4, "R3": 0.0}.get(item.risk, 0.0)
        fit = next((candidate.score for candidate in navigation.candidates if candidate.capability_id == capability_id), 0)
        score = round(10 * fit + 3 * item.freshness + 2 * safety - item.cost - item.latency, 3)
        chosen.append(capability_id)
        if item.redundancy_group:
            groups.add(item.redundancy_group)
        decisions.append(SelectionReason(capability_id, score, (reason, f"fit={fit}", f"risk={item.risk}", f"freshness={item.freshness}")))
        return True

    ranked = sorted(
        navigation.candidates,
        key=lambda candidate: (
            -(10 * candidate.score + 3 * records[candidate.capability_id].freshness + 2 * ({"R0": 1, "R1": .8, "R2": .4}.get(candidate.risk, 0)) - records[candidate.capability_id].cost - records[candidate.capability_id].latency),
            candidate.capability_id,
        ),
    )
    for candidate in ranked:
        add(candidate.capability_id, 0, "matched task metadata")
    return WorkingSet(tuple(chosen), tuple(decisions), tuple(sorted(set(rejected))))
