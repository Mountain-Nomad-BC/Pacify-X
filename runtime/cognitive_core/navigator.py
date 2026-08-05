"""Fast deterministic hierarchical retrieval over the unified cognitive map.

Search is metadata-only.  The navigator returns a bounded hydration plan so the caller
loads only the selected leaf, its owner contract/body, and explicit dependencies.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from .common import char_ngrams, jaccard, normalize_text, token_set

_SELECTABLE = frozenset(
    {"active", "admitted", "formula", "reference", "reference_only", "executable"}
)


@dataclass(frozen=True, slots=True)
class CognitiveHit:
    key: str
    identifier: str
    kind: str
    owner: str
    status: str
    selectable: bool
    score: float
    path: str
    implementation_path: str
    reasons: tuple[str, ...]
    dependencies: tuple[str, ...]
    formula_refs: tuple[str, ...]
    related: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CognitiveSearchResult:
    query: str
    hits: tuple[CognitiveHit, ...]
    examined: int
    index_revision: str
    degraded: bool
    trace: tuple[str, ...]


class CognitiveNavigator:
    FIELD_WEIGHTS = {
        "id": 9.0,
        "title": 7.0,
        "aliases": 8.0,
        "triggers": 6.0,
        "summary": 3.5,
        "concepts": 3.2,
        "domain": 2.5,
        "inputs": 2.0,
        "outputs": 2.0,
        "dependencies": 1.5,
        "formula_refs": 2.8,
        "relations": 1.0,
    }
    KIND_SIGNALS = {
        "formula": {
            "formula",
            "equation",
            "calculate",
            "units",
            "dimension",
            "sensitivity",
            "uncertainty",
        },
        "workflow": {
            "workflow",
            "orchestrate",
            "sequence",
            "pipeline",
            "process",
            "steps",
        },
        "script": {"script", "implementation", "execute", "tool", "runner"},
        "capability": {
            "reason",
            "logic",
            "diagnose",
            "analyze",
            "infer",
            "cognition",
            "planner",
        },
        "knowledge": {"knowledge", "source", "reference", "document", "evidence"},
        "skill": {"skill", "domain", "pack", "ability"},
    }

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.revision = str(payload.get("revision", ""))
        self.records = tuple(
            item for item in payload.get("records", ()) if isinstance(item, Mapping)
        )
        self.by_key = {str(item["key"]): item for item in self.records}
        self.by_id: dict[str, list[str]] = defaultdict(list)
        self.outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for record in self.records:
            self.by_id[str(record["id"])].append(str(record["key"]))
        for edge in payload.get("edges", ()):
            source, target, relation = (
                str(edge["source"]),
                str(edge["target"]),
                str(edge["relation"]),
            )
            self.outgoing[source].append((relation, target))
            self.incoming[target].append((relation, source))
        self._fields: dict[str, dict[str, set[str]]] = {}
        self._ngrams: dict[str, set[str]] = {}
        self._normalized_aliases: dict[str, set[str]] = defaultdict(set)
        document_frequency: Counter[str] = Counter()
        for record in self.records:
            key = str(record["key"])
            fields = {
                "id": token_set(str(record.get("id", "")).replace("-", " ")),
                "title": token_set(str(record.get("title", ""))),
                "aliases": self._combined_tokens(record.get("aliases", ())),
                "triggers": self._combined_tokens(record.get("triggers", ())),
                "summary": token_set(str(record.get("summary", ""))),
                "concepts": self._combined_tokens(record.get("concepts", ())),
                "domain": token_set(str(record.get("domain", ""))),
                "inputs": self._combined_tokens(record.get("inputs", ())),
                "outputs": self._combined_tokens(record.get("outputs", ())),
                "dependencies": self._combined_tokens(record.get("dependencies", ())),
                "formula_refs": self._combined_tokens(record.get("formula_refs", ())),
                "relations": self._combined_tokens(record.get("relations", ())),
            }
            self._fields[key] = fields
            document_frequency.update(set().union(*fields.values()))
            identity_text = " ".join(
                (
                    str(record.get("id", "")),
                    str(record.get("title", "")),
                    *map(str, record.get("aliases", ())),
                )
            )
            self._ngrams[key] = char_ngrams(identity_text)
            for value in (
                record.get("id", ""),
                record.get("title", ""),
                *record.get("aliases", ()),
            ):
                normalized = normalize_text(str(value))
                if normalized:
                    self._normalized_aliases[normalized].add(key)
        self._df = document_frequency

    @staticmethod
    def _combined_tokens(values: object) -> set[str]:
        if isinstance(values, Mapping):
            values = (*values.keys(), *values.values())
        if isinstance(values, str):
            values = (values,)
        result: set[str] = set()
        for value in values or ():
            result.update(token_set(str(value)))
        return result

    def _graph_context(self, key: str, depth: int = 1) -> tuple[str, ...]:
        if depth < 1:
            return ()
        related: set[str] = set()
        frontier = {key}
        seen = {key}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for current in frontier:
                for relation, target in self.outgoing.get(current, ()):
                    related.add(f"{relation}->{target}")
                    if target in self.by_key and target not in seen:
                        seen.add(target)
                        next_frontier.add(target)
                for relation, source in self.incoming.get(current, ()):
                    related.add(f"{relation}<-{source}")
                    if source in self.by_key and source not in seen:
                        seen.add(source)
                        next_frontier.add(source)
            frontier = next_frontier
        return tuple(sorted(related))

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        kinds: Sequence[str] = (),
        statuses: Sequence[str] = (),
        selectable_only: bool = False,
        graph_depth: int = 1,
        dense_ranked_keys: Sequence[str] = (),
    ) -> CognitiveSearchResult:
        if not query.strip() or limit < 1:
            raise ValueError("query and positive limit are required")
        query_terms = token_set(query)
        query_normalized = normalize_text(query)
        query_ngrams = char_ngrams(query)
        allowed_kinds = {str(value) for value in kinds}
        allowed_statuses = {str(value) for value in statuses}
        kind_preferences = {
            kind for kind, signals in self.KIND_SIGNALS.items() if query_terms & signals
        }
        total = max(1, len(self.records))
        exact_keys = self._normalized_aliases.get(query_normalized, set())
        dense_ranks = {str(key): rank for rank, key in enumerate(dense_ranked_keys, 1)}
        scored: list[tuple[float, str, str, Mapping[str, Any], list[str]]] = []
        for record in self.records:
            key = str(record["key"])
            kind = str(record.get("kind"))
            status = str(record.get("status"))
            selectable = status in _SELECTABLE
            if allowed_kinds and kind not in allowed_kinds:
                continue
            if allowed_statuses and status not in allowed_statuses:
                continue
            if selectable_only and not selectable:
                continue
            fields = self._fields[key]
            score = 0.0
            reasons: list[str] = []
            if key in exact_keys:
                score += 500.0
                reasons.append("exact governed id/title/alias")
            matched_union: set[str] = set()
            for field, terms in fields.items():
                matched = sorted(query_terms & terms)
                if not matched:
                    continue
                matched_union.update(matched)
                contribution = sum(
                    self.FIELD_WEIGHTS[field]
                    * math.log(
                        1.0 + (total - self._df[term] + 0.5) / (self._df[term] + 0.5)
                    )
                    for term in matched
                )
                score += contribution
                reasons.append(f"{field}={','.join(matched)}")
            if query_terms:
                coverage = len(matched_union) / len(query_terms)
                score += 10.0 * coverage * coverage
                if coverage >= 0.75:
                    reasons.append(f"query-coverage={coverage:.3f}")
            fuzzy = jaccard(query_ngrams, self._ngrams[key])
            if fuzzy >= 0.30:
                score += 14.0 * fuzzy
                reasons.append(f"identity-fuzzy={fuzzy:.3f}")
            if kind in kind_preferences:
                score += 5.0
                reasons.append("query-kind fit")
            if selectable:
                score += 0.25
            else:
                score -= 2.0
                reasons.append(f"non-selectable-status={status}")
            if key in dense_ranks:
                score += 60.0 / (60 + dense_ranks[key])
                reasons.append(f"dense-rank={dense_ranks[key]}")
            if score <= 0:
                continue
            scored.append((score, str(record.get("id")), key, record, reasons))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        hits = []
        for score, _, key, record, reasons in scored[:limit]:
            status = str(record.get("status", ""))
            hits.append(
                CognitiveHit(
                    key=key,
                    identifier=str(record["id"]),
                    kind=str(record["kind"]),
                    owner=str(record.get("owner", "")),
                    status=status,
                    selectable=status in _SELECTABLE,
                    score=round(score, 6),
                    path=str(record.get("path", "")),
                    implementation_path=str(record.get("implementation_path", "")),
                    reasons=tuple(reasons),
                    dependencies=tuple(record.get("dependencies", ())),
                    formula_refs=tuple(record.get("formula_refs", ())),
                    related=self._graph_context(key, graph_depth),
                )
            )
        trace = (
            f"records={len(self.records)}",
            f"exact_matches={len(exact_keys)}",
            f"kind_preferences={','.join(sorted(kind_preferences)) or 'none'}",
            f"graph_depth={graph_depth}",
            f"dense_candidates={len(dense_ranks)}",
            f"selectable_only={selectable_only}",
        )
        return CognitiveSearchResult(
            query, tuple(hits), len(self.records), self.revision, not bool(hits), trace
        )

    def hydration_plan(
        self, keys: Sequence[str], *, dependency_depth: int = 2, max_records: int = 16
    ) -> dict[str, Any]:
        """Return deterministic paths to load after ranking, without reading those files."""
        if dependency_depth < 0 or max_records < 1:
            raise ValueError("invalid hydration budget")
        queue = deque((str(key), 0, "selected") for key in keys)
        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        unresolved: set[str] = set()
        while queue and len(records) < max_records:
            key, depth, reason = queue.popleft()
            if key in seen:
                continue
            seen.add(key)
            record = self.by_key.get(key)
            if record is None:
                unresolved.add(key)
                continue
            records.append(
                {
                    "key": key,
                    "id": record.get("id"),
                    "kind": record.get("kind"),
                    "status": record.get("status"),
                    "selectable": str(record.get("status")) in _SELECTABLE,
                    "path": record.get("path", ""),
                    "implementation_path": record.get("implementation_path", ""),
                    "reason": reason,
                }
            )
            if depth >= dependency_depth:
                continue
            for relation, target in sorted(self.outgoing.get(key, ())):
                if target.startswith("unresolved:"):
                    unresolved.add(target)
                elif (
                    relation == "owned_by"
                    or relation == "depends_on"
                    or relation == "uses_formula"
                    or relation.startswith("step:")
                ):
                    queue.append((target, depth + 1, relation))
        return {
            "valid": True,
            "index_revision": self.revision,
            "records": records,
            "unresolved": sorted(unresolved),
            "truncated": bool(queue),
            "rule": "load metadata globally; hydrate only these selected records and declared dependencies",
        }
