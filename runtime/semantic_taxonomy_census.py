"""Hierarchical classification and the SEM-003 census report.

Builds ``Subject -> Object -> Semantic -> Kind`` recursively, compares a global
Object registry against a namespace-local one, and reports capacity, ambiguity,
buckets and stability. Freezes nothing and allocates nothing.

Object is a CATEGORY inside a Subject, never an individual entity. An earlier
pass treated symbol head-nouns as Objects and produced 1,089 terms, which
merely recreated a directory tree numerically. Here Objects are derived from the
distinctive shared vocabulary of each Subject's entities, so a Subject yields a
small set of categories such as state, identity, ledger, execution, validation
rather than one Object per symbol.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from runtime.semantic_surfaces import collect_corpus_snapshot
from runtime.semantic_taxonomy import (
    AMBIGUOUS,
    KIND_VOCABULARY,
    NOVEL_TERM,
    OUTCOMES,
    RESOLVED,
    SUBJECT_CANDIDATES,
    TAXONOMY_SCHEMA,
    UNRESOLVED,
    SurfaceEntity,
    canonical_term,
    tokenize,
)

SEGMENT_CAPACITY = 254

# Stopwords are ordinary English filler, not PX taxonomy. Removing them stops
# clusters forming around "the system returns a value".
_STOPWORDS = frozenset(
    """the a an and or of to in for from with without is are be been being this that these those
    it its as at by on if then else not no nor so such own same other another any all each every
    which who whom whose what when where why how return returns returned value values data item
    items result results object objects def function method class self none true false null void
    str int bool dict list set tuple type name names path paths key keys value""".split()
)


def _content_tokens(entity: SurfaceEntity) -> list[str]:
    tokens = [token for token in entity.tokens if token not in _STOPWORDS and len(token) > 2]
    doc_tokens = [token for token in tokenize(entity.doc) if token not in _STOPWORDS and len(token) > 2]
    return tokens + doc_tokens


def classify_subject(entity: SurfaceEntity) -> tuple[str, float, dict[str, int]]:
    """Score every Subject candidate against multi-channel evidence.

    Path is one channel among several and can never be decisive alone: semantic
    identity must survive artifact relocation.
    """
    scores: dict[str, int] = defaultdict(int)
    name_tokens = set(tokenize(entity.name))
    doc_tokens = set(tokenize(entity.doc))
    path_tokens = set(tokenize(entity.source_path.replace("/", " ").replace(".", " ")))
    all_tokens = set(_content_tokens(entity))

    for subject, needles in SUBJECT_CANDIDATES.items():
        for needle in needles:
            needle_token = tokenize(needle)
            if not needle_token:
                continue
            primary = needle_token[0]
            if primary in name_tokens:
                scores[subject] += 5
            if primary in doc_tokens:
                scores[subject] += 3
            if primary in path_tokens:
                scores[subject] += 2
            if any(needle_token[0] in token for token in all_tokens):
                scores[subject] += 1
    if not scores:
        return UNRESOLVED, 0.0, {}
    total = sum(scores.values())
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    confidence = top_score / total
    margin = (top_score - ranked[1][1]) / total if len(ranked) > 1 else 1.0
    if top_score < 3:
        return UNRESOLVED, round(confidence, 3), dict(ranked[:3])
    if margin < 0.15:
        return AMBIGUOUS, round(confidence, 3), dict(ranked[:3])
    return top, round(confidence, 3), dict(ranked[:3])


def classify_semantic(entity: SurfaceEntity) -> tuple[str, float, str | None]:
    """Canonical PX functional term, or NOVEL_TERM when nothing maps."""
    best: str | None = None
    best_raw = ""
    best_score = 0
    for token in _content_tokens(entity):
        canonical, mapped = canonical_term(token)
        if not mapped:
            continue
        # Head-of-name tokens weigh more than docstring filler.
        weight = 3 if token in set(entity.tokens) else 1
        score = weight if canonical not in {best} else 0
        if score > best_score:
            best, best_raw, best_score = canonical, token, score
    if best is None:
        return NOVEL_TERM, 0.0, None
    confidence = min(1.0, best_score / 3.0)
    return best, round(confidence, 3), best_raw


def derive_objects(entities: list[SurfaceEntity], *, max_objects: int = 40) -> dict[str, dict[str, Any]]:
    """Discover Object CATEGORIES within a Subject from shared vocabulary.

    Each category is the set of entities sharing a distinctive head noun. This
    produces concepts like state, identity, ledger or execution rather than one
    Object per symbol.
    """
    if not entities:
        return {}
    document_frequency: Counter[str] = Counter()
    for entity in entities:
        head = next(
            (token for token in reversed(entity.tokens) if token not in _STOPWORDS and len(token) > 2),
            None,
        )
        if head:
            canonical, _ = canonical_term(head)
            document_frequency[canonical] += 1
    ranked = document_frequency.most_common(max_objects)
    buckets: dict[str, list[SurfaceEntity]] = defaultdict(list)
    for entity in entities:
        head = next(
            (token for token in reversed(entity.tokens) if token not in _STOPWORDS and len(token) > 2),
            None,
        )
        key = canonical_term(head)[0] if head else "general"
        buckets[key].append(entity)
    out: dict[str, dict[str, Any]] = {}
    total = len(entities)
    for term, count in ranked:
        canonical, _ = canonical_term(term)
        out[canonical] = {
            "count": count,
            "share": round(count / total, 4),
            "representatives": [e.name for e in buckets[canonical][:6]],
        }
    if "general" in buckets:
        out["general"] = {
            "count": len(buckets["general"]),
            "share": round(len(buckets["general"]) / total, 4),
            "representatives": [e.name for e in buckets["general"][:6]],
        }
    return out


def run_full_census(root: Path, *, per_surface_limit: int | None = None) -> dict[str, Any]:
    source_snapshot = collect_corpus_snapshot(root, per_surface_limit=per_surface_limit)
    source_report = source_snapshot.report()
    entities = list(source_snapshot.entities)

    assignments: list[dict[str, Any]] = []
    subject_scores: dict[str, int] = Counter()
    for entity in entities:
        subject, subject_confidence, rivals = classify_subject(entity)
        semantic, semantic_confidence, raw_semantic = classify_semantic(entity)
        if subject == RESOLVED:
            subject_scores[subject] += 1
        outcome = RESOLVED
        if subject in {UNRESOLVED}:
            outcome = UNRESOLVED
        elif subject == AMBIGUOUS:
            outcome = AMBIGUOUS
        elif semantic == NOVEL_TERM:
            outcome = NOVEL_TERM
        assignments.append(
            {
                "key": entity.key,
                "surface": entity.surface,
                "kind": entity.kind,
                "name": entity.name,
                "source_path": entity.source_path,
                "subject": subject,
                "subject_confidence": subject_confidence,
                "subject_rivals": rivals,
                "semantic": semantic,
                "semantic_confidence": semantic_confidence,
                "semantic_raw": raw_semantic,
                "outcome": outcome,
                "channels": entity.channels(),
            }
        )

    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in assignments:
        by_subject[record["subject"]].append(record)

    hierarchy: dict[str, Any] = {}
    for subject, rows in sorted(by_subject.items(), key=lambda kv: -len(kv[1])):
        surface_entities = [e for e in entities if e.key in {r["key"] for r in rows}]
        objects = derive_objects(surface_entities)
        hierarchy[subject] = {
            "entity_count": len(rows),
            "object_count": len(objects),
            "objects": objects,
            "semantics": Counter(
                r["semantic"] for r in rows if r["semantic"] != NOVEL_TERM
            ).most_common(40),
        }

    # --- capacity, both models ---
    global_object_terms = sorted({t for s in hierarchy.values() for t in s["objects"]})
    live_subjects = sorted(
        s for s in hierarchy
        if s not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}
    )
    objects_per_subject = {s: hierarchy[s]["object_count"] for s in live_subjects}
    semantics_per_pair = {
        f"{s}/{o}": len(set(r["semantic"] for r in rows if r["semantic"] != NOVEL_TERM))
        for s, rows in by_subject.items()
        for o in [None]  # placeholder replaced below
    }
    # Real nested semantic cardinality, computed per (subject, object).
    pair_semantics: dict[str, set[str]] = defaultdict(set)
    surface_by_key = {e.key: e for e in entities}
    for record in assignments:
        if record["semantic"] == NOVEL_TERM:
            continue
        entity = surface_by_key.get(record["key"])
        head = None
        if entity is not None:
            head = next(
                (t for t in reversed(entity.tokens) if t not in _STOPWORDS and len(t) > 2), None
            )
        obj = canonical_term(head)[0] if head else "general"
        pair_semantics[f"{record['subject']}/{obj}"].add(record["semantic"])

    observed_kinds = sorted({e.kind for e in entities})
    kind_counts = Counter(e.kind for e in entities)
    canonical_kinds = sorted({canonical_term(k)[0] for k in observed_kinds})
    kind_map: dict[str, str] = {}
    for kind in observed_kinds:
        canonical_map, _ = canonical_term(kind)
        kind_map[kind] = canonical_map

    outcome_counts = Counter(r["outcome"] for r in assignments)
    total = len(assignments) or 1

    def percentile(values: list[int], fraction: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        return ordered[index]

    obj_counts = list(objects_per_subject.values())
    sem_counts = list(pair_semantics.values())
    sem_counts = [len(value) for value in sem_counts]

    buckets: dict[str, int] = Counter(
        f"{r['subject']}/{r['semantic']}/{canonical_map_kind(r, kind_map)}/{kind_map.get(r['kind'], r['kind'])}"
        for r in assignments
    )
    bucket_sizes = sorted(buckets.values())
    singleton = sum(1 for size in bucket_sizes if size == 1)

    capacity = {
        "model_A_global_registry": {
            "subjects": len(live_subjects),
            "objects_global": len(global_object_terms),
            "semantics_global": len({r["semantic"] for r in assignments if r["semantic"] != NOVEL_TERM}),
            "kinds": len(canonical_kinds),
            "objects_fit_one_segment": len(global_object_terms) <= SEGMENT_CAPACITY,
            "objects_utilization": round(len(global_object_terms) / SEGMENT_CAPACITY, 3),
            "verdict": "OVERFLOW" if len(global_object_terms) > SEGMENT_CAPACITY else "fits",
        },
        "model_B_namespace_local": {
            "subjects": len(live_subjects),
            "max_objects_within_subject": max(obj_counts) if obj_counts else 0,
            "median_objects_per_subject": percentile(obj_counts, 0.5),
            "max_semantics_within_subject_object": max(sem_counts) if sem_counts else 0,
            "median_semantics_per_object": percentile(sem_counts, 0.5),
            "kinds": len(canonical_kinds),
            "subjects_fit": len(live_subjects) <= SEGMENT_CAPACITY,
            "objects_fit_per_subject": (max(obj_counts) if obj_counts else 0) <= SEGMENT_CAPACITY,
            "semantics_fit_per_object": (max(sem_counts) if sem_counts else 0) <= SEGMENT_CAPACITY,
            "kinds_fit": len(canonical_kinds) <= SEGMENT_CAPACITY,
        },
    }
    capacity["model_B_namespace_local"]["verdict"] = (
        "fits"
        if all([
            capacity["model_B_namespace_local"]["subjects_fit"],
            capacity["model_B_namespace_local"]["objects_fit_per_subject"],
            capacity["model_B_namespace_local"]["semantics_fit_per_object"],
            capacity["model_B_namespace_local"]["kinds_fit"],
        ])
        else "OVERFLOW"
    )

    return {
        "schema_version": TAXONOMY_SCHEMA,
        "source_census": source_report,
        "source_binding_sha256": source_report["source_binding_sha256"],
        "frozen": False,
        "addresses_allocated": False,
        "legend_frozen": False,
        "corpus": {
            "entities": len(entities),
            "by_surface": dict(Counter(e.surface for e in entities)),
            "by_kind": dict(kind_counts),
            "sources": len({e.source_path for e in entities}),
        },
        "outcomes": {name: outcome_counts.get(name, 0) for name in OUTCOMES},
        "outcome_percentages": {
            name: round(100 * outcome_counts.get(name, 0) / total, 2) for name in OUTCOMES
        },
        "vocabularies": {
            "subjects_live": live_subjects,
            "subjects_unresolved": sorted(
                s for s in hierarchy if s in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}
            ),
            "objects_global": global_object_terms,
            "semantics_global": sorted(
                {r["semantic"] for r in assignments if r["semantic"] != NOVEL_TERM}
            ),
            "kinds_observed": observed_kinds,
            "kinds_canonical": canonical_kinds,
            "kind_map": kind_map,
        },
        "capacity": capacity,
        "buckets": {
            "bucket_count": len(buckets),
            "max_population": bucket_sizes[-1] if bucket_sizes else 0,
            "median_population": percentile(bucket_sizes, 0.5),
            "singleton_buckets": singleton,
            "singleton_percentage": round(100 * singleton / (len(buckets) or 1), 2),
            "largest": [
                {"bucket": key, "population": count}
                for key, count in buckets.most_common(15)
            ],
        },
        "hierarchy": {
            subject: {
                "entity_count": data["entity_count"],
                "object_count": data["object_count"],
                "objects": list(data["objects"])[:12],
                "top_semantics": [term for term, _ in data["semantics"][:10]],
            }
            for subject, data in hierarchy.items()
        },
        "normalization_ledger": _normalization_ledger(assignments),
        "uncertainty": {
            "ambiguous": [r["key"] for r in assignments if r["outcome"] == AMBIGUOUS][:40],
            "unresolved": [r["key"] for r in assignments if r["outcome"] == UNRESOLVED][:40],
            "novel_term": [r["key"] for r in assignments if r["outcome"] == NOVEL_TERM][:40],
            "low_confidence": [
                {"key": r["key"], "confidence": r["subject_confidence"]}
                for r in assignments
                if r["outcome"] == RESOLVED and r["subject_confidence"] < 0.55
            ][:40],
        },
    }


def canonical_map_kind(record: dict[str, Any], kind_map: dict[str, str]) -> str:
    return kind_map.get(record["kind"], record["kind"])


def _normalization_ledger(assignments: list[dict[str, Any]]) -> dict[str, int]:
    ledger: dict[str, int] = Counter()
    for record in assignments:
        raw = record.get("semantic_raw")
        canonical = record.get("semantic")
        if raw and canonical and canonical != NOVEL_TERM:
            ledger[f"{raw} -> {canonical}"] += 1
    return dict(ledger.most_common(60))
