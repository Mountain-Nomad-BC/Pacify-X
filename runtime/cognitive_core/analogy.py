"""Structural analogy scoring for mechanism records, not mere prose similarity."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .common import jaccard, stable_hash, token_set

_FIELDS = {
    "entities": 1.0,
    "mechanisms": 3.0,
    "relations": 2.0,
    "inputs": 1.5,
    "outputs": 1.5,
    "invariants": 2.5,
    "failure_modes": 2.0,
    "tests": 1.5,
}


def _terms(value: object) -> set[str]:
    if isinstance(value, Mapping):
        values = [*value.keys(), *value.values()]
    elif isinstance(value, str):
        values = [value]
    else:
        values = list(value or ())
    result: set[str] = set()
    for item in values:
        result.update(token_set(str(item)))
    return result


def _triple(value: object) -> tuple[str, str, str] | None:
    if isinstance(value, Mapping):
        subject = value.get("subject", value.get("source", value.get("from")))
        relation = value.get("relation", value.get("predicate", value.get("type")))
        target = value.get("object", value.get("target", value.get("to")))
        if subject is None or relation is None or target is None:
            return None
        return str(subject), str(relation), str(target)
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) == 3
    ):
        return str(value[0]), str(value[1]), str(value[2])
    if isinstance(value, str):
        for separator in ("|", "->"):
            parts = [part.strip() for part in value.split(separator)]
            if len(parts) == 3 and all(parts):
                return parts[0], parts[1], parts[2]
    return None


def _multiset_jaccard(left: Counter[object], right: Counter[object]) -> float:
    keys = set(left) | set(right)
    union = sum(max(left[key], right[key]) for key in keys)
    return (
        0.0 if union == 0 else sum(min(left[key], right[key]) for key in keys) / union
    )


def _structure(record: Mapping[str, Any]) -> dict[str, Any]:
    triples = [
        parsed
        for value in record.get("relation_triples", ())
        if (parsed := _triple(value)) is not None
    ]
    degrees: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    relation_tokens: set[str] = set()
    relation_counts: Counter[str] = Counter()
    for subject, relation, target in triples:
        degrees[subject][1] += 1
        degrees[target][0] += 1
        normalized_relation = (
            " ".join(sorted(token_set(relation))) or relation.strip().lower()
        )
        relation_counts[normalized_relation] += 1
        relation_tokens.update(token_set(relation))
    degree_profile = Counter(
        (incoming, outgoing) for incoming, outgoing in degrees.values()
    )
    return {
        "triples": triples,
        "relation_tokens": relation_tokens,
        "relation_counts": relation_counts,
        "degree_profile": degree_profile,
        "node_count": len(degrees),
        "edge_count": len(triples),
    }


def _structural_similarity(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> tuple[float | None, dict[str, float]]:
    left_structure, right_structure = _structure(left), _structure(right)
    if not left_structure["triples"] and not right_structure["triples"]:
        return None, {}
    relation_label = jaccard(
        left_structure["relation_tokens"], right_structure["relation_tokens"]
    )
    relation_multiplicity = _multiset_jaccard(
        left_structure["relation_counts"], right_structure["relation_counts"]
    )
    topology = _multiset_jaccard(
        left_structure["degree_profile"], right_structure["degree_profile"]
    )
    edge_count_fit = 1.0 - abs(
        left_structure["edge_count"] - right_structure["edge_count"]
    ) / max(1, left_structure["edge_count"], right_structure["edge_count"])
    node_count_fit = 1.0 - abs(
        left_structure["node_count"] - right_structure["node_count"]
    ) / max(1, left_structure["node_count"], right_structure["node_count"])
    components = {
        "relation_label_overlap": relation_label,
        "relation_multiplicity_overlap": relation_multiplicity,
        "degree_topology_overlap": topology,
        "edge_count_fit": edge_count_fit,
        "node_count_fit": node_count_fit,
    }
    score = (
        0.30 * relation_label
        + 0.20 * relation_multiplicity
        + 0.30 * topology
        + 0.10 * edge_count_fit
        + 0.10 * node_count_fit
    )
    return score, components


def compare(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = payload.get("source", {})
    candidates = tuple(
        item for item in payload.get("candidates", ()) if isinstance(item, Mapping)
    )
    if not isinstance(source, Mapping) or not candidates:
        raise ValueError("source and candidates are required")
    identifiers = [str(item.get("id", "")).strip() for item in candidates]
    if any(not identifier for identifier in identifiers) or len(identifiers) != len(
        set(identifiers)
    ):
        raise ValueError("candidate IDs must be unique and non-empty")
    rows = []
    for candidate in candidates:
        weighted = 0.0
        weight_sum = 0.0
        field_scores = {}
        for field, weight in _FIELDS.items():
            left, right = (
                _terms(source.get(field, ())),
                _terms(candidate.get(field, ())),
            )
            if not left and not right:
                continue
            score = jaccard(left, right)
            weighted += weight * score
            weight_sum += weight
            field_scores[field] = score
        semantic_similarity = weighted / weight_sum if weight_sum else 0.0
        structural, structural_components = _structural_similarity(source, candidate)
        similarity = (
            semantic_similarity
            if structural is None
            else 0.55 * semantic_similarity + 0.45 * structural
        )
        rows.append(
            {
                "id": str(candidate["id"]),
                "similarity": similarity,
                "semantic_mechanism_score": semantic_similarity,
                "field_scores": field_scores,
                "structural_relation_score": structural,
                "structural_components": structural_components,
                "shared_invariants": sorted(
                    _terms(source.get("invariants", ()))
                    & _terms(candidate.get("invariants", ()))
                ),
                "transfer_warning": "Analogy proposes a transfer candidate; target constraints, causal assumptions, and counterexamples still require validation.",
            }
        )
    rows.sort(key=lambda item: (-item["similarity"], item["id"]))
    result = {
        "valid": True,
        "ranked_candidates": rows,
        "selected": rows[0]["id"] if rows else None,
    }
    return {**result, "result_sha256": stable_hash(result)}
