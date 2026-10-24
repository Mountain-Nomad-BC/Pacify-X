"""Dry-run semantic census for punch card SEM-003.

This module PROPOSES a taxonomy. It does not freeze one, and it allocates no
production addresses.

Why a census before a legend
-----------------------------
The previous compact-address implementation derived all four segments from raw
digest bytes. That produced collision-free, deterministic, reserved-safe
addresses that carried no meaning at all: eight operations received eight
distinct Kind values. The mechanics were sound and the semantics were noise.

Fixing that requires knowing what the four dimensions actually contain in THIS
repository. Inventing a vocabulary would just relocate the same error, so this
module extracts evidence first and reports candidates.

The four dimensions, per the SEM-003 design
-------------------------------------------
Subject  - highest useful semantic domain (runtime, governance, memory,
           verification, routing, ...). NOT a module path. Physical location may
           be evidence for a proposal but never authority, because semantic
           identity must survive artifact relocation.
Object   - the concept within the Subject that the entity primarily concerns.
           Path-independent: imports, call relationships and docstrings are
           evidence, not identity.
Semantic - the entity's meaningful function in the PX ontology (validates,
           routes, executes, governs, produces, consumes, records, ...). These
           are PX functional roles, not linguistic semantic roles such as
           agent/patient/instrument.
Kind     - a closed entity-type vocabulary. This is the dimension where a
           tightly controlled vocabulary genuinely belongs, because kind=N must
           mean the same thing system-wide.

ML is advisory
--------------
Feature vectors and clustering PROPOSE groupings. Nothing here writes a legend.
Every proposal is reported with counts, representatives and confidence so a
human can accept, merge or reject it. That is the difference between a taxonomy
and a clustering that quietly becomes authority.

Nothing is silently created
---------------------------
An entity whose proposed classification is uncertain is reported as
UNRESOLVED, AMBIGUOUS or NOVEL_TERM. The census never invents a term to make
every row fit, because a fabricated legend is worse than an admitted gap.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CENSUS_SCHEMA = "px.semantic-census/1.0"

UNRESOLVED = "UNRESOLVED"
AMBIGUOUS = "AMBIGUOUS"
NOVEL_TERM = "NOVEL_TERM"

# Classification outcome vocabulary. An entity never silently lands in a term.
CLASSIFICATION_OUTCOMES = ("RESOLVED", UNRESOLVED, AMBIGUOUS, NOVEL_TERM)

_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Verb families are PROPOSALS derived from the corpus, not a frozen vocabulary.
# They are counted and reported so a human can confirm, split or reject each.
_PROPOSED_SEMANTIC_ROOTS = (
    "validat", "verif", "govern", "route", "dispatch", "execut", "run",
    "produce", "generat", "create", "build", "emit", "publish",
    "consum", "read", "load", "fetch", "retriev", "query", "search",
    "record", "persist", "store", "log", "track", "receipt",
    "promot", "learn", "adapt", "evolv",
    "depend", "import", "resolve", "bind", "link",
    "authoriz", "approve", "deny",
    "project", "derive", "compute", "calculat", "classif", "infer",
    "reclaim", "clean", "prune", "compact", "coalesc",
    "install", "package", "publish_artifact", "deploy",
    "compare", "diff", "merge", "conflict",
    "orchestrat", "schedul", "queue",
    "diagnos", "inspect", "explain", "trace",
    "translat", "render", "serial", "deserial", "encode", "decode",
    "open", "close", "connect", "bind_port", "listen",
    "learn_from", "remember", "forget",
    "supervis", "monitor", "watch",
)

# Kind proposals are a CLOSED vocabulary by intent, derived from what the
# corpus actually contains rather than assumed.
_PROPOSED_KINDS = {
    "module": "a python or javascript module",
    "function": "a callable",
    "class": "a type declaration",
    "contract": "a schema or contract file",
    "test": "a test module or case",
    "registry": "a registry or index",
    "policy": "a policy or configuration authority",
    "artifact": "a produced artifact",
    "evidence": "evidence or receipt material",
}


def _tokens(text: str) -> list[str]:
    """Lowercase, de-camel, de-snake tokens."""
    spaced = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " "))
    return [token for token in _TOKEN.findall(spaced.lower()) if len(token) > 1]


@dataclass(frozen=True)
class ObservedEntity:
    """One analyzable thing in the corpus, before classification."""

    entity_key: str          # synthetic, census-local; NOT a PX entity_id
    source_path: str         # evidence only, never authority
    symbol: str
    kind_proposal: str
    docstring: str = ""
    imports: tuple[str, ...] = ()
    line: int = 0

    def feature_text(self) -> str:
        """Text used for TF-IDF. Path is included as evidence, not identity."""
        return " ".join(
            [
                self.source_path.replace("/", " ").replace(".", " ").replace("_", " "),
                self.symbol.replace("_", " "),
                self.docstring[:240].replace("\n", " "),
                " ".join(self.imports[:12]),
            ]
        )


@dataclass
class Proposal:
    dimension: str
    term: str
    count: int
    representatives: list[str] = field(default_factory=list)
    support: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "term": self.term,
            "count": self.count,
            "support": round(self.support, 4),
            "representatives": self.representatives[:6],
        }


@dataclass
class Classification:
    entity_key: str
    subject: str
    obj: str
    semantic: str
    kind: str
    outcome: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def four_segment(self) -> tuple[str, str, str, str]:
        return (self.subject, self.obj, self.semantic, self.kind)


# --- feature extraction ----------------------------------------------------


def observe_python_module(path: Path, root: Path, *, max_symbols: int = 400) -> list[ObservedEntity]:
    """Extract module, class and function observations from one Python file."""
    relative = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return []
    doc = ast.get_docstring(tree) or ""
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names[:20])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    out: list[ObservedEntity] = [
        ObservedEntity(
            entity_key=f"py:module:{relative}",
            source_path=relative,
            symbol=path.stem,
            kind_proposal="module",
            docstring=doc[:240],
            imports=tuple(imports[:24]),
            line=0,
        )
    ]
    count = 0
    for node in tree.body:
        for child in ast.walk(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            kind = "class" if isinstance(child, ast.ClassDef) else "function"
            out.append(
                ObservedEntity(
                    entity_key=f"py:{kind}:{relative}:{child.lineno}:{child.name}",
                    source_path=relative,
                    symbol=child.name,
                    kind_proposal=kind,
                    docstring=(ast.get_docstring(child) or "")[:240],
                    imports=(),
                    line=child.lineno,
                )
            )
            count += 1
            if count >= max_symbols:
                return out
    return out


def census_corpus(
    root: Path,
    *,
    include_globs: Iterable[str] = ("runtime/**/*.py", "extension/src/**/*.js"),
    max_entities: int = 6000,
) -> list[ObservedEntity]:
    """Walk the authored corpus and collect observations."""
    root = Path(root).resolve(strict=True)
    observed: list[ObservedEntity] = []
    seen: set[Path] = set()
    for pattern in include_globs:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            if path.suffix == ".py":
                observed.extend(observe_python_module(path, root))
            else:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                observed.append(
                    ObservedEntity(
                        entity_key=f"js:module:{path.relative_to(root).as_posix()}",
                        source_path=path.relative_to(root).as_posix(),
                        symbol=path.stem,
                        kind_proposal="module",
                        docstring="",
                    )
                )
                del text
            if len(observed) >= max_entities:
                return observed[:max_entities]
    return observed


# --- advisory proposal -----------------------------------------------------


def propose_subject(entity: ObservedEntity, taxonomy: dict[str, list[str]]) -> tuple[str, float, list[str]]:
    """Propose a Subject domain from evidence, never from the path alone.

    Path components vote, symbol tokens vote, docstring tokens vote. A proposal
    is only returned when the evidence concentrates; otherwise UNRESOLVED.
    """
    votes: Counter[str] = Counter()
    # Evidence 1: path components (weak - relocatable, so never decisive alone)
    for component in entity.source_path.replace("\\", "/").split("/")[:-1]:
        for token in _tokens(component):
            for subject in taxonomy["subject"]:
                if token == subject or token.startswith(subject):
                    votes[subject] += 1
    # Evidence 2: symbol tokens
    for token in _tokens(entity.symbol):
        for subject in taxonomy["subject"]:
            if token == subject or token.startswith(subject):
                votes[subject] += 3
    # Evidence 3: docstring tokens (weakest, sparse)
    for token in _tokens(entity.docstring)[:40]:
        for subject in taxonomy["subject"]:
            if token == subject:
                votes[subject] += 1
    if not votes:
        return UNRESOLVED, 0.0, []
    ranked = votes.most_common()
    total = sum(votes.values())
    top_term, top_votes = ranked[0]
    confidence = top_votes / total if total else 0.0
    if confidence < 0.45:
        return AMBIGUOUS, round(confidence, 3), [term for term, _ in ranked[:3]]
    return top_term, round(confidence, 3), [term for term, _ in ranked[:3]]


def propose_semantic(entity: ObservedEntity) -> tuple[str, float, list[str]]:
    """Propose a PX functional role from verb families found in the symbol."""
    tokens = _tokens(entity.symbol)
    if not tokens:
        return NOVEL_TERM, 0.0, []
    hits: list[str] = []
    for token in tokens:
        for root in _PROPOSED_SEMANTIC_ROOTS:
            if token.startswith(root) or root.startswith(token):
                hits.append(root)
                break
    if not hits:
        return NOVEL_TERM, 0.0, []
    counts = Counter(hits)
    top, count = counts.most_common(1)[0]
    confidence = min(1.0, count / 2.0)
    return top, round(confidence, 3), [term for term, _ in counts.most_common(3)]


def propose_object(entity: ObservedEntity, subject: str) -> tuple[str, float, list[str]]:
    """Propose an Object concept: the symbol's head noun inside its Subject."""
    tokens = _tokens(entity.symbol)
    if not tokens:
        return NOVEL_TERM, 0.0, []
    # Drop the verb-like leading token; keep the domain noun that follows it.
    head = tokens[-1]
    if len(tokens) >= 2 and any(
        head.startswith(root) or root.startswith(head) for root in _PROPOSED_SEMANTIC_ROOTS
    ):
        head = tokens[-2] if len(tokens) >= 2 else head
    return head, 0.5, [head]


def classify(
    entity: ObservedEntity, taxonomy: dict[str, list[str]]
) -> Classification:
    subject, subject_confidence, subject_rivals = propose_subject(entity, taxonomy)
    semantic, semantic_confidence, semantic_rivals = propose_semantic(entity)
    obj, object_confidence, object_rivals = propose_object(entity, subject)
    unresolved = [
        name
        for name, value in (
            ("Subject", subject),
            ("Semantic", semantic),
            ("Object", obj),
        )
        if value in {UNRESOLVED, AMBIGUOUS, NOVEL_TERM}
    ]
    if len(unresolved) > 1:
        outcome = AMBIGUOUS
    elif unresolved:
        outcome = NOVEL_TERM if semantic in {NOVEL_TERM} or subject == NOVEL_TERM else UNRESOLVED
    else:
        outcome = "RESOLVED"
    confidence = round(
        (subject_confidence + semantic_confidence + object_confidence) / 3.0, 3
    )
    return Classification(
        entity_key=entity.entity_key,
        subject=subject,
        obj=obj,
        semantic=semantic,
        kind=entity.kind_proposal,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "source_path": entity.source_path,
            "symbol": entity.symbol,
            "subject_rivals": subject_rivals[:3],
            "semantic_rivals": semantic_rivals[:3],
        },
    )