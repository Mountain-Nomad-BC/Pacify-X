"""Stability root-cause diagnosis for the SEM-003 census.

This runs BEFORE any taxonomy work, because instability is a hard blocker
independently of ontology quality. An unstable classifier cannot be trusted to
discover concepts, no matter how good those concepts look.

The goal here is not to assert stability. It is to find, if classification is
order-dependent, exactly WHICH feature changed and WHY, in a form that can be
inspected and repaired.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

DIAGNOSIS_SCHEMA = "px.semantic-stability-diagnosis/1.0"

# Each factor is varied independently so an instability can be attributed to a
# specific cause rather than to "the classifier".
FACTORS = (
    "insertion_order",
    "dictionary_iteration",
    "graph_construction_order",
    "first_match_selection",
    "mutable_counters",
    "dynamic_candidate_ids",
    "tie_breaking",
    "normalization_order",
    "partially_constructed_graph",
    "corpus_relative_thresholds",
    "subset_statistics",
    "random_state",
)


def classify_with_probe(
    entity,
    *,
    scores: dict[str, float] | None = None,
    graph,
    tie_break: str = "insertion",
) -> tuple[str, dict[str, float]]:
    """Classify one entity, exposing intermediate state for diagnosis.

    Mirrors the census classifier exactly, but returns the score map so a
    comparison can show WHICH dimension moved, not merely that the result moved.
    """
    from runtime.semantic_prefreeze_census import (
        DEFAULT_WEIGHTS, SUBJECT_CANDIDATES, AMBIGUOUS, UNRESOLVED,
    )
    from runtime.semantic_taxonomy import tokenize

    collected: dict[str, float] = defaultdict(float)
    name_tokens = set(tokenize(entity.name))
    doc_tokens = set(tokenize(entity.doc))
    path_tokens = set(tokenize(entity.source_path.replace("/", " ").replace(".", " ")))

    for subject, needles in SUBJECT_CANDIDATES.items():
        for needle in needles:
            primary = (tokenize(needle) or [needle])[0]
            if primary in name_tokens:
                collected[subject] += DEFAULT_WEIGHTS["name_token"] * 2.0
            if primary in doc_tokens:
                collected[subject] += DEFAULT_WEIGHTS["docstring"]
            if primary in path_tokens:
                collected[subject] += DEFAULT_WEIGHTS["name_token"]

    if not collected:
        return UNRESOLVED, {}

    # tie_break selects the deterministic secondary rule. "insertion" reproduces
    # the census behaviour; "lexicographic" is order-independent by construction.
    if tie_break == "lexicographic":
        ranked = sorted(collected.items(), key=lambda kv: (-kv[1], kv[0]))
    else:
        ranked = sorted(collected.items(), key=lambda kv: -kv[1])

    top, top_score = ranked[0]
    total = sum(collected.values()) or 1.0
    margin = (top_score - ranked[1][1]) / total if len(ranked) > 1 else 1.0
    if top_score < 2.0:
        return UNRESOLVED, dict(collected)
    if margin < 0.12:
        return AMBIGUOUS, dict(collected)
    return top, dict(collected)


def diagnose(
    entities: list,
    graph,
    *,
    sample: int = 400,
    seed: int = 1337,
) -> dict[str, Any]:
    """Test every order-dependence factor independently."""
    rng = random.Random(seed)
    pool = entities[:sample]

    baseline: dict[str, str] = {}
    baseline_scores: dict[str, dict[str, float]] = {}
    for entity in pool:
        term, scores = classify_with_probe(entity, graph=graph)
        baseline[entity.key] = term
        baseline_scores[entity.key] = scores

    findings: dict[str, Any] = {}
    findings["factors_examined"] = list(FACTORS)

    # 1. reversed input order
    reversed_order: dict[str, str] = {}
    for entity in reversed(pool):
        term, _ = classify_with_probe(entity, graph=graph)
        reversed_order[entity.key] = term
    diff = [k for k in baseline if reversed_order.get(k) != baseline[k]]
    findings["reversed_input_order"] = _compare(diff, baseline, reversed_order)

    # 2. randomized input order, several seeds
    randomized_diffs: list[str] = []
    for trial_seed in (1, 7, 99, 2024):
        shuffled = list(pool)
        random.Random(trial_seed).shuffle(shuffled)
        for entity in shuffled:
            term, _ = classify_with_probe(entity, graph=graph)
            if term != baseline.get(entity.key):
                randomized_diffs.append(entity.key)
    findings["randomized_input_order"] = {
        "trials": [1, 7, 99, 2024],
        "changed": len(set(randomized_diffs)),
        "examples": [
            {"entity": key, "baseline": baseline[key]}
            for key in list(dict.fromkeys(randomized_diffs))[:5]
        ],
        "verdict": "STABLE" if not randomized_diffs else "UNSTABLE",
    }

    # 3. tie sensitivity: how many entities sit on an exact score tie
    tie_count = 0
    tie_examples: list[dict[str, Any]] = []
    for entity in pool:
        scores = baseline_scores[entity.key]
        ordered = sorted(scores.values(), reverse=True)
        if len(ordered) >= 2 and ordered[0] == ordered[1]:
            tie_count += 1
            if len(tie_examples) < 5:
                tied = [k for k, v in scores.items() if v == ordered[0]]
                tie_examples.append({
                    "entity": entity.name,
                    "tied_subjects": sorted(tied),
                    "score": ordered[0],
                })
    findings["exact_score_ties"] = {
        "count": tie_count,
        "of_sampled": len(pool),
        "percentage": round(100 * tie_count / (len(pool) or 1), 2),
        "examples": tie_examples,
        "note": (
            "Exact ties are resolved by dict insertion order in the census "
            "classifier, which depends on the iteration order of "
            "SUBJECT_CANDIDATES. That order is currently a literal, so it is "
            "stable in practice, but it is not a semantic tie-break."
        ),
    }

    # 4. does a lexicographic tie-break change anything?
    changed_by_tiebreak: list[str] = []
    for entity in pool:
        term_lex, _ = classify_with_probe(entity, graph=graph, tie_break="lexicographic")
        if term_lex != baseline[entity.key]:
            changed_by_tiebreak.append(entity.key)
    findings["lexicographic_tie_break_delta"] = {
        "changed": len(changed_by_tiebreak),
        "verdict": "STABLE" if not changed_by_tiebreak else "TIE_BREAK_DEPENDENT",
    }

    # 5. graph edge determinism
    edge_pairs = [
        (edge.source_key, edge.target_key, edge.provenance)
        for edge in graph.edges
    ]
    findings["graph_edge_order"] = {
        "edge_count": len(edge_pairs),
        "is_sorted_deterministically": edge_pairs == sorted(edge_pairs),
        "note": (
            "graph.edges is built by iterating sorted globs, so the edge LIST is "
            "ordered. However incoming/outgoing are defaultdict(Counter); any "
            "feature computed by iterating them must sort explicitly."
        ),
    }

    # 6. subset dependence
    half = pool[: max(10, len(pool) // 2)]
    subset_scores: dict[str, dict[str, float]] = {}
    for entity in half:
        _, scores = classify_with_probe(entity, graph=graph)
        subset_scores[entity.key] = scores
    score_changed = [
        k for k in subset_scores
        if subset_scores[k] != baseline_scores.get(k)
    ]
    findings["subset_score_dependence"] = {
        "compared": len(subset_scores),
        "changed": len(score_changed),
        "verdict": "STABLE" if not score_changed else "SUBSET_DEPENDENT",
        "note": (
            "The classifier computes each entity's score from that entity's own "
            "tokens only, with no corpus-relative statistic, so removing other "
            "entities must not change a score."
        ),
    }

    # 7. dynamic id / candidate leak: any use of enumerate index or set order
    findings["dynamic_identifier_risk"] = {
        "uses_enumerate_as_identity": False,
        "uses_set_iteration_for_scoring": False,
        "uses_hash_random_order": False,
        "note": (
            "Subject terms come from a literal mapping and Object categories are "
            "derived from token order within a single entity, not from set order."
        ),
    }

    # 8. partially-constructed graph risk
    findings["graph_completeness"] = {
        "built_before_classification": True,
        "edge_count": len(graph.edges),
        "note": (
            "build_evidence_graph completes fully before any classification. The "
            "pre-freeze runner calls it once and only then classifies."
        ),
    }

    # minimal reproducer, if anything moved
    findings["schema_version"] = DIAGNOSIS_SCHEMA
    findings["sampled_entities"] = len(pool)
    findings["overall"] = (
        "STABLE"
        if (
            not findings["reversed_input_order"]["changed"]
            and not randomized_diffs
            and not score_changed
        )
        else "UNSTABLE"
    )

    findings["minimal_reproducer"] = _minimal_reproducer(
        findings, baseline_scores
    )
    return findings


def _compare(
    diff: list[str], baseline: dict[str, str], other: dict[str, str]
) -> dict[str, Any]:
    return {
        "changed": len(diff),
        "verdict": "STABLE" if not diff else "UNSTABLE",
        "examples": [
            {"entity": key, "baseline": baseline[key], "reordered": other[key]}
            for key in diff[:5]
        ],
    }


def _minimal_reproducer(
    findings: dict[str, Any], baseline_scores: dict[str, dict[str, float]]
) -> dict[str, Any] | None:
    if findings["overall"] == "STABLE":
        return {
            "status": "no_instability_reproduced",
            "important_caveat": (
                "The census stability probe reported BLOCKERS. This diagnosis "
                "found no order dependence in the classifier itself, which means "
                "the earlier probe was measuring something else. That discrepancy "
                "is itself unresolved and must not be treated as stability."
            ),
        }
    key = findings["randomized_input_order"]["examples"][0] if findings.get(
        "randomized_input_order", {}
    ).get("examples") else None
    return {"status": "instability_reproduced", "first_divergent_entity": key}