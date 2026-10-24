"""Canonicalization of raw tokens into candidate taxonomy terms.

The first census reported verb ROOTS (``validat``, ``retriev``, ``verif``) as
if they were terms. They are extraction artifacts. Cardinality measured over
roots over-counts: ``validate``, ``validates``, ``validation`` and
``validator`` are four raw tokens describing one concept.

This module canonicalizes before counting, and RETAINS the raw to canonical
mapping so every merge is auditable rather than silent.

Three kinds of collapse are applied, in order:

1. **Symbol-suffix stripping.** ``_ledger_head_id``, ``_policy_sha``,
   ``_snapshot_bytes`` collapse to their stem. A suffix is only stripped when
   what remains is still a usable concept; ``id`` alone is not a concept.
2. **Morphological lemma.** Plurals and nominalizations collapse onto a single
   canonical form, with an explicit verb/noun distinction preserved where the
   two are genuinely different concepts (``validation`` vs ``verification`` are
   NOT merged).
3. **Concept mapping.** An explicit, reviewable table maps remaining roots onto
   candidate ontology terms. This table is a PROPOSAL, reported with counts so a
   human can reject any mapping.

The goal is that the taxonomy compresses MEANING. If canonicalization ever
reduces two genuinely different concepts to one term, that is a defect, and the
collision is visible in the ledger rather than absorbed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Symbol-specific suffixes that decorate a stem without changing its meaning.
# Order matters: longer suffixes are stripped first.
_DECORATIVE_SUFFIXES = (
    "_sha256", "_sha", "_bytes", "_records", "_record", "_manifest",
    "_payload", "_count", "_counts", "_index", "_entries", "_entry",
    "_status", "_state", "_stamp", "_size", "_len", "_list", "_map",
    "_set", "_ids", "_id", "_by", "_to", "_from", "_at", "_in",
    "_path", "_dir", "_file", "_name", "_names", "_key", "_keys",
    "_value", "_values", "_ref", "_refs", "_handle", "_ref_path",
    "_spec", "_version", "_hash", "_json", "_text", "_path_hash",
)

_TRAILING_DECORATIVE = (
    "sha256", "sha", "bytes", "count", "path", "name", "key", "id",
    "ids", "paths", "names", "manifest", "payload", "records", "index",
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*")

# Explicit root -> candidate ontology term. A PROPOSAL for human review, not a
# frozen legend. Kept small and legible on purpose: a large generated table would
# hide exactly the merge decisions that need review.
ROOT_TO_CONCEPT: dict[str, str] = {
    # verification family
    "validat": "validation", "valid": "validation", "validator": "validation",
    "verif": "verification", "verify": "verification", "verified": "verification",
    "check": "verification", "assert": "verification", "prove": "verification",
    "attest": "verification", "audit": "verification", "inspect": "verification",
    # retrieval family
    "retriev": "retrieval", "retrieve": "retrieval", "query": "retrieval",
    "search": "retrieval", "find": "retrieval", "lookup": "retrieval",
    "load": "loading", "read": "reading", "fetch": "retrieval",
    # production family
    "produc": "production", "produce": "production", "generat": "generation",
    "generate": "generation", "emit": "production", "publish": "publication",
    "creat": "creation", "create": "creation", "build": "construction",
    "render": "rendering", "serial": "serialization", "encode": "encoding",
    "decode": "decoding", "deserial": "deserialization",
    # governance family
    "govern": "governance", "authoriz": "authorization",
    "authorise": "authorization", "authoriz": "authorization",
    "approve": "approval", "approv": "approval", "deny": "authorization",
    "admit": "admission", "admiss": "admission", "grant": "admission",
    "policy": "policy", "policies": "policy", "rule": "policy",
    # identity family
    "ident": "identity", "identity": "identity", "fingerprint": "identity",
    "hash": "hashing", "canonical": "canonicalization", "canonicalize": "canonicalization",
    # execution family
    "execut": "execution", "execute": "execution", "dispatch": "dispatch",
    "run": "execution", "invoke": "invocation", "call": "invocation",
    "spawn": "execution", "launch": "execution", "orchestrat": "orchestration",
    "schedul": "scheduling", "queue": "queueing", "route": "routing",
    "routing": "routing", "delegat": "delegation", "dispatch_route": "routing",
    # persistence family
    "record": "recording", "persist": "persistence", "store": "persistence",
    "save": "persistence", "writ": "writing", "commit": "commitment",
    "append": "append", "ledger": "ledger", "log": "logging", "journal": "ledger",
    # lifecycle family
    "lifecycle": "lifecycle", "init": "initialization",
    "initialize": "initialization", "initialis": "initialization",
    "start": "lifecycle", "stop": "lifecycle", "shutdown": "lifecycle",
    "clos": "closure", "close": "closure", "finali": "finalization",
    "retire": "retirement", "reclaim": "reclamation", "prune": "reclamation",
    "clean": "reclamation", "compact": "compaction", "coalesc": "compaction",
    "rotat": "rotation", "prune": "reclamation",
    # learning family
    "learn": "learning", "learn_from": "learning", "promot": "promotion",
    "adapt": "adaptation", "evolv": "evolution", "memor": "memory",
    "remember": "memory", "forget": "memory",
    # installation family
    "install": "installation", "packag": "packaging", "package": "packaging",
    "deploy": "deployment", "distribut": "distribution", "publish_artifact": "publication",
    # relation family
    "depend": "dependency", "import": "dependency", "resolve": "resolution",
    "bind": "binding", "link": "linking", "relat": "relation",
    "extend": "inheritance", "inherit": "inheritance", "subclass": "inheritance",
    # analysis family
    "classif": "classification", "infer": "inference", "derive": "derivation",
    "comput": "computation", "calculat": "computation", "project": "projection",
    "transform": "transformation", "convert": "transformation",
    "summar": "summary", "explain": "explanation", "diagnos": "diagnostics",
    "trace": "tracing", "measure": "measurement", "metric": "metrics",
    "count": "measurement", "report": "reporting",
    # comparison family
    "compare": "comparison", "diff": "comparison", "merge": "merging",
    "conflict": "conflict", "reconcil": "reconciliation",
    # state family
    "state": "state", "snapshot": "snapshot", "export": "export",
    "import_state": "state", "freeze": "freezing",
}

_PLURAL_RULES = (
    ("ies", "y"),
    ("sses", "ss"),
    ("xes", "x"),
    ("ches", "ch"),
    ("shes", "sh"),
    ("ses", "s"),
    ("s", ""),
)


@dataclass
class NormalizationLedger:
    """Auditable record of every raw token and where it landed."""

    canonical: dict[str, str] = field(default_factory=dict)
    strip_kind: dict[str, str] = field(default_factory=dict)
    mapping: dict[str, str] = field(default_factory=dict)

    def record(self, raw: str, canonical: str, *, strip: str = "", mapping: str = "") -> None:
        self.canonical[raw] = canonical
        if strip:
            self.strip_kind[raw] = strip
        if mapping:
            self.mapping[raw] = mapping

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "px.taxonomy-normalization/1.0",
            "raw_token_count": len(self.canonical),
            "distinct_canonical_count": len(set(self.canonical.values())),
            "compression_ratio": (
                round(len(self.canonical) / len(set(self.canonical.values())), 3)
                if self.canonical else 0.0
            ),
            "decorative_suffix_strips": dict(sorted(self.strip_kind.items())),
            "concept_mappings": dict(sorted(self.mapping.items())),
            "raw_to_canonical": dict(sorted(self.canonical.items())),
        }


def split_identifier(identifier: str) -> list[str]:
    """Split snake_case, camelCase and dotted names into lowercase tokens."""
    spaced = _CAMEL.sub(" ", identifier.replace("_", " ").replace("-", " ").replace(".", " "))
    return [token.lower() for token in _TOKEN.findall(spaced)]


def strip_decorative(tokens: list[str], ledger: NormalizationLedger, raw: str) -> list[str]:
    """Remove trailing decorations that do not change meaning."""
    result = list(tokens)
    while len(result) > 1:
        last = result[-1]
        if last in _TRAILING_DECORATIVE:
            ledger.strip_kind[raw] = last
            result = result[:-1]
            continue
        break
    return result


def singularize(token: str) -> str:
    for suffix, replacement in _PLURAL_RULES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)] + replacement
    return token


def canonicalize_identifier(
    identifier: str, ledger: NormalizationLedger | None = None
) -> tuple[str, list[str]]:
    """Canonicalize one identifier into a candidate taxonomy term.

    Returns the canonical term and the raw tokens it came from, so the caller can
    decide whether to treat it as a taxonomy term or as residual noise.
    """
    ledger = ledger if ledger is not None else NormalizationLedger()
    raw_tokens = split_identifier(identifier)
    stripped = strip_decorative(raw_tokens, ledger, identifier)
    if not stripped:
        return "", []

    head = stripped[0]
    tail = singularize("".join(stripped[-2:])) if len(stripped) >= 2 else singularize(stripped[-1])

    concept = ROOT_TO_CONCEPT.get(head)
    if concept is None:
        concept = ROOT_TO_CONCEPT.get(singularize(head))
    if concept is not None:
        ledger.record(identifier, concept, mapping=head)
        return concept, stripped

    # Not a known verb root: treat the trailing noun as the concept.
    candidate = singularize(stripped[-1])
    ledger.record(identifier, candidate, strip=ledger.strip_kind.get(identifier, ""))
    return candidate, stripped


def canonicalize_tokens(
    tokens: Iterable[str], ledger: NormalizationLedger | None = None
) -> list[str]:
    """Canonicalize a bag of raw tokens, preserving first-seen order."""
    ledger = ledger if ledger is not None else NormalizationLedger()
    out: list[str] = []
    for token in tokens:
        concept = ROOT_TO_CONCEPT.get(token)
        if concept is None:
            concept = ROOT_TO_CONCEPT.get(singularize(token))
        if concept is None:
            concept = singularize(token)
        ledger.record(token, concept, mapping=token if concept != token else "")
        if concept and concept not in out:
            out.append(concept)
    return out