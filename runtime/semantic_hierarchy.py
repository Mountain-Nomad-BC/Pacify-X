"""Hierarchical ontology construction and capacity analysis for SEM-003.

Builds ``Subject -> Object -> Semantic -> Kind`` with each level conditioned on
its parent, then MEASURES whether the four-segment layout fits, comparing a
global registry model against a namespace-local one. Nothing is frozen and no
address is allocated.

Two candidate models, compared empirically
-------------------------------------------
**Global registry.** Every Object ID means the same thing under every Subject.
One shared vocabulary, so an Object table of size N must fit one byte for all
Subjects.

**Namespace-local registry.** An Object ID is interpreted as ``(Subject,Object)``.
``37.112`` means Object 112 *under Subject 37*, so each Subject may have its own
Object table and the byte only has to hold the largest one. Semantics can follow
the same rule under ``(Subject,Object)``.

The local model trades a global meaning for capacity: two Objects with the same
number under different Subjects are unrelated. Whether that trade is acceptable
depends on whether routing is ever done across Subjects, which is exactly why
this census reports both rather than choosing.

Compression, not renaming
-------------------------
Object is a CATEGORY within a Subject, never an individual entity. If the tree
ever mirrors a directory listing or a symbol table, the classifier has descended
to naming rather than meaning, and the report says so.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from runtime.semantic_evidence import (
    AMBIGUOUS,
    NOVEL_TERM,
    OUTCOMES,
    RESOLVED,
    UNRESOLVED,
    Observation,
)
from runtime.semantic_normalize import (
    NormalizationLedger,
    canonicalize_tokens,
    split_identifier,
)

REPORT_SCHEMA = "px.semantic-census-report/2.0"
SEGMENT_CAPACITY = 254

# Candidate semantic DOMAINS. Each is evidence-backed by the corpus, not a
# directory listing: the resolver scores domains against observation tokens and
# accepts only those the corpus actually supports.
DOMAIN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "verification": ("verify", "validate", "valid", "check", "assert", "prove", "attest", "audit", "inspect", "review", "assur", "certif", "gate"),
    "identity": ("identity", "canonical", "fingerprint", "hash", "digest", "provenance", "revision", "currentness"),
    "memory": ("memory", "memor", "recall", "context", "librarian", "retriev", "knowledge", "corpus"),
    "learning": ("learn", "promot", "adapt", "evolv", "skill", "cognitive", "metacognitive"),
    "governance": ("govern", "policy", "polic", "authoriz", "approv", "admit", "admiss", "grant", "contract", "ledger", "card", "receipt"),
    "routing": ("route", "routing", "dispatch", "select", "choose", "placement", "provider", "gateway", "adapter"),
    "orchestration": ("orchestrat", "workflow", "schedul", "queue", "pipeline", "control", "controller", "execution", "exec"),
    "diagnostics": ("diagnos", "trace", "log", "metric", "report", "monitor", "health", "status", "telemetry"),
    "retrieval": ("retriev", "query", "search", "index", "lookup", "find", "inventory", "discover"),
    "installation": ("install", "packag", "deploy", "distribut", "provision", "environment", "bootstrap"),
    "release": ("release", "certif", "campaign", "publish", "version", "migration", "promot"),
    "capability": ("capability", "capabilit", "fabric", "integration", "bridge", "surface"),
    "representation": ("serial", "render", "encode", "decode", "format", "schema", "projection", "media"),
    "code": ("source", "symbol", "function", "class", "module", "lsp", "ast", "syntax", "parse"),
    "structure": ("structur", "schema", "model", "entity", "relation", "graph", "tree", "node"),
}

# Words that indicate the subject is a CONTAINER rather than a concept.
_CONTAINER_HINTS = {"runtime", "extension", "pacify", "px", "src", "lib", "core", "main", "index", "init", "util", "utilities", "common", "shared", "base"}


def _tokens(text: str) -> list[str]:
    return split_identifier(text)


@dataclass
class Node:
    term: str
    parent: str | None
    depth: int
    count: int = 0
    members: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.term


@dataclass
class Assignment:
    key: str
    subject: str
    obj: str
    semantic: str
    kind: str
    outcome: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def address(self) -> tuple[str, str, str, str]:
        return (self.subject, self.obj, self.semantic, self.kind)


class OntologyBuilder:
    """Builds the proposed hierarchy. Advisory only."""

    def __init__(self, *, min_domain_score: float = 0.25) -> None:
        self.min_domain_score = min_domain_score
        self.ledger = NormalizationLedger()

    # -- subject ------------------------------------------------------------

    def assign_subject(self, observation: Observation) -> tuple[str, float, dict[str, float]]:
        """Score candidate semantic domains against an observation's evidence.

        Deliberately NOT a path lookup. A path component such as ``runtime`` is
        a container, not a domain, and is explicitly excluded from scoring so
        the observed 88 percent runtime concentration cannot become the answer.
        """
        tokens = set(_tokens(observation.symbol))
        tokens.update(_tokens(" ".join(observation.base_names)))
        tokens.update(_tokens(observation.doc[:160]))
        path_tokens = set(_tokens(observation.path))
        tokens.update(t for t in path_tokens if t not in _CONTAINER_HINTS)

        scores: dict[str, float] = {}
        for domain, cues in DOMAIN_CANDIDATES.items():
            score = 0.0
            for cue in cues:
                if cue in tokens:
                    score += 3.0
                elif any(token.startswith(cue) for token in tokens):
                    score += 1.5
                elif any(cue in token for token in path_tokens):
                    score += 1.0
            if score:
                scores[domain] = score
        if not scores:
            return UNRESOLVED, 0.0, {}
        total = sum(scores.values())
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        top, top_score = ranked[0]
        confidence = top_score / total if total else 0.0
        if top_score < 1.0:
            return UNRESOLVED, round(confidence, 3), dict(ranked[:3])
        return top, round(confidence, 3), dict(ranked[:3])

    # -- object -------------------------------------------------------------

    def assign_object(self, observation: Observation, subject: str) -> tuple[str, float]:
        """Object is a CATEGORY within the Subject, never an individual entity.

        Categories are the canonicalized CONCEPT tokens of the observation after
        container and location noise is removed. If the resulting category is
        just the symbol name, the classification is rejected as renaming rather
        than compressing meaning.
        """
        raw = _tokens(observation.symbol)
        concepts = canonicalize_tokens(
            [token for token in raw if token not in _CONTAINER_HINTS], self.ledger
        )
        concepts = [c for c in concepts if c not in _CONTAINER_HINTS]
        if not concepts:
            return NOVEL_TERM, 0.0
        # The leading concept is usually the verb; the category is the domain noun.
        category = concepts[-1]
        if category == raw[-1] and len(raw) > 2:
            # Degenerate case: the "category" is just the trailing symbol token.
            category = concepts[0] if len(concepts) > 1 else category
        confidence = 0.6 if len(concepts) > 1 else 0.35
        return category, confidence

    # -- semantic -----------------------------------------------------------

    def assign_semantic(self, observation: Observation) -> tuple[str, float]:
        """The PX functional role, canonicalized from verb families."""
        raw = _tokens(observation.symbol)
        if not raw:
            return NOVEL_TERM, 0.0
        concepts = canonicalize_tokens(raw, self.ledger)
        functional = [
            c for c in concepts
            if c in {
                "validation", "verification", "retrieval", "reading", "loading",
                "production", "generation", "construction", "publication",
                "governance", "authorization", "approval", "admission",
                "identity", "hashing", "canonicalization", "execution",
                "dispatch", "invocation", "orchestration", "scheduling",
                "queueing", "routing", "delegation", "recording",
                "persistence", "writing", "commitment", "append", "logging",
                "lifecycle", "initialization", "closure", "finalization",
                "retirement", "reclamation", "compaction", "rotation",
                "learning", "promotion", "adaptation", "evolution", "memory",
                "installation", "packaging", "deployment", "distribution",
                "dependency", "resolution", "binding", "linking",
                "classification", "inference", "derivation", "computation",
                "projection", "transformation", "summary", "explanation",
                "diagnostics", "tracing", "measurement", "metrics",
                "reporting", "comparison", "merging", "conflict",
                "reconciliation", "state", "snapshot", "export", "freezing",
            }
        ]
        if not functional:
            return NOVEL_TERM, 0.0
        return functional[0], 0.7 if len(functional) == 1 else 0.55

    # -- kind ---------------------------------------------------------------

    def assign_kind(self, observation: Observation) -> str:
        return observation.kind


def build(
    observations: list[Observation],
    *,
    min_domain_score: float = 0.25,
) -> tuple[list[Assignment], dict[str, Any]]:
    builder = OntologyBuilder(min_domain_score=min_domain_score)
    assignments: list[Assignment] = []
    for observation in observations:
        subject, subject_confidence, rivals = builder.assign_subject(observation)
        obj, object_confidence = (
            (UNRESOLVED, 0.0) if subject in {UNRESOLVED, NOVEL_TERM, AMBIGUOUS}
            else builder.assign_object(observation, subject)
        )
        semantic, semantic_confidence = (
            (UNRESOLVED, 0.0) if subject in {UNRESOLVED, NOVEL_TERM, AMBIGUOUS}
            else builder.assign_semantic(observation)
        )
        kind = builder.assign_kind(observation)
        unresolved = [
            name for name, value in (
                ("Subject", subject), ("Object", obj), ("Semantic", semantic)
            ) if value in {UNRESOLVED, NOVEL_TERM}
        ]
        if not unresolved:
            outcome = RESOLVED
        elif subject in {UNRESOLVED, AMBIGUOUS}:
            outcome = UNRESOLVED if len(unresolved) > 1 else NOVEL_TERM
        else:
            outcome = AMBIGUOUS if len(unresolved) > 1 else NOVEL_TERM
        confidence = round(
            (subject_confidence + object_confidence + semantic_confidence) / 3.0, 3
        )
        assignments.append(
            Assignment(
                key=observation.key, subject=subject, obj=obj, semantic=semantic,
                kind=kind, outcome=outcome, confidence=confidence,
                evidence={
                    "surface": observation.surface,
                    "path": observation.path,
                    "symbol": observation.symbol,
                    "channels": list(observation.channels),
                    "domain_rivals": sorted(rivals.items(), key=lambda kv: -kv[1])[:3],
                },
            )
        )
    meta = {"normalization_ledger": builder.ledger}
    return assignments, meta