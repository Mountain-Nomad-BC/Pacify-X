"""Semantic taxonomy discovery - full governed corpus census for SEM-003.

This module discovers PX's ontology. It does not freeze a legend, allocate an
address, or migrate anything.

Design constraints this implements
---------------------------------
``Subject.Object.Semantic.Kind`` where every byte carries useful meaning.

* **Subject** is a semantic domain, not a path. Paths are EVIDENCE, never
  authority, because semantic identity must survive artifact relocation.
* **Object** is a CATEGORY inside a Subject, never an individual entity. An
  earlier pass that treated symbol head-nouns as Objects produced 1,089 terms
  and merely recreated a directory tree numerically. Individual entities stay
  distinguished by ``entity_id``.
* **Semantic** is the entity's function in the PX ontology, canonicalized so
  ``validate``/``validates``/``validation`` collapse to one term with the raw
  form retained as evidence.
* **Kind** is the strongest candidate for a genuinely global vocabulary.

Hierarchy is built recursively: Objects are discovered WITHIN a Subject, and
Semantics WITHIN a (Subject, Object). Whether Object and Semantic identifiers
should be global or namespace-local is compared empirically rather than
assumed.

Uncertainty is preserved. RESOLVED, AMBIGUOUS, NOVEL_TERM and UNRESOLVED are
all reported, and nothing is invented to raise the RESOLVED percentage.

Many-to-one addressing is expected, not exceptional. The census reports bucket
populations because a compact semantic address identifies a routing BUCKET,
while ``entity_id`` identifies the exact entity.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

TAXONOMY_SCHEMA = "px.semantic-taxonomy-census/2.0"

RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
AMBIGUOUS = "AMBIGUOUS"
NOVEL_TERM = "NOVEL_TERM"
OUTCOMES = (RESOLVED, UNRESOLVED, AMBIGUOUS, NOVEL_TERM)

_TOKEN = re.compile(r"[a-z][a-z0-9]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# ---------------------------------------------------------------------------
# Canonicalization ledger.
#
# Extraction produces verb ROOTS such as ``validat`` or ``retriev``. Those are
# artifacts, not taxonomy terms. Each root maps to ONE canonical term, and the
# raw forms are retained so the normalization is auditable.
# ---------------------------------------------------------------------------
CANONICAL_SEMANTIC_TERMS: dict[str, str] = {
    "validat": "validation", "verif": "verification", "authent": "authentication",
    "authoriz": "authorization", "approv": "approval", "deni": "denial",
    "govern": "governance", "polic": "policy", "complian": "compliance",
    "route": "routing", "dispatch": "dispatch", "execut": "execution",
    "invok": "invocation", "call": "invocation", "schedul": "scheduling",
    "orchestrat": "orchestration", "coordin": "coordination",
    "produc": "production", "generat": "generation", "creat": "creation",
    "build": "construction", "emitt": "emission", "publish": "publication",
    "declar": "declaration", "defin": "definition", "specif": "specification",
    "consum": "consumption", "read": "reading", "load": "loading",
    "fetch": "retrieval", "retriev": "retrieval", "query": "query",
    "search": "query", "resolv": "resolution", "lookup": "resolution",
    "record": "recording", "persist": "persistence", "stor": "storage",
    "log": "recording", "track": "tracking", "receipt": "recording",
    "index": "indexing", "cach": "caching", "snapshot": "snapshot",
    "promot": "promotion", "learn": "learning", "adapt": "adaptation",
    "evolv": "evolution", "train": "training", "infer": "inference",
    "depend": "dependency", "import": "import", "bind": "binding",
    "link": "binding", "connect": "connection", "attach": "attachment",
    "project": "projection", "deriv": "derivation", "comput": "computation",
    "calcul": "computation", "classif": "classification", "categor": "classification",
    "cluster": "classification", "aggregat": "aggregation", "summar": "summary",
    "reclaim": "reclamation", "clean": "reclamation", "prun": "reclamation",
    "compact": "compaction", "coalesc": "coalescing", "dedup": "deduplication",
    "install": "installation", "packag": "packaging", "deploy": "deployment",
    "distribut": "distribution", "upgrad": "upgrade", "migrat": "migration",
    "compar": "comparison", "diff": "comparison", "match": "comparison",
    "merge": "merging", "conflict": "conflicting", "reconcil": "reconciliation",
    "diagnos": "diagnostics", "inspect": "inspection", "explain": "explanation",
    "trace": "tracing", "audit": "audit", "monitor": "monitoring",
    "supervis": "supervision", "watch": "monitoring", "observ": "observation",
    "serial": "serialization", "deserial": "serialization", "encod": "encoding",
    "decod": "decoding", "render": "rendering", "translat": "translation",
    "convert": "conversion", "format": "formatting", "pars": "parsing",
    "open": "opening", "clos": "closure", "shutdown": "shutdown",
    "start": "lifecycle", "stop": "lifecycle", "restart": "lifecycle",
    "lifecycle": "lifecycle", "init": "initialization", "finali": "finalization",
    "reclaim_evidence": "reclamation",
    "report": "reporting", "emit": "emission", "notify": "notification",
    "approv": "approval", "request": "request", "respond": "response",
    "fail": "failure", "error": "failure", "exception": "failure",
    "recover": "recovery", "retry": "recovery", "rollback": "reversal",
    "freez": "freezing", "freeze": "freezing", "seal": "sealing",
    "sign": "signing", "verif_": "verification", "integr": "integrity",
}

# Alias folding applied after root canonicalization.
_CANONICAL_ALIASES: dict[str, str] = {
    "validation": "validation", "validations": "validation", "validator": "validation",
    "verification": "verification", "verify": "verification", "verifies": "verification",
    "retrieval": "retrieval", "retrieve": "retrieval", "retrieves": "retrieval",
    "execution": "execution", "execute": "execution", "executes": "execution",
    "generation": "generation", "generate": "generation", "generates": "generation",
    "resolution": "resolution", "resolve": "resolution", "resolves": "resolution",
    "recording": "recording", "record": "recording", "records": "recording",
    "projection": "projection", "project": "projection", "projects": "projection",
    "classification": "classification", "classify": "classification",
    "reclamation": "reclamation", "reclaim": "reclamation",
    "compaction": "compaction", "compact": "compaction",
    "computation": "computation", "compute": "computation",
    "lifecycle": "lifecycle", "initialization": "initialization", "init": "initialization",
    "termination": "lifecycle", "teardown": "lifecycle",
}

# Subject domain candidates. Each is EVIDENCE-scored against the corpus; a
# candidate that the corpus does not support is reported as unsupported rather
# than quietly retained.
SUBJECT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "runtime": ("runtime",),
    "governance": ("governance", "campaign", "registry", "ledger", "policy", "policies"),
    "verification": ("verification", "verify", "assurance", "test", "tests", "gate"),
    "memory": ("memory", "persistent_memory", "remember"),
    "learning": ("learning", "metacognitive", "evolve", "promot", "train"),
    "cognitive": ("cognitive", "reasoning", "cognitive_core"),
    "code": ("semantic_code", "code", "symbol", "ast", "refactor"),
    "lsp": ("lsp", "language_server"),
    "integration": ("integration", "integrations", "bridge", "adapter"),
    "capability": ("capability", "capabilities", "external_capabilities"),
    "routing": ("routing", "hardware", "placement", "device"),
    "orchestration": ("orchestration", "orchestrations", "workflow", "mode"),
    "retrieval": ("retrieval", "retrieve", "search", "index"),
    "evidence": ("evidence", "receipt", "proof", "attest"),
    "release": ("release", "package", "install", "certif"),
    "security": ("security", "auth", "trust", "sanit"),
    "scheduling": ("scheduling", "schedule", "queue"),
    "skills": ("skill", "skills", "skill_package"),
    "agents": ("agent", "agents", "orchestrat"),
    "research": ("research", "research_ops", "nsai"),
    "diagnostics": ("diagnostic", "diagnostics", "telemetry", "trace"),
}

# Kind is the global vocabulary. Keys are canonical, values are descriptions.
KIND_VOCABULARY: dict[str, str] = {
    "module": "a source module",
    "function": "a callable",
    "class": "a type or class declaration",
    "contract": "a schema, contract or specification file",
    "policy": "a policy or configuration authority",
    "registry": "a registry, index or manifest",
    "skill": "a packaged skill",
    "orchestration": "an orchestration or workflow definition",
    "agent": "an agent or provider definition",
    "schema": "a schema document",
    "manifest": "a manifest document",
    "evidence": "evidence or receipt material",
    "test": "a test module or case",
    "documentation": "a narrative document",
    "runtime_artifact": "a produced runtime artifact",
}


def canonical_term(raw: str) -> tuple[str, bool]:
    """Canonicalize an extracted verb root or word.

    Returns (canonical_term, was_canonicalized). Unmapped input returns the
    input unchanged with False so it can be reported as a NOVEL_TERM rather than
    silently folded into a neighbouring concept.
    """
    value = str(raw).strip().lower()
    if not value:
        return value, False
    if value in _CANONICAL_ALIASES:
        return _CANONICAL_ALIASES[value], True
    if value in CANONICAL_SEMANTIC_TERMS:
        return CANONICAL_SEMANTIC_TERMS[value], True
    for suffix in ("_", "s", "es", "ed", "ing", "ion", "or", "er", "ate", "ify", "ize"):
        if value.endswith(suffix) and value[: -len(suffix)] in CANONICAL_SEMANTIC_TERMS:
            return CANONICAL_SEMANTIC_TERMS[value[: -len(suffix)]], True
    for suffix in ("s", "es", "ed", "ing", "ion"):
        if value.endswith(suffix):
            stem = value[: -len(suffix)]
            if stem in _CANONICAL_ALIASES:
                return _CANONICAL_ALIASES[stem], True
    return value, False


def tokenize(text: str) -> list[str]:
    spaced = _CAMEL.sub(" ", str(text).replace("_", " ").replace("-", " ").replace(".", " "))
    return [token for token in _TOKEN.findall(spaced.lower()) if len(token) > 1]


@dataclass
class SurfaceEntity:
    """One entity-bearing item, with every evidence channel collected."""

    key: str
    surface: str          # runtime | contracts | skills | registry | policies | extension
    kind: str             # proposed global kind
    name: str
    source_path: str
    doc: str = ""
    tokens: list[str] = field(default_factory=list)
    imports: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    referenced_schemas: tuple[str, ...] = ()
    tests_referencing: int = 0
    registries_mentioning: int = 0
    line: int = 0

    def channels(self) -> dict[str, Any]:
        """Evidence channels beyond lexical similarity."""
        return {
            "name": self.name,
            "tokens": self.tokens[:24],
            "doc": self.doc[:240],
            "path": self.source_path,
            "kind": self.kind,
            "imports": list(self.imports[:16]),
            "decorators": list(self.decorators[:8]),
            "referenced_schemas": list(self.referenced_schemas[:8]),
            "tests_referencing": self.tests_referencing,
            "registries_mentioning": self.registries_mentioning,
        }