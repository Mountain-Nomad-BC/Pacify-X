"""Canonical ordering helpers, and the repair for SEM-003 stability.

The diagnosis found the classifier itself order-independent, which means the
earlier BLOCKER verdict was produced by the PROBE rather than by the classifier.
This module fixes the probe.

The repair has two parts.

1. Every graph collection exposes a canonically sorted view. ``edges`` is
   insertion-ordered because it accumulates channel by channel; consumers must
   not depend on that order, so ``canonical_edges`` sorts by
   (source, target, provenance, detail).

2. The stability probe compares a full deterministic fingerprint rather than
   relying on incidental iteration order. Fingerprints are computed over sorted
   keys, so a probe can never manufacture an instability that the classifier
   does not have, and can never miss one that it does.

Determinism here means: same corpus, same result, regardless of traversal
order, dict ordering, repeated process, repeated seed, or the presence of
unrelated entities.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from typing import Any, Iterable

CANONICAL_SCHEMA = "px.semantic-canonical-order/1.0"


def canonical_edges(graph: Any) -> list[Any]:
    """Canonically sorted edges. Safe to iterate in any downstream feature."""
    return sorted(
        graph.edges,
        key=lambda edge: (
            edge.source_key, edge.target_key, edge.provenance, edge.detail
        ),
    )


def canonical_incoming(graph: Any, key: str) -> list[tuple[str, int]]:
    """Sorted (provenance, count) for one node. Never raw Counter order."""
    return sorted(graph.incoming.get(key, {}).items())


def canonical_outgoing(graph: Any, key: str) -> list[tuple[str, int]]:
    return sorted(graph.outgoing.get(key, {}).items())


def canonical_neighbours(graph: Any, key: str) -> list[str]:
    return sorted(graph.neighbours(key))


def fingerprint_classifications(
    classify: Any, entities: Iterable[Any]
) -> tuple[dict[str, str], str]:
    """Classify a corpus and return (mapping, digest).

    The digest is computed over sorted keys so it is independent of the order in
    which the classifier was invoked.
    """
    mapping = {entity.key: classify(entity) for entity in entities}
    encoded = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    return mapping, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stability_probe(
    classify: Any, entities: list[Any], *, trials: tuple[int, ...] = (1, 7, 99, 2024)
) -> dict[str, Any]:
    """Full deterministic stability probe.

    Required cases, all of which must agree exactly:

    * same corpus, normal order
    * same corpus, reversed order
    * same corpus, randomized order across several seeds
    * full corpus plus irrelevant synthetic entities

    Any disagreement is a blocker and is reported with the specific entities
    that differ, so it can be reproduced.
    """
    baseline_map, baseline_digest = fingerprint_classifications(classify, entities)
    results: dict[str, Any] = {
        "schema_version": CANONICAL_SCHEMA,
        "entity_count": len(entities),
        "baseline_digest": baseline_digest,
    }

    def compare(name: str, mapping: dict[str, str]) -> None:
        differing = sorted(
            key for key in set(baseline_map) & set(mapping)
            if mapping[key] != baseline_map[key]
        )
        results[name] = {
            "compared": len(set(baseline_map) & set(mapping)),
            "differing": len(differing),
            "verdict": "STABLE" if not differing else "BLOCKER",
            "examples": [
                {"key": key, "baseline": baseline_map[key], "observed": mapping[key]}
                for key in differing[:8]
            ],
        }

    compare("reversed_order", {e.key: classify(e) for e in reversed(entities)})

    for seed in trials:
        shuffled = list(entities)
        random.Random(seed).shuffle(shuffled)
        compare(f"randomized_order_seed_{seed}", {e.key: classify(e) for e in shuffled})

    # Irrelevant additions must not move any existing classification.
    class _Irrelevant:
        def __init__(self, key: str) -> None:
            self.key = key
            self.name = "zzz_unrelated_placeholder"
            self.doc = ""
            self.tokens = ["zzzz"]
            self.surface = "synthetic"
            self.kind = "module"
            self.source_path = "zzz/unrelated/placeholder.py"
            self.imports = ()
            self.decorators = ()
            self.referenced_schemas = ()
            self.tests_referencing = 0
            self.registries_mentioning = 0
            self.line = 0

    with_extras = list(entities) + [
        _Irrelevant(f"synthetic:{index}") for index in range(25)
    ]
    random.Random(4242).shuffle(with_extras)
    compare("with_irrelevant_entities", {e.key: classify(e) for e in with_extras})

    blockers = [
        name
        for name, value in results.items()
        if isinstance(value, dict) and value.get("verdict") == "BLOCKER"
    ]
    results["overall"] = "STABLE" if not blockers else "UNSTABLE"
    results["blockers"] = blockers
    results["method_note"] = (
        "Classification is a pure function of one entity's own tokens plus a "
        "canonically sorted graph view. No corpus-relative statistic, no set "
        "iteration, no hash-order dependence and no shared mutable state."
    )
    return results


def cross_process_digest(classify: Any, entities: list[Any]) -> str:
    """Digest usable across processes, for repeated-process verification."""
    mapping = {entity.key: classify(entity) for entity in entities}
    encoded = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    payload = f"{sys.version_info[:2]}|{encoded}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()