"""Census runner and report rendering for SEM-003 taxonomy discovery.

Produces the evidence BEFORE any legend is frozen:
candidate vocabularies with counts and representatives, ambiguity and
low-confidence sets, identical four-segment classifications, cardinality,
projected utilization, clustering quality and stability, and a human-readable
tree. It writes no legend and allocates no production address.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from runtime.semantic_census import (
    AMBIGUOUS,
    CENSUS_SCHEMA,
    NOVEL_TERM,
    UNRESOLVED,
    Classification,
    ObservedEntity,
    Proposal,
    census_corpus,
    classify,
)


def build_subject_taxonomy(observed: list[ObservedEntity], seeds: tuple[str, ...]) -> dict[str, list[str]]:
    """Propose candidate Subject domains.

    Seeds are the concepts named in the design; each is retained only if the
    corpus actually evidences it. Nothing is added that the corpus does not show.
    """
    vocab = [seed for seed in seeds if any(
        seed in entity.source_path or seed in entity.symbol.lower() or seed in entity.docstring.lower()
        for entity in observed
    )]
    return {"subject": vocab}


def cluster_stability(
    observed: list[ObservedEntity], *, n_clusters: int = 12, seeds: tuple[int, ...] = (0, 7, 42)
) -> dict[str, Any]:
    """Advisory clustering with a stability estimate across reseeded runs.

    Stability is measured as adjusted Rand index between independent runs. A low
    score is a WARNING that the proposed grouping is not reproducible, and is
    reported as such rather than smoothed over.
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics import adjusted_rand_score
    except ImportError:
        return {"available": False, "reason": "scikit-learn is not importable"}
    corpus = [entity.feature_text() for entity in observed]
    if len(corpus) < n_clusters + 2:
        return {"available": False, "reason": "corpus too small to cluster"}
    vectorizer = TfidfVectorizer(
        max_features=4000, stop_words="english", token_pattern=r"[a-z][a-z0-9_]{2,}"
    )
    try:
        matrix = vectorizer.fit_transform(corpus)
    except ValueError as error:
        return {"available": False, "reason": f"vectorization failed: {error}"}
    labels = []
    for seed in seeds:
        model = KMeans(n_clusters=n_clusters, n_init=4, random_state=seed)
        labels.append(model.fit_predict(matrix))
    scores = [
        adjusted_rand_score(labels[i], labels[j])
        for i in range(len(labels))
        for j in range(i + 1, len(labels))
    ]
    mean_score = sum(scores) / len(scores) if scores else 0.0
    return {
        "available": True,
        "vectorizer": "TfidfVectorizer(max_features=4000)",
        "kmeans_n_init": 4,
        "n_clusters": n_clusters,
        "reseeds": list(seeds),
        "pairwise_adjusted_rand": [round(score, 4) for score in scores],
        "mean_adjusted_rand": round(mean_score, 4),
        "verdict": (
            "stable" if mean_score >= 0.6
            else "weak" if mean_score >= 0.35
            else "unstable"
        ),
        "warning": (
            None if mean_score >= 0.6
            else "Clustering is not reproducible across reseeds. Proposals from it "
                 "must not be promoted to a legend without human review."
        ),
    }


def _proposals(dimension: str, values: Counter[str], label_of: dict[str, str]) -> list[Proposal]:
    total = sum(values.values()) or 1
    rows = []
    for term, count in values.most_common():
        rows.append(
            Proposal(
                dimension=dimension,
                term=term,
                count=count,
                support=count / total,
                representatives=label_of.get(term, [])[:6],
            )
        )
    return rows


def run_census(
    root: Path,
    *,
    subject_seeds: tuple[str, ...] = (
        "runtime", "governance", "memory", "learning", "verification",
        "diagnostics", "routing", "orchestration", "retrieval",
        "installation", "release", "code", "lsp", "integration",
        "capability", "evidence", "project", "cognitive", "metacognitive",
    ),
    max_entities: int = 6000,
) -> dict[str, Any]:
    observed = census_corpus(root, max_entities=max_entities)
    taxonomy = build_subject_taxonomy(observed, subject_seeds)
    classifications: list[Classification] = [classify(entity, taxonomy) for entity in observed]

    labels: dict[str, list[str]] = defaultdict(list)
    for entity in observed:
        labels[entity.source_path].append(entity.symbol)

    subject_counts = Counter(c.subject for c in classifications)
    object_counts = Counter(c.obj for c in classifications)
    semantic_counts = Counter(c.semantic for c in classifications)
    kind_counts = Counter(c.kind for c in classifications)

    subject_labels: dict[str, list[str]] = defaultdict(list)
    object_labels: dict[str, list[str]] = defaultdict(list)
    semantic_labels: dict[str, list[str]] = defaultdict(list)
    kind_labels: dict[str, list[str]] = defaultdict(list)
    for entity, c in zip(observed, classifications):
        subject_labels[c.subject].append(f"{c.kind}:{entity.symbol}")
        object_labels[c.obj].append(f"{c.subject}/{entity.symbol}")
        semantic_labels[c.semantic].append(f"{c.subject}/{entity.symbol}")
        kind_labels[c.kind].append(f"{c.subject}/{entity.symbol}")

    # Identical four-segment classifications are legitimate, not an error.
    four_segment = Counter(c.four_segment() for c in classifications)
    shared = {key: count for key, count in four_segment.items() if count > 1}

    ambiguous = [c for c in classifications if c.outcome == AMBIGUOUS]
    unresolved = [c for c in classifications if c.outcome == UNRESOLVED]
    novel = [c for c in classifications if c.outcome == NOVEL_TERM]
    low_confidence = sorted(
        (c for c in classifications if c.outcome == "RESOLVED" and c.confidence < 0.55),
        key=lambda c: c.confidence,
    )

    live_subjects = [t for t in subject_counts if t not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}]
    live_objects = [t for t in object_counts if t not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}]
    live_semantics = [t for t in semantic_counts if t not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}]
    live_kinds = [t for t in kind_counts if t not in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}]

    capacity = 254 ** 4
    utilization = {
        "segment_capacity": 254,
        "subject_cardinality": len(live_subjects),
        "subject_utilization": round(len(live_subjects) / 254, 4),
        "object_cardinality": len(live_objects),
        "object_utilization": round(len(live_objects) / 254, 4),
        "semantic_cardinality": len(live_semantics),
        "semantic_utilization": round(len(live_semantics) / 254, 4),
        "kind_cardinality": len(live_kinds),
        "kind_utilization": round(len(live_kinds) / 254, 4),
        "address_space": capacity,
        "max_shared_classification_size": max(shared.values()) if shared else 0,
        "shared_classification_groups": len(shared),
    }

    outcome_counts = Counter(c.outcome for c in classifications)
    return {
        "schema_version": CENSUS_SCHEMA,
        "root": str(Path(root).resolve()),
        "frozen": False,
        "addresses_allocated": False,
        "corpus": {
            "observed_entities": len(observed),
            "distinct_sources": len({e.source_path for e in observed}),
            "include_globs": ["runtime/**/*.py", "extension/src/**/*.js"],
        },
        "outcomes": {name: outcome_counts.get(name, 0) for name in
                     ("RESOLVED", UNRESOLVED, AMBIGUOUS, NOVEL_TERM)},
        "candidate_vocabularies": {
            "subject": [p.to_json() for p in _proposals("Subject", subject_counts, subject_labels)],
            "object": [p.to_json() for p in _proposals("Object", object_counts, object_labels)],
            "semantic": [p.to_json() for p in _proposals("Semantic", semantic_counts, semantic_labels)],
            "kind": [p.to_json() for p in _proposals("Kind", kind_counts, kind_labels)],
        },
        "ambiguity": {
            "ambiguous": [c.entity_key for c in ambiguous[:40]],
            "unresolved": [c.entity_key for c in unresolved[:40]],
            "novel_term": [c.entity_key for c in novel[:40]],
            "low_confidence": [
                {"entity_key": c.entity_key, "confidence": c.confidence}
                for c in low_confidence[:40]
            ],
        },
        "identical_four_segment_classifications": {
            "group_count": len(shared),
            "largest_group": max(shared.values()) if shared else 0,
            "examples": [
                {"segments": list(key), "count": count}
                for key, count in sorted(shared.items(), key=lambda kv: -kv[1])[:15]
            ],
        },
        "cardinality_and_utilization": utilization,
        "clustering": cluster_stability(observed),
    }


def render_tree(report: dict[str, Any], *, max_per_level: int = 8) -> str:
    """Human-readable proposed hierarchy."""
    def top(dim: str) -> list[Proposal]:
        rows = report["candidate_vocabularies"][dim]
        return sorted(rows, key=lambda p: -p["count"])[:max_per_level]

    lines: list[str] = []
    lines.append("PROPOSED SEMANTIC TAXONOMY (DRY RUN - NOT FROZEN)")
    lines.append(
        f"observed {report['corpus']['observed_entities']} entities across "
        f"{report['corpus']['distinct_sources']} sources"
    )
    lines.append(f"outcomes: {json.dumps(report['outcomes'])}")
    lines.append("")
    for subject in top("Subject"):
        lines.append(f"{subject['term']}  [{subject['count']} entities]")
        objects = [o for o in report["candidate_vocabularies"]["object"]
                   if o["term"] != subject["term"]]
        for obj in objects[:max_per_level]:
            lines.append(f"  {obj['term']}  [{obj['count']}]")
            for semantic in top("Semantic")[:max_per_level]:
                lines.append(f"    {semantic['term']}  [{semantic['count']}]")
                for kind in top("Kind")[:max_per_level]:
                    lines.append(f"      {kind['term']}  [{kind['count']}]")
        lines.append("")
    return "\n".join(lines)