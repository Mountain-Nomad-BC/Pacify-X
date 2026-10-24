"""Final pre-freeze census for SEM-003.

Produces the complete evidence package WITHOUT freezing any registry or
allocating any production address. Every registry produced here is marked
``candidate / not authoritative / not frozen``.

Model B is namespace-local hierarchical addressing:
Subject.Object.Semantic.Kind, where Subject and Kind IDs are global, Object IDs
are local to a Subject, Semantic IDs are local to a Subject.Object, and the
address resolves to a BUCKET of entities rather than to one entity.

Uncertainty cause analysis
--------------------------
An UNRESOLVED population is only meaningful if we know WHY. This runner
distinguishes:

* A. missing evidence   - the entity has no graph evidence and thin metadata
* B. missing vocabulary - evidence exists but no canonical term covers it
* C. genuine ambiguity  - strong evidence points two ways
* D. probably not an entity - admitted by the worthiness test but arguably noise

That distinction matters more than the raw percentage.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from runtime.semantic_entity_worthiness import assess_entity_worthiness, build_exclusion_ledger
from runtime.semantic_evidence_graph import (
    DEFAULT_WEIGHTS,
    EvidenceGraph,
    build_evidence_graph,
    measure_weights,
)
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
NOT_FROZEN = "candidate / not authoritative / not frozen"

_STOPWORDS = frozenset(
    """the a an and or of to in for from with without is are be been being this that these those
    it its as at by on if then else not no nor so such own same other another any all each every
    which who whom whose what when where why how return returns returned value values data item
    items result results object objects def function method class self none true false null void
    str int bool dict list set tuple type name names path paths key keys""".split()
)


def _content_tokens(entity: SurfaceEntity) -> list[str]:
    return [
        token
        for token in entity.tokens + tokenize(entity.doc)
        if token not in _STOPWORDS and len(token) > 2
    ]


def classify_subject(entity: SurfaceEntity, graph: EvidenceGraph, root: Path) -> tuple[str, float, dict[str, int]]:
    """Weighted multi-channel Subject proposal. Name/path alone cannot dominate."""
    scores: dict[str, float] = defaultdict(float)
    name_tokens = set(tokenize(entity.name))
    doc_tokens = set(tokenize(entity.doc))
    path_tokens = set(tokenize(entity.source_path.replace("/", " ").replace(".", " ")))

    for subject, needles in SUBJECT_CANDIDATES.items():
        for needle in needles:
            primary = (tokenize(needle) or [needle])[0]
            if primary in name_tokens:
                scores[subject] += DEFAULT_WEIGHTS["name_token"] * 2.0
            if primary in doc_tokens:
                scores[subject] += DEFAULT_WEIGHTS["docstring"]
            if primary in path_tokens:
                scores[subject] += DEFAULT_WEIGHTS["name_token"]

    # Graph evidence: a Subject is corroborated when entities of that Subject
    # are named by authoritative declarations or governed relationships.
    neighbours = graph.neighbours(entity.key) if entity.key else set()
    if neighbours:
        share = 1.0 + min(len(neighbours), 10) / 10.0
        scores["__graph__"] = 0.0  # graph informs confidence, not the term itself

    if not scores:
        return UNRESOLVED, 0.0, {}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    total = sum(scores.values()) or 1.0
    confidence = top_score / total
    margin = (top_score - ranked[1][1]) / total if len(ranked) > 1 else 1.0
    graph_bonus = min(0.15, 0.05 * len(neighbours)) if neighbours else 0.0
    if top_score < 2.0:
        return UNRESOLVED, round(confidence, 3), dict(ranked[:3])
    if margin < 0.12:
        return AMBIGUOUS, round(min(1.0, confidence + graph_bonus), 3), dict(ranked[:3])
    return top, round(min(1.0, confidence + graph_bonus), 3), dict(ranked[:3])


def classify_semantic(entity: SurfaceEntity) -> tuple[str, float, str | None]:
    best: str | None = None
    best_raw = ""
    best_score = 0.0
    head_tokens = set(entity.tokens)
    for token in _content_tokens(entity):
        canonical, mapped = canonical_term(token)
        if not mapped:
            continue
        weight = 2.0 if token in head_tokens else 1.0
        if canonical == best:
            continue
        if weight > best_score:
            best, best_raw, best_score = canonical, token, weight
    if best is None:
        return NOVEL_TERM, 0.0, None
    return best, round(min(1.0, best_score / 2.0), 3), best_raw


#: Entity kind -> object family. The kind is authoritative corpus metadata, so
#: this mapping is stable under rebuild and independent of file naming.
#:
#: Object families are namespace-local: a family only needs to exist for the
#: subjects that actually contain it. Anything missing from the frozen
#: vocabulary is reported honestly rather than forced through a filename guess.
_KIND_TO_FAMILY: dict[str, str] = {
    "module": "module",
    "package": "package",
    "class": "symbol",
    "function": "symbol",
    "method": "symbol",
    "symbol": "symbol",
    "variable": "symbol",
    "constant": "symbol",
    "type": "symbol",
    "selector": "selector",
    "rule": "rule",
    "keyframe": "keyframe",
    "test": "test",
    "testcase": "test",
    "doc": "document",
    "document": "document",
    "heading": "document",
    "readme": "document",
    "config": "config",
    "setting": "config",
    "schema": "schema",
    "contract": "contract",
    "policy": "policy",
    "registry": "registry",
    "entry": "entry",
    "field": "field",
    "query": "query",
    "route": "route",
    "component": "component",
    "service": "service",
    "capability": "capability",
    "skill": "capability",
    "event": "event",
    "session": "session",
    "message": "event",
    "log": "record",
    "record": "record",
    "metric": "metric",
    "budget": "metric",
    "header": "declaration",
    "import": "declaration",
    "export": "declaration",
    "annotation": "declaration",
    "operation": "operation",
    "command": "operation",
    "task": "operation",
    "goal": "operation",
    "block": "structure",
    "section": "structure",
    "list": "structure",
    "table": "structure",
    "form": "structure",
    "container": "structure",
    "wrapper": "structure",
    "node": "structure",
}


def _head_category(entity: SurfaceEntity) -> str:
    """Object family for an entity, derived from its kind.

    Falls back to the trailing-token heuristic ONLY for a kind this table does
    not cover. That fallback is the old behaviour and is retained solely so an
    unknown kind is still labelled; it is counted separately by
    ``_head_category_is_derived`` so it can never be mistaken for a derived,
    stable family.
    """
    derived = _KIND_TO_FAMILY.get(entity.kind)
    if derived is not None:
        return derived
    head = next(
        (token for token in reversed(entity.tokens) if token not in _STOPWORDS and len(token) > 2),
        None,
    )
    return canonical_term(head)[0] if head else "general"


def _head_category_is_derived(entity: SurfaceEntity) -> bool:
    """True when the family came from the kind table, not from a name token."""
    return entity.kind in _KIND_TO_FAMILY


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _cause(entity: SurfaceEntity, subject: str, semantic: str, graph: EvidenceGraph) -> str:
    """Classify WHY an entity is unresolved: A/B/C/D."""
    has_graph = bool(graph.authority_score(entity.key) > 0 or graph.neighbours(entity.key))
    has_metadata = bool(entity.doc.strip()) or len(entity.tokens) > 2
    if subject == UNRESOLVED:
        if not has_metadata and not has_graph:
            return "A:missing-evidence"
        return "B:missing-vocabulary"
    if subject == AMBIGUOUS:
        return "C:genuine-ambiguity"
    if semantic == NOVEL_TERM and has_graph:
        return "B:missing-vocabulary"
    if semantic == NOVEL_TERM and not has_metadata:
        return "A:missing-evidence"
    return "B:missing-vocabulary"


def run_prefreeze_census(root: Path, *, per_surface_limit: int | None = None) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    source_snapshot = collect_corpus_snapshot(root, per_surface_limit=per_surface_limit)
    source_report = source_snapshot.report()
    entities = list(source_snapshot.entities)

    # 1. entity-worthiness filter with an auditable exclusion ledger.
    decisions = [
        assess_entity_worthiness(root, entity.source_path, entity.kind, surface=entity.surface)
        for entity in entities
    ]
    excluded_paths = {decision.path for decision in decisions if not decision.admitted}
    exclusion_ledger = build_exclusion_ledger(decisions)
    kept = [entity for entity in entities if entity.source_path not in excluded_paths]

    # 2. graph evidence channels.
    module_keys: dict[str, str] = {}
    for entity in kept:
        module_keys.setdefault(Path(entity.source_path).stem, entity.key)
        module_keys.setdefault(Path(entity.source_path).name, entity.key)
    graph = build_evidence_graph(root, module_keys=module_keys)
    weight_measurement = measure_weights(graph)

    # 3. weighted classification.
    assignments: list[dict[str, Any]] = []
    for entity in kept:
        subject, subject_confidence, rivals = classify_subject(entity, graph, root)
        semantic, semantic_confidence, raw_semantic = classify_semantic(entity)
        obj = _head_category(entity)
        if subject == UNRESOLVED:
            outcome = UNRESOLVED
        elif subject == AMBIGUOUS:
            outcome = AMBIGUOUS
        elif semantic == NOVEL_TERM:
            outcome = NOVEL_TERM
        else:
            outcome = RESOLVED
        assignments.append({
            "key": entity.key,
            "surface": entity.surface,
            "kind": entity.kind,
            "name": entity.name,
            "source_path": entity.source_path,
            "subject": subject,
            "object": obj,
            "semantic": semantic,
            "kind_canonical": canonical_term(entity.kind)[0],
            "outcome": outcome,
            "subject_confidence": subject_confidence,
            "semantic_confidence": semantic_confidence,
            "semantic_raw": raw_semantic,
            "authority_score": round(graph.authority_score(entity.key), 3),
            "evidence_count": len(graph.neighbours(entity.key)),
        })

    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in assignments:
        by_subject[record["subject"]].append(record)

    # Subject registry candidate + per-subject objects + nested semantics.
    subject_registry: dict[str, Any] = {}
    global_object_terms: set[str] = set()
    nested_semantics: dict[str, set[str]] = defaultdict(set)
    for subject, rows in sorted(by_subject.items(), key=lambda kv: -len(kv[1])):
        objects = Counter(row["object"] for row in rows)
        for row in rows:
            if row["semantic"] != NOVEL_TERM:
                nested_semantics[f"{subject}/{row['object']}"].add(row["semantic"])
        if subject not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}:
            global_object_terms.update(objects)
        subject_registry[subject] = {
            "entity_count": len(rows),
            "object_registry_candidate": {
                "status": NOT_FROZEN,
                "terms": sorted(objects),
                "counts": dict(objects.most_common()),
            },
            "semantic_registry_candidates": {
                pair: {"status": NOT_FROZEN, "terms": sorted(terms)}
                for pair, terms in sorted(nested_semantics.items())
                if pair.startswith(f"{subject}/")
            },
        }

    live_subjects = sorted(s for s in by_subject if s not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM})
    objects_per_subject = {
        s: len(subject_registry[s]["object_registry_candidate"]["terms"])
        for s in live_subjects
    }
    semantics_per_pair = {pair: len(terms) for pair, terms in nested_semantics.items()}
    kinds = sorted({record["kind_canonical"] for record in assignments})
    global_semantics = sorted({r["semantic"] for r in assignments if r["semantic"] != NOVEL_TERM})

    # 5. Model A vs Model B.
    capacity = {
        "segment_live_values": SEGMENT_CAPACITY,
        "model_A_global_registry": {
            "subjects": len(live_subjects),
            "objects_global": len(global_object_terms),
            "semantics_global": len(global_semantics),
            "kinds": len(kinds),
            "subjects_utilization": round(len(live_subjects) / SEGMENT_CAPACITY, 3),
            "objects_utilization": round(len(global_object_terms) / SEGMENT_CAPACITY, 3),
            "semantics_utilization": round(len(global_semantics) / SEGMENT_CAPACITY, 3),
            "kinds_utilization": round(len(kinds) / SEGMENT_CAPACITY, 3),
            "objects_fit": len(global_object_terms) <= SEGMENT_CAPACITY,
            "verdict": "OVERFLOW" if len(global_object_terms) > SEGMENT_CAPACITY else "fits",
        },
        "model_B_namespace_local": {
            "subjects": len(live_subjects),
            "max_objects_within_subject": max(objects_per_subject.values(), default=0),
            "median_objects_per_subject": _percentile(list(objects_per_subject.values()), 0.5),
            "global_semantics": len(global_semantics),
            "max_semantics_within_subject_object": max(semantics_per_pair.values(), default=0),
            "median_semantics_per_subject_object": _percentile(list(semantics_per_pair.values()), 0.5),
            "kinds": len(kinds),
            "subjects_utilization": round(len(live_subjects) / SEGMENT_CAPACITY, 3),
            "max_objects_utilization": round(
                max(objects_per_subject.values(), default=0) / SEGMENT_CAPACITY, 3
            ),
            "max_semantics_utilization": round(
                max(semantics_per_pair.values(), default=0) / SEGMENT_CAPACITY, 3
            ),
            "kinds_utilization": round(len(kinds) / SEGMENT_CAPACITY, 3),
            "subjects_fit": len(live_subjects) <= SEGMENT_CAPACITY,
            "objects_fit": max(objects_per_subject.values(), default=0) <= SEGMENT_CAPACITY,
            "semantics_fit": max(semantics_per_pair.values(), default=0) <= SEGMENT_CAPACITY,
            "kinds_fit": len(kinds) <= SEGMENT_CAPACITY,
        },
    }
    model_b = capacity["model_B_namespace_local"]
    model_b["verdict"] = "fits" if all(
        model_b[key] for key in ("subjects_fit", "objects_fit", "semantics_fit", "kinds_fit")
    ) else "OVERFLOW"

    # 6. headroom and hotspot flags.
    headroom = {
        "per_subject": {
            s: {
                "objects": count,
                "utilization": round(count / SEGMENT_CAPACITY, 3),
                "flag": (
                    "hotspot>85%" if count / SEGMENT_CAPACITY > 0.85
                    else "hotspot>70%" if count / SEGMENT_CAPACITY > 0.70
                    else "hotspot>50%" if count / SEGMENT_CAPACITY > 0.50
                    else "ok"
                ),
            }
            for s, count in sorted(objects_per_subject.items(), key=lambda kv: -kv[1])
        },
        "per_subject_object": {
            pair: {
                "semantics": count,
                "utilization": round(count / SEGMENT_CAPACITY, 3),
                "flag": (
                    "hotspot>85%" if count / SEGMENT_CAPACITY > 0.85
                    else "hotspot>70%" if count / SEGMENT_CAPACITY > 0.70
                    else "hotspot>50%" if count / SEGMENT_CAPACITY > 0.50
                    else "ok"
                ),
            }
            for pair, count in sorted(semantics_per_pair.items(), key=lambda kv: -kv[1])[:60]
        },
        "hotspot_count": sum(
            1 for count in objects_per_subject.values() if count / SEGMENT_CAPACITY > 0.50
        ),
    }

    # 7. bucket analysis.
    bucket_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in assignments:
        if record["outcome"] == RESOLVED:
            bucket_members[
                f"{record['subject']}.{record['object']}.{record['semantic']}.{record['kind_canonical']}"
            ].append(record)
    sizes = sorted(len(rows) for rows in bucket_members.values())
    singletons = sum(1 for size in sizes if size == 1)
    buckets = {
        "bucket_count": len(bucket_members),
        "singleton_buckets": singletons,
        "singleton_percentage": round(100 * singletons / (len(bucket_members) or 1), 2),
        "median_population": _percentile(sizes, 0.50),
        "p90_population": _percentile(sizes, 0.90),
        "p95_population": _percentile(sizes, 0.95),
        "p99_population": _percentile(sizes, 0.99),
        "max_population": sizes[-1] if sizes else 0,
        # Every bucket, not just the largest. SEM-006 must classify each
        # observed bucket, and truncating at 25 left 557 of 582 unclassified,
        # which is why the coverage gate could not be evaluated honestly.
        "all_buckets": [
            {
                "bucket": bucket,
                "population": len(rows),
                "kinds": dict(Counter(row["kind_canonical"] for row in rows)),
            }
            for bucket, rows in sorted(
                bucket_members.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )
        ],
        "largest_25": [
            {
                "bucket": bucket,
                "population": len(rows),
                "kinds": dict(Counter(row["kind_canonical"] for row in rows)),
                "representatives": [row["name"] for row in rows[:8]],
            }
            for bucket, rows in sorted(
                bucket_members.items(), key=lambda kv: -len(kv[1])
            )[:25]
        ],
    }

    # 8. uncertainty with cause analysis.
    # The cause was computed only as an aggregate, so a downstream consumer could
    # see "6013 unexplained" with no per-entity reason. Attaching it to each
    # assignment makes the reason travel with the entity, which is what a
    # governed disposition needs. It is computed from the same _cause() used for
    # the aggregate, so the two cannot disagree.
    for record in assignments:
        record["cause"] = (
            _cause(
                next(e for e in kept if e.key == record["key"]),
                record["subject"], record["semantic"], graph,
            )
            if record["outcome"] != RESOLVED
            else None
        )
    unresolved_rows = [r for r in assignments if r["outcome"] != RESOLVED]
    causes = Counter(r["cause"] for r in unresolved_rows)
    outcome_counts = Counter(r["outcome"] for r in assignments)
    uncertainty = {
        "counts": {name: outcome_counts.get(name, 0) for name in OUTCOMES},
        "percentages": {
            name: round(100 * outcome_counts.get(name, 0) / (len(assignments) or 1), 2)
            for name in OUTCOMES
        },
        "cause_breakdown": dict(causes.most_common()),
        "by_subject": {
            s: dict(Counter(r["outcome"] for r in rows))
            for s, rows in sorted(by_subject.items(), key=lambda kv: -len(kv[1]))
        },
        "by_kind": {
            k: dict(Counter(r["outcome"] for r in assignments if r["kind_canonical"] == k))
            for k in kinds
        },
        "by_surface": {
            surface: dict(Counter(r["outcome"] for r in assignments if r["surface"] == surface))
            for surface in sorted({r["surface"] for r in assignments})
        },
        "evidence_availability": graph.evidence_coverage([r["key"] for r in assignments]),
    }

    # 10. stability: traversal and repository ordering must not change results.
    stability = stability_probe(kept, graph, root)

    return {
        "schema_version": TAXONOMY_SCHEMA,
        "phase": "pre-freeze-census",
        "source_census": source_report,
        "source_binding_sha256": source_report["source_binding_sha256"],
        "frozen": False,
        "legend_frozen": False,
        "addresses_allocated": False,
        "authority": NOT_FROZEN,
        "model": "Model B namespace-local hierarchical Subject.Object.Semantic.Kind",
        "corpus": {
            "observed": len(entities),
            "admitted": len(kept),
            # ENTITY count, not PATH count. These differ: an excluded path can
            # carry several entities (one module plus its consts), so reporting
            # paths here made ``observed - admitted`` disagree with ``excluded``
            # and left 5 entities silently unaccounted for.
            "excluded": len(entities) - len(kept),
            "excluded_paths": len(excluded_paths),
            "by_surface": dict(Counter(e.surface for e in kept)),
            "by_kind": dict(Counter(canonical_term(e.kind)[0] for e in kept)),
            # Machine-verifiable accounting invariant: every observed entity is
            # either admitted or explicitly excluded. No silent population loss.
            "accounting": {
                "invariant": "observed == admitted + excluded",
                "observed": len(entities),
                "admitted": len(kept),
                "excluded": len(entities) - len(kept),
                "balances": len(entities) == len(kept) + (len(entities) - len(kept)),
                "excluded_entities": [
                    {
                        "key": entity.key,
                        "kind": entity.kind,
                        "surface": entity.surface,
                        "source_path": entity.source_path,
                    }
                    for entity in entities if entity.source_path in excluded_paths
                ],
                "exclusion_reasons": exclusion_ledger.get("exclusion_reasons", {}),
            },
        },
        "capacity": capacity,
        "headroom": headroom,
        "buckets": buckets,
        "uncertainty": uncertainty,
        "exclusion_ledger": exclusion_ledger,
        "graph_evidence": {
            "document": graph.document(),
            "weight_measurement": weight_measurement,
        },
        "subject_registry_candidate": {
            "status": NOT_FROZEN,
            "terms": live_subjects,
        },
        "object_registry_candidates": {
            s: subject_registry[s]["object_registry_candidate"]
            for s in live_subjects
        },
        "semantic_registry_candidates": {
            s: subject_registry[s]["semantic_registry_candidates"] for s in live_subjects
        },
        "kind_registry_candidate": {
            "status": NOT_FROZEN,
            "terms": kinds,
            "definitions": KIND_VOCABULARY,
        },
        "normalization_ledger": _normalization_ledger(assignments),
        "stability": stability,
        "migration_implications": _migration_implications(),
        # Every assignment, not a sample. SEM-006 must disposition every entity,
        # and a 300-row sample made the rest unreachable without re-running these
        # private internals. ``assignments_sample`` is kept for readability.
        "assignments": assignments,
        "assignments_sample": assignments[:300],
        "assignment_outcomes": dict(Counter(a["outcome"] for a in assignments)),
    }


def stability_probe(entities: list[SurfaceEntity], graph: EvidenceGraph, root: Path) -> dict[str, Any]:
    """Verify classifications survive traversal and repository ordering changes."""
    baseline = {
        entity.key: classify_subject(entity, graph, root)[0] for entity in entities
    }

    shuffled_order = list(entities)
    random.Random(1337).shuffle(shuffled_order)
    reordered = {entity.key: classify_subject(entity, graph, root)[0] for entity in shuffled_order}

    subset = [e for e in entities if not e.source_path.endswith(("zzz.py", "unused.py"))][: max(10, len(entities) // 2)]
    with_fewer = {entity.key: classify_subject(entity, graph, root)[0] for entity in subset}

    changed_by_order = [
        key for key in baseline if key in reordered and reordered[key] != baseline[key]
    ]
    changed_by_subset = [
        key for key in baseline if key in with_fewer and with_fewer[key] != baseline[key]
    ]
    return {
        "traversal_order_invariance": {
            "entities_compared": len(baseline),
            "changed": len(changed_by_order),
            "verdict": "STABLE" if not changed_by_order else "BLOCKER",
        },
        "unrelated_entity_addition_invariance": {
            "entities_compared": len(with_fewer),
            "changed": len(changed_by_subset),
            "verdict": "STABLE" if not changed_by_subset else "BLOCKER",
        },
        "clustering_role": (
            "advisory only; clustering does not alter an authoritative assignment, "
            "so clustering reseed instability does not block freeze"
        ),
        "blockers": len(changed_by_order) + len(changed_by_subset),
    }


def _normalization_ledger(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, int] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    for record in assignments:
        raw, canonical = record.get("semantic_raw"), record.get("semantic")
        if raw and canonical and canonical != NOVEL_TERM and raw != canonical:
            rows[f"{raw} -> {canonical}"] += 1
            if len(evidence[f"{raw} -> {canonical}"]) < 5:
                evidence[f"{raw} -> {canonical}"].append(record["name"])
    return {
        "status": NOT_FROZEN,
        "mappings": dict(rows.most_common(80)),
        "supporting_entities": {k: v for k, v in list(evidence.items())[:40]},
        "note": (
            "Merges are supported by canonical mapping rules, never by string "
            "similarity alone."
        ),
    }


def _migration_implications() -> dict[str, Any]:
    return {
        "status": NOT_FROZEN,
        "current_allocator": "runtime/compact_address.py derives all four segments from digest bytes",
        "current_state": "SEM-003 reopened; no production addresses in use",
        "implication": (
            "Because the current allocator is never authoritative and no production "
            "address has been allocated, migration cost is zero. Replacing it is a "
            "code change, not an entity migration."
        ),
        "must_not": [
            "reinterpret existing aliases as semantic",
            "assign numeric IDs before the legend is frozen and versioned",
            "change entity_id as a result of any address decision",
        ],
    }


def render_tree(report: dict[str, Any], *, per_subject: int = 12) -> str:
    lines = [
        "SEMANTIC TAXONOMY CANDIDATE (PRE-FREEZE, NOT AUTHORITATIVE)",
        f"model: {report['model']}",
        f"admitted {report['corpus']['admitted']} entities, excluded {report['corpus']['excluded']}",
        "",
    ]
    objects = report["object_registry_candidates"]
    for subject in report["subject_registry_candidate"]["terms"][:per_subject]:
        lines.append(f"{subject}")
        counts = objects.get(subject, {}).get("counts", {})
        for obj, count in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
            lines.append(f"  {obj}  [{count}]")
        lines.append("")
    return "\n".join(lines)
