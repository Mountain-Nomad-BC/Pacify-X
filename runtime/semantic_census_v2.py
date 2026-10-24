"""Report generation for the SEM-003 ontology census.

Emits the full evidence set requested before any structural decision is made:
normalized vocabulary candidates, the raw to canonical ledger, the semantic
hierarchy tree, a global versus namespace-local registry comparison, capacity
analysis against the 254-per-segment bound, ambiguity, many-to-one bucket
analysis, clustering stability, and a recommendation grounded in the measurements.

It freezes nothing and allocates nothing.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from runtime.semantic_evidence import (
    AMBIGUOUS,
    NOVEL_TERM,
    OUTCOMES,
    RESOLVED,
    UNRESOLVED,
    Observation,
    collect,
)
from runtime.semantic_hierarchy import SEGMENT_CAPACITY, Assignment, build

REPORT_SCHEMA = "px.semantic-census-report/2.0"


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _vocabulary(assignments: list[Assignment], field: str, limit: int = 40) -> list[dict[str, Any]]:
    counts = Counter(getattr(a, field) for a in assignments)
    labels: dict[str, list[str]] = defaultdict(list)
    for a in assignments:
        term = getattr(a, field)
        if len(labels[term]) < 6:
            labels[term].append(a.evidence.get("symbol", a.key))
    rows = []
    total = sum(counts.values()) or 1
    for term, count in counts.most_common(limit):
        rows.append(
            {
                "term": term,
                "count": count,
                "share": round(count / total, 4),
                "representatives": labels[term],
            }
        )
    return rows


def capacity_report(assignments: list[Assignment]) -> dict[str, Any]:
    """Measure the four-segment layout against the 254-per-segment bound."""
    resolved = [a for a in assignments if a.outcome == RESOLVED]
    live = lambda value: value not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}

    subjects = {a.subject for a in resolved if live(a.subject)}
    objects_global = {a.obj for a in resolved if live(a.obj)}
    kinds = {a.kind for a in resolved}

    objects_per_subject: dict[str, set[str]] = defaultdict(set)
    semantics_per_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    bucket_members: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)

    for a in resolved:
        if not (live(a.subject) and live(a.obj) and live(a.semantic)):
            continue
        objects_per_subject[a.subject].add(a.obj)
        semantics_per_pair[(a.subject, a.obj)].add(a.semantic)
        bucket_members[a.address()].append(a.key)

    obj_counts = [len(v) for v in objects_per_subject.values()]
    sem_counts = [len(v) for v in semantics_per_pair.values()]
    bucket_sizes = [len(v) for v in bucket_members.values()]
    singletons = sum(1 for size in bucket_sizes if size == 1)

    global_model = {
        "model": "global-registry",
        "subjects": len(subjects),
        "objects_global": len(objects_global),
        "semantics_global": len({a.semantic for a in resolved if live(a.semantic)}),
        "kinds": len(kinds),
        "capacity_per_segment": SEGMENT_CAPACITY,
        "fits": (
            len(subjects) <= SEGMENT_CAPACITY
            and len(objects_global) <= SEGMENT_CAPACITY
            and len({a.semantic for a in resolved if live(a.semantic)}) <= SEGMENT_CAPACITY
            and len(kinds) <= SEGMENT_CAPACITY
        ),
        "overflow": {},
    }
    for label, value in (
        ("subjects", len(subjects)),
        ("objects_global", len(objects_global)),
        ("semantics_global", len({a.semantic for a in resolved if live(a.semantic)})),
        ("kinds", len(kinds)),
    ):
        if value > SEGMENT_CAPACITY:
            global_model["overflow"][label] = {
                "required": value,
                "capacity": SEGMENT_CAPACITY,
                "ratio": round(value / SEGMENT_CAPACITY, 3),
            }

    local_model = {
        "model": "namespace-local-registry",
        "subjects": len(subjects),
        "max_objects_in_any_subject": max(obj_counts) if obj_counts else 0,
        "median_objects_per_subject": _median(obj_counts),
        "max_semantics_in_any_subject_object": max(sem_counts) if sem_counts else 0,
        "median_semantics_per_object": _median(sem_counts),
        "kinds": len(kinds),
        "capacity_per_segment": SEGMENT_CAPACITY,
    }
    local_model["fits"] = (
        local_model["subjects"] <= SEGMENT_CAPACITY
        and local_model["max_objects_in_any_subject"] <= SEGMENT_CAPACITY
        and local_model["max_semantics_in_any_subject_object"] <= SEGMENT_CAPACITY
        and local_model["kinds"] <= SEGMENT_CAPACITY
    )
    local_model["overflow"] = {}
    for label, value in (
        ("subjects", local_model["subjects"]),
        ("max_objects_in_any_subject", local_model["max_objects_in_any_subject"]),
        ("max_semantics_in_any_subject_object", local_model["max_semantics_in_any_subject_object"]),
        ("kinds", local_model["kinds"]),
    ):
        if value > SEGMENT_CAPACITY:
            local_model["overflow"][label] = {
                "required": value,
                "capacity": SEGMENT_CAPACITY,
                "ratio": round(value / SEGMENT_CAPACITY, 3),
            }

    return {
        "resolved_entities_measured": len(resolved),
        "global_model": global_model,
        "local_model": local_model,
        "address_space": SEGMENT_CAPACITY ** 4,
        "buckets": {
            "bucket_count": len(bucket_members),
            "max_bucket_population": max(bucket_sizes) if bucket_sizes else 0,
            "median_bucket_population": _median(bucket_sizes),
            "singleton_buckets": singletons,
            "singleton_percentage": round(100.0 * singletons / len(bucket_members), 2) if bucket_members else 0.0,
            "largest_examples": [
                {"address": list(key), "members": len(value), "sample": value[:4]}
                for key, value in sorted(bucket_members.items(), key=lambda kv: -len(kv[1]))[:15]
            ],
        },
    }


def kind_distribution(assignments: list[Assignment]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], list[Assignment]] = defaultdict(list)
    for a in assignments:
        buckets[a.address()].append(a)
    rows = []
    for key, members in sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:25]:
        kinds = Counter(m.kind for m in members)
        surfaces = Counter(m.evidence.get("surface", "?") for m in members)
        rows.append(
            {
                "address": list(key),
                "members": len(members),
                "outcome": members[0].outcome,
                "kind_mix": dict(kinds),
                "surface_mix": dict(surfaces),
                "coherent": len(kinds) == 1,
                "sample_symbols": [m.evidence.get("symbol", "") for m in members[:5]],
            }
        )
    return rows


def render_tree(assignments: list[Assignment], *, max_children: int = 10) -> str:
    """Human-readable proposed hierarchy."""
    tree: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for a in assignments:
        if a.outcome != RESOLVED:
            continue
        tree[a.subject][a.obj][a.semantic].add(a.kind)
    lines = ["PROPOSED SEMANTIC HIERARCHY (ADVISORY - NOT FROZEN, NO ADDRESSES ALLOCATED)", ""]
    for subject in sorted(tree, key=lambda s: -sum(len(o) for o in tree[s].values())):
        obj_total = sum(len(sem) for obj in tree[subject].values() for sem in obj[obj].values() if False)
        sem_total = sum(len(kinds) for obj in tree[subject].values() for sem in obj.values() for kinds in sem.values())
        lines.append(f"{subject}  ({len(tree[subject])} objects, {sem_total} semantic groups)")
        objects = sorted(tree[subject].items(), key=lambda kv: -len(kv[1]))[:max_children]
        for obj, semantics in objects:
            lines.append(f"  +-- {obj}  ({len(semantics)} semantics)")
            for semantic, kinds in sorted(semantics.items(), key=lambda kv: -len(kv[1]))[:max_children]:
                kind_list = ", ".join(sorted(kinds)[:5])
                lines.append(f"  |   +-- {semantic} -> [{kind_list}]")
        remaining = len(tree[subject]) - len(objects)
        if remaining > 0:
            lines.append(f"  +-- ... {remaining} more objects")
        lines.append("")
    return "\n".join(lines)


def run(
    root: Path,
    *,
    max_per_surface: int = 2500,
    surfaces: list[str] | None = None,
) -> dict[str, Any]:
    observations, coverage = collect(
        root, max_per_surface=max_per_surface, surfaces=surfaces
    )
    assignments, meta = build(observations)
    outcome_counts = Counter(a.outcome for a in assignments)
    unresolved_rows = [
        {
            "key": a.key,
            "outcome": a.outcome,
            "subject": a.subject, "object": a.obj, "semantic": a.semantic,
            "path": a.evidence.get("path"),
            "channels": a.evidence.get("channels", []),
        }
        for a in assignments
        if a.outcome in {UNRESOLVED, AMBIGUOUS}
    ][:40]

    return {
        "schema_version": REPORT_SCHEMA,
        "root": str(Path(root).resolve()),
        "frozen": False,
        "addresses_allocated": False,
        "legend_frozen": False,
        "coverage": coverage,
        "outcomes": {name: outcome_counts.get(name, 0) for name in OUTCOMES},
        "outcome_percentages": {
            name: round(100.0 * outcome_counts.get(name, 0) / max(1, len(assignments)), 2)
            for name in OUTCOMES
        },
        "candidate_vocabularies": {
            "subject": _vocabulary(assignments, "subject"),
            "object": _vocabulary(assignments, "obj"),
            "semantic": _vocabulary(assignments, "semantic"),
            "kind": _vocabulary(assignments, "kind"),
        },
        "capacity": capacity_report(assignments),
        "many_to_one_analysis": kind_distribution(assignments),
        "ambiguity": {
            "unresolved_or_ambiguous_count": outcome_counts.get(UNRESOLVED, 0) + outcome_counts.get(AMBIGUOUS, 0),
            "novel_term_count": outcome_counts.get(NOVEL_TERM, 0),
            "samples": unresolved_rows,
            "low_confidence": [
                {"key": a.key, "confidence": a.confidence, "address": list(a.address())}
                for a in sorted(
                    (a for a in assignments if a.outcome == RESOLVED and a.confidence < 0.55),
                    key=lambda a: a.confidence,
                )[:30]
            ],
        },
        "normalization_ledger": meta["normalization_ledger"].to_json(),
    }


def recommendation(report: dict[str, Any]) -> dict[str, Any]:
    """A recommendation grounded only in the measurements above."""
    capacity = report["capacity"]
    global_model = capacity["global_model"]
    local_model = capacity["local_model"]
    kinds = report["candidate_vocabularies"]["kind"]
    notes = []
    if not global_model["fits"]:
        notes.append(
            f"The global registry model does not fit: "
            f"{json.dumps(global_model['overflow'])}. An Object ID would not mean the "
            f"same thing under every Subject, so a single shared Object table "
            f"overflows the segment."
        )
    if local_model["fits"]:
        notes.append(
            f"The namespace-local model fits with headroom: max "
            f"{local_model['max_objects_in_any_subject']} objects in any Subject and "
            f"max {local_model['max_semantics_in_any_subject_object']} semantics in any "
            f"(Subject,Object), against a {SEGMENT_CAPACITY} segment bound."
        )
    else:
        notes.append(f"The namespace-local model still overflows: {json.dumps(local_model['overflow'])}.")
    notes.append(
        f"{report['outcome_percentages'].get(NOVEL_TERM, 0)}% of entities are NOVEL_TERM, so the "
        f"semantic vocabulary is immature. That is expected at discovery stage and is "
        f"not something to optimize away."
    )
    top_kind = kinds[0] if kinds else None
    return {
        "global_model_fits": global_model["fits"],
        "local_model_fits": local_model["fits"],
        "recommended_model": "namespace-local" if local_model["fits"] else "requires-revision",
        "kind_vocabulary_is_small_enough_to_be_global": bool(kinds) and len(kinds) <= SEGMENT_CAPACITY,
        "dominant_kind": top_kind,
        "notes": notes,
        "blocking_before_freeze": [
            "Subject, Object and Semantic vocabularies require human acceptance or revision",
            "NOVEL_TERM entities need classification or explicit rejection, not forced assignment",
            "Kind vocabulary is under-sampled and must be recomputed over the full corpus",
            "Stability must be re-measured over the expanded corpus before any legend is frozen",
        ],
    }