"""Normalized, multi-path capability discovery and minimum-package selection.

This module is the canonical fusion layer over existing metadata navigators. It
normalizes first, keeps source paths independent through discovery, applies
authority and lifecycle filters before selection, and never hydrates bodies or
grants execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Iterable, Mapping, Sequence

from .classifier import classify_task
from .skill_navigator import CapabilitySummary, RISK_ORDER, navigate


TOKEN = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*", re.IGNORECASE)
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "use",
    "with",
}
VERBS = {
    "analyze",
    "audit",
    "build",
    "certify",
    "change",
    "compare",
    "create",
    "debug",
    "deploy",
    "design",
    "diagnose",
    "edit",
    "evaluate",
    "extract",
    "fix",
    "implement",
    "install",
    "integrate",
    "map",
    "migrate",
    "operate",
    "optimize",
    "plan",
    "query",
    "repair",
    "research",
    "review",
    "route",
    "sanitize",
    "test",
    "validate",
    "verify",
    "write",
}
TECHNOLOGIES = {
    "aider",
    "anthropic",
    "azure",
    "claude",
    "codex",
    "docker",
    "fastapi",
    "gemini",
    "github",
    "gitlab",
    "kubernetes",
    "mcp",
    "n8n",
    "nginx",
    "node",
    "openai",
    "postgres",
    "postgresql",
    "python",
    "rag",
    "redis",
    "rust",
    "supabase",
    "svelte",
    "tauri",
    "typescript",
    "vscode",
    "wsl",
}
OUTPUT_TERMS = {
    "api",
    "artifact",
    "certificate",
    "code",
    "contract",
    "csv",
    "document",
    "evidence",
    "file",
    "graph",
    "json",
    "map",
    "package",
    "plan",
    "receipt",
    "report",
    "schema",
    "script",
    "skill",
    "test",
    "tool",
    "workflow",
}
SAFETY_TERMS = {
    "credential",
    "delete",
    "destructive",
    "financial",
    "healthcare",
    "legal",
    "medical",
    "migration",
    "payment",
    "privacy",
    "production",
    "secret",
    "security",
    "token",
    "vulnerability",
}
REPOSITORY_TERMS = {
    "architecture",
    "branch",
    "code",
    "commit",
    "dependency",
    "diff",
    "file",
    "function",
    "import",
    "module",
    "project",
    "repository",
    "repo",
    "test",
}


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.casefold().strip("./-")
                for item in TOKEN.findall(value)
                if item.casefold().strip("./-") not in STOPWORDS
            }
        )
    )


def _stable(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    raw_request: str
    primary_objective: str
    secondary_objectives: tuple[str, ...]
    raw_constraints: tuple[str, ...]
    constraints: tuple[str, ...]
    domain: tuple[str, ...]
    technologies: tuple[str, ...]
    required_outputs: tuple[str, ...]
    safety_implications: tuple[str, ...]
    execution_depth: str
    confidence_requirements: str
    intent: tuple[str, ...]
    capabilities: tuple[str, ...]
    entities: tuple[str, ...]
    aliases: tuple[str, ...]
    verbs: tuple[str, ...]
    nouns: tuple[str, ...]
    semantic_concepts: tuple[str, ...]
    repository_context_required: bool
    task_envelope_sha256: str


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    candidate_id: str
    source_path: str
    source_kind: str
    match_reasons: tuple[str, ...]
    raw_score: float
    confidence: float
    matched_terms: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    matched_graph_paths: tuple[str, ...]
    lifecycle_state: str
    authority_class: str


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: str
    canonical_id: str
    kind: str
    source_paths: tuple[str, ...]
    component_scores: Mapping[str, float]
    penalties: Mapping[str, float]
    final_score: float
    disposition: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPackage:
    package_id: str
    task_envelope_sha256: str
    selected: tuple[str, ...]
    selected_by_kind: Mapping[str, tuple[str, ...]]
    dependencies_added: tuple[str, ...]
    contracts: tuple[str, ...]
    validators: tuple[str, ...]
    unused_candidates: tuple[tuple[str, str], ...]
    complete: bool
    executable: bool
    errors: tuple[str, ...]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class RouteResult:
    envelope: TaskEnvelope
    discovery: Mapping[str, tuple[DiscoveryCandidate, ...]]
    ranked: tuple[RankedCandidate, ...]
    package: ExecutionPackage
    project_map: Mapping[str, object] | None
    receipt_sha256: str


def normalize_task(
    request: str,
    *,
    constraints: Iterable[str] = (),
    repository_context_required: bool | None = None,
) -> TaskEnvelope:
    """Normalize a raw task without retrieval or model-dependent inference."""
    if not request.strip():
        raise ValueError("task request must not be empty")
    raw_constraints = tuple(
        str(value).strip() for value in constraints if str(value).strip()
    )
    tokens = _tokens(request)
    classification = classify_task(request)
    sentences = tuple(
        item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", request) if item.strip()
    )
    primary = sentences[0]
    secondary = sentences[1:]
    verbs = tuple(item for item in tokens if item in VERBS)
    nouns = tuple(item for item in tokens if item not in VERBS)
    technologies = tuple(
        item
        for item in tokens
        if item in TECHNOLOGIES or "." in item or item.startswith("py")
    )
    outputs = tuple(item for item in tokens if item in OUTPUT_TERMS)
    safety = tuple(item for item in tokens if item in SAFETY_TERMS)
    inferred_repository = bool(set(tokens) & REPOSITORY_TERMS)
    if repository_context_required is not None:
        inferred_repository = repository_context_required
    normalized_constraints = tuple(
        sorted(
            {" ".join(_tokens(value)) for value in raw_constraints if _tokens(value)}
        )
    )
    depth = (
        "comprehensive"
        if set(tokens) & {"all", "complete", "comprehensive", "entire", "every", "full"}
        else "bounded"
    )
    confidence = (
        "certification"
        if set(tokens)
        & {"certify", "complete", "correct", "perfect", "production", "validate"}
        else "standard"
    )
    aliases = tuple(sorted({item.replace("-", " ") for item in tokens if "-" in item}))
    concepts = tuple(
        sorted(set((*tokens, *classification.domains, *classification.task_classes)))
    )
    capabilities = tuple(sorted(set((*verbs, *outputs, *classification.domains))))
    entities = tuple(
        item
        for item in tokens
        if any(character in item for character in ("-", ".", "/"))
        or item in technologies
    )
    payload = {
        "raw_request": request,
        "primary_objective": primary,
        "secondary_objectives": secondary,
        "raw_constraints": raw_constraints,
        "constraints": normalized_constraints,
        "domain": classification.domains,
        "technologies": technologies,
        "required_outputs": outputs,
        "safety_implications": safety,
        "execution_depth": depth,
        "confidence_requirements": confidence,
        "intent": tuple(
            sorted(set((*classification.task_classes, *classification.domains)))
        ),
        "capabilities": capabilities,
        "entities": entities,
        "aliases": aliases,
        "verbs": verbs,
        "nouns": nouns,
        "semantic_concepts": concepts,
        "repository_context_required": inferred_repository,
    }
    return TaskEnvelope(**payload, task_envelope_sha256=_stable(payload))


def discover_independently(
    envelope: TaskEnvelope,
    sources: Mapping[str, Iterable[CapabilitySummary]],
    *,
    available_inputs: Mapping[str, object] | None = None,
    constraints: Mapping[str, object] | None = None,
    max_per_source: int = 25,
) -> dict[str, tuple[DiscoveryCandidate, ...]]:
    """Run each governed metadata source independently before fusion."""
    if max_per_source < 1 or max_per_source > 100:
        raise ValueError("max_per_source must be between 1 and 100")
    result: dict[str, tuple[DiscoveryCandidate, ...]] = {}
    for source_id, source_records in sorted(sources.items()):
        records = tuple(source_records)
        navigation = navigate(
            envelope.raw_request,
            records,
            available_inputs,
            max_candidates=max_per_source,
            allowed_statuses=("active", "admitted", "candidate", "candidate_external"),
            constraints=constraints,
        )
        candidates = []
        for row in navigation.candidates:
            record = next(
                item for item in records if item.capability_id == row.capability_id
            )
            candidates.append(
                DiscoveryCandidate(
                    candidate_id=row.capability_id,
                    source_path=source_id,
                    source_kind=record.kind,
                    match_reasons=row.reasons,
                    raw_score=row.score,
                    confidence=round(min(1.0, row.score / 30.0), 6),
                    matched_terms=row.matched_terms,
                    matched_capabilities=tuple(
                        sorted(set(row.matched_terms) & set(record.capability_tags))
                    ),
                    matched_graph_paths=(),
                    lifecycle_state=record.status,
                    authority_class=record.risk,
                )
            )
        result[source_id] = tuple(candidates)
    return result


def expand_graph(
    seeds: Iterable[str],
    edges: Mapping[str, Sequence[tuple[str, str]]],
    *,
    max_depth: int = 2,
    max_nodes: int = 100,
    max_edges: int = 250,
    max_milliseconds: int = 100,
) -> dict[str, tuple[str, ...]]:
    """Expand reviewed edges under explicit depth, node, edge, and time budgets."""
    if not 0 <= max_depth <= 3 or min(max_nodes, max_edges, max_milliseconds) < 1:
        raise ValueError("invalid graph-expansion budget")
    started = time.monotonic()
    paths: dict[str, tuple[str, ...]] = {seed: (seed,) for seed in sorted(set(seeds))}
    frontier = list(paths)
    examined_edges = 0
    for _depth in range(max_depth):
        next_frontier = []
        for source in frontier:
            for relation, target in sorted(
                edges.get(source, ()), key=lambda item: (item[0], item[1])
            ):
                examined_edges += 1
                if (
                    examined_edges > max_edges
                    or (time.monotonic() - started) * 1000 > max_milliseconds
                ):
                    return paths
                if target in paths:
                    continue
                if len(paths) >= max_nodes:
                    return paths
                paths[target] = (*paths[source], f"{relation}:{target}")
                next_frontier.append(target)
        frontier = next_frontier
        if not frontier:
            break
    return paths


def _overlap(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    return 0.0 if not a or not b else len(a & b) / len(a | b)


def canonicalize_records(
    records: Mapping[str, CapabilitySummary],
) -> tuple[dict[str, str], tuple[tuple[str, str, str], ...]]:
    """Resolve explicit supersession and exact semantic shadows deterministically.

    Filenames and input order are never used as evidence of equivalence. Exact
    shadows require the same normalized responsibility signature with at least
    three terms. Explicit ``supersedes`` metadata takes precedence.
    """
    lifecycle = {"active": 0, "admitted": 1, "candidate": 2, "candidate_external": 3}

    def preference(item: CapabilitySummary) -> tuple[object, ...]:
        return (
            lifecycle.get(item.status, 9),
            -item.contract_coverage,
            -item.validation_coverage,
            -item.evidence_quality,
            -item.freshness,
            item.capability_id,
        )

    canonical = {capability_id: capability_id for capability_id in records}
    reasons: list[tuple[str, str, str]] = []
    for owner in sorted(records.values(), key=preference):
        if owner.status not in {"active", "admitted"}:
            continue
        for superseded in sorted(set(owner.supersedes)):
            if superseded in records and superseded != owner.capability_id:
                canonical[superseded] = owner.capability_id
                reasons.append(
                    (superseded, owner.capability_id, "explicit_supersession")
                )

    signatures: dict[tuple[str, ...], list[CapabilitySummary]] = {}
    for item in records.values():
        signature = _tokens(" ".join((*item.outcomes, *item.outputs, item.purpose)))
        if len(signature) >= 3:
            signatures.setdefault(signature, []).append(item)
    for members in signatures.values():
        if len(members) < 2:
            continue
        owner = min(members, key=preference)
        for shadow in sorted(members, key=lambda item: item.capability_id):
            if shadow.capability_id == owner.capability_id:
                continue
            if canonical[shadow.capability_id] != shadow.capability_id:
                continue
            canonical[shadow.capability_id] = owner.capability_id
            reasons.append(
                (shadow.capability_id, owner.capability_id, "exact_semantic_shadow")
            )

    # Collapse a bounded supersession chain and fail closed on cycles.
    for candidate_id in sorted(canonical):
        seen: set[str] = set()
        target = candidate_id
        while canonical[target] != target:
            if target in seen:
                raise ValueError(f"canonical ownership cycle involving {candidate_id}")
            seen.add(target)
            target = canonical[target]
        canonical[candidate_id] = target
    return canonical, tuple(sorted(set(reasons)))


def rank_candidates(
    envelope: TaskEnvelope,
    discovery: Mapping[str, Sequence[DiscoveryCandidate]],
    records: Mapping[str, CapabilitySummary],
    *,
    graph_paths: Mapping[str, tuple[str, ...]] | None = None,
    max_risk: str = "R4",
) -> tuple[RankedCandidate, ...]:
    """Fuse independently discovered records with explainable 0-100 scoring."""
    if max_risk not in RISK_ORDER:
        raise ValueError("max_risk must be R0 through R4")
    canonical_ids, shadow_reasons = canonicalize_records(records)
    shadow_reason_by_id = {
        shadow: (owner, reason) for shadow, owner, reason in shadow_reasons
    }
    by_id: dict[str, list[DiscoveryCandidate]] = {}
    for rows in discovery.values():
        for row in rows:
            by_id.setdefault(
                canonical_ids.get(row.candidate_id, row.candidate_id), []
            ).append(row)
    applicable_ids = set(by_id)
    ranked: list[RankedCandidate] = []
    for candidate_id, rows in sorted(by_id.items()):
        record = records.get(candidate_id)
        if record is None:
            continue
        fields = set(
            _tokens(
                " ".join(
                    (
                        record.capability_id,
                        record.purpose,
                        *record.triggers,
                        *record.aliases,
                        *record.capability_tags,
                        *record.concepts,
                        *record.synonyms,
                    )
                )
            )
        )
        exact_alias = any(
            " ".join(_tokens(value)) == " ".join(_tokens(envelope.raw_request))
            for value in record.aliases
        )
        convergence = min(1.0, len({row.source_path for row in rows}) / 4.0)
        components = {
            "intent_similarity": 10 * _overlap(envelope.intent, fields),
            "capability_match": 16 * _overlap(envelope.capabilities, fields),
            "technology_match": 8 * _overlap(envelope.technologies, fields),
            "domain_match": 7 * _overlap(envelope.domain, fields),
            "task_type_match": 7 * _overlap(envelope.verbs, fields),
            "alias_confidence": 8.0
            if exact_alias
            else 4 * _overlap(envelope.aliases, record.aliases),
            "graph_proximity": 6.0
            if graph_paths and candidate_id in graph_paths
            else 0.0,
            "independent_path_convergence": 8 * convergence,
            "historical_success": 1.5,
            "freshness": 4 * max(0.0, min(1.0, record.freshness)),
            "canonical_preference": 4.0
            if record.status in {"active", "admitted"}
            else 0.0,
            "evidence_quality": 4 * record.evidence_quality,
            "validation_coverage": 4 * record.validation_coverage,
            "contract_coverage": 4 * record.contract_coverage,
            "workflow_compatibility": 2.0 if record.relations else 0.0,
            "tool_compatibility": 2.0,
            "safety_compatibility": 2.0
            if RISK_ORDER.get(record.risk, 4) <= RISK_ORDER[max_risk]
            else 0.0,
            "output_compatibility": 1
            * _overlap(envelope.required_outputs, record.outputs),
            "lexical_support": 5 * min(1.0, max(row.confidence for row in rows)),
        }
        normalized_request = " ".join(_tokens(envelope.raw_request))
        negative_hit = any(
            " ".join(_tokens(item)) in normalized_request
            for item in record.negative_matches
            if _tokens(item)
        )
        avoid_hit = any(
            " ".join(_tokens(item)) in normalized_request
            for item in record.avoid_when
            if _tokens(item)
        )
        penalties = {
            "conflict": 40.0 if set(record.conflicts_with) & applicable_ids else 0.0,
            "deprecation": 50.0
            if record.status in {"deprecated", "superseded", "quarantined"}
            else 0.0,
            "orphan": 10.0 if record.dependencies and not record.relations else 0.0,
            "weak_metadata": 8.0 if len(fields) < 4 else 0.0,
            "stale_source": 10.0 if record.freshness < 0.25 else 0.0,
            "missing_authority": 35.0
            if RISK_ORDER.get(record.risk, 4) > RISK_ORDER[max_risk]
            else 0.0,
            "missing_reviewer": 25.0
            if record.risk in {"R3", "R4"} and not record.reviewed_by
            else 0.0,
            "negative_match": 35.0 if negative_hit else 0.0,
            "avoid_condition": 35.0 if avoid_hit else 0.0,
            "unresolved_dependency": 25.0
            if any(dep not in records for dep in record.dependencies)
            else 0.0,
        }
        positive = sum(components.values())
        penalty = sum(penalties.values())
        score = round(max(0.0, min(100.0, positive - penalty)), 6)
        blocked = any(value >= 25 for value in penalties.values())
        selectable = record.status in {"active", "admitted"} and not blocked
        reasons_set = {reason for row in rows for reason in row.match_reasons}
        for row in rows:
            shadow = shadow_reason_by_id.get(row.candidate_id)
            if shadow:
                reasons_set.add(f"{shadow[1]}:{row.candidate_id}->{shadow[0]}")
        reasons = tuple(
            sorted(
                reasons_set
                | {
                    f"paths={len(rows)}",
                    f"positive={positive:.3f}",
                    f"penalties={penalty:.3f}",
                }
            )
        )
        ranked.append(
            RankedCandidate(
                candidate_id=candidate_id,
                canonical_id=candidate_id,
                kind=record.kind,
                source_paths=tuple(sorted({row.source_path for row in rows})),
                component_scores={
                    key: round(value, 6) for key, value in components.items()
                },
                penalties={key: round(value, 6) for key, value in penalties.items()},
                final_score=score,
                disposition="selectable" if selectable else "discovery_only",
                reasons=reasons,
            )
        )
    return tuple(
        sorted(ranked, key=lambda item: (-item.final_score, item.canonical_id))
    )


def build_minimum_package(
    envelope: TaskEnvelope,
    ranked: Sequence[RankedCandidate],
    records: Mapping[str, CapabilitySummary],
    *,
    max_total: int = 15,
    kind_limits: Mapping[str, int] | None = None,
) -> ExecutionPackage:
    """Build the smallest dependency-complete, policy-compatible package."""
    limits = {
        "agent": 3,
        "skill": 15,
        "workflow": 3,
        "orchestration": 3,
        "formula": 6,
        "validator": 8,
        "contract": 8,
        "tool": 8,
        "knowledge": 8,
    }
    if kind_limits:
        limits.update({str(key): int(value) for key, value in kind_limits.items()})
    selected: list[str] = []
    by_kind: dict[str, list[str]] = {}
    unused: list[tuple[str, str]] = []
    dependencies_added: list[str] = []
    required_terms = set(envelope.capabilities)
    covered: set[str] = set()
    for row in ranked:
        record = records[row.canonical_id]
        if row.disposition != "selectable":
            unused.append((row.candidate_id, "not admitted or failed policy filter"))
            continue
        bucket = by_kind.setdefault(record.kind, [])
        if len(bucket) >= limits.get(record.kind, 8) or len(selected) >= max_total:
            unused.append((row.candidate_id, "package budget"))
            continue
        record_terms = set(
            _tokens(
                " ".join((record.purpose, *record.capability_tags, *record.triggers))
            )
        )
        new_coverage = required_terms & record_terms - covered
        if selected and not new_coverage and row.final_score < 25:
            unused.append((row.candidate_id, "redundant low-utility candidate"))
            continue
        selected.append(row.canonical_id)
        bucket.append(row.canonical_id)
        covered.update(new_coverage)
        if required_terms and covered >= required_terms:
            break
    cursor = 0
    errors: list[str] = []
    while cursor < len(selected):
        current = records[selected[cursor]]
        cursor += 1
        for dependency in current.dependencies:
            if dependency in selected:
                continue
            target = records.get(dependency)
            if target is None:
                errors.append(
                    f"unresolved dependency: {current.capability_id} -> {dependency}"
                )
                continue
            bucket = by_kind.setdefault(target.kind, [])
            if len(selected) >= max_total or len(bucket) >= limits.get(target.kind, 8):
                errors.append(f"dependency budget exceeded: {dependency}")
                continue
            selected.append(dependency)
            bucket.append(dependency)
            dependencies_added.append(dependency)
    for left in selected:
        for conflict in records[left].conflicts_with:
            if conflict in selected:
                errors.append(f"conflict: {left} -> {conflict}")
    contracts = tuple(
        sorted(
            {
                item
                for selected_id in selected
                for item in records[selected_id].contracts
            }
        )
    )
    validators = tuple(
        sorted(
            {
                item
                for selected_id in selected
                for item in records[selected_id].validators
            }
        )
    )
    complete = bool(selected) and not errors
    # Specialist prompts provide bounded context, never execution authority.
    # A package containing agents must pass through the separate agent compile
    # and task-authorization boundaries before any effects can be executed.
    executable = complete and not by_kind.get("agent")
    payload = {
        "task_envelope_sha256": envelope.task_envelope_sha256,
        "selected": selected,
        "selected_by_kind": {
            key: tuple(value) for key, value in sorted(by_kind.items())
        },
        "dependencies_added": dependencies_added,
        "contracts": contracts,
        "validators": validators,
        "unused_candidates": unused,
        "complete": complete,
        "executable": executable,
        "errors": sorted(set(errors)),
    }
    package_id = "pkg_" + _stable(payload)[:20]
    receipt = _stable({"package_id": package_id, **payload})
    return ExecutionPackage(
        package_id=package_id,
        task_envelope_sha256=envelope.task_envelope_sha256,
        selected=tuple(selected),
        selected_by_kind={key: tuple(value) for key, value in sorted(by_kind.items())},
        dependencies_added=tuple(dependencies_added),
        contracts=contracts,
        validators=validators,
        unused_candidates=tuple(unused),
        complete=complete,
        executable=executable,
        errors=tuple(sorted(set(errors))),
        receipt_sha256=receipt,
    )


def route_task(
    request: str,
    sources: Mapping[str, Iterable[CapabilitySummary]],
    *,
    project: Path | None = None,
    constraints: Iterable[str] = (),
    max_risk: str = "R4",
    available_inputs: Mapping[str, object] | None = None,
    canonical_records: Mapping[str, CapabilitySummary] | None = None,
) -> RouteResult:
    """Run the normalized discovery-to-package control flow without execution."""
    envelope = normalize_task(
        request,
        constraints=constraints,
        repository_context_required=project is not None or None,
    )
    project_map: Mapping[str, object] | None = None
    if envelope.repository_context_required and project is not None:
        from .project_intelligence import validate_project_map
        from .project_map_retrieval import query_project_map

        validation = validate_project_map(project, check_freshness=True)
        if not validation.get("valid"):
            raise ValueError(
                f"fresh project map required: {validation.get('errors', [])}"
            )
        project_map = query_project_map(project, request, top_k=10, relation_depth=2)
    materialized = {name: tuple(items) for name, items in sources.items()}
    records = dict(canonical_records or {})
    for items in materialized.values():
        for item in items:
            records.setdefault(item.capability_id, item)
    discovery = discover_independently(
        envelope,
        materialized,
        available_inputs=available_inputs,
        constraints={"max_risk": max_risk},
    )
    relations = {
        record.capability_id: tuple(("relation", target) for target in record.relations)
        for record in records.values()
    }
    seeds = [row.candidate_id for rows in discovery.values() for row in rows[:5]]
    graph_paths = expand_graph(seeds, relations)
    ranked = rank_candidates(
        envelope, discovery, records, graph_paths=graph_paths, max_risk=max_risk
    )
    package = build_minimum_package(envelope, ranked, records)
    receipt_payload = {
        "envelope": envelope.task_envelope_sha256,
        "discovery_sources": {
            key: [item.candidate_id for item in value]
            for key, value in discovery.items()
        },
        "ranked": [
            (item.canonical_id, item.final_score, item.disposition) for item in ranked
        ],
        "package": package.receipt_sha256,
        "project_map_revision": project_map.get("map_revision")
        if project_map
        else None,
    }
    return RouteResult(
        envelope, discovery, ranked, package, project_map, _stable(receipt_payload)
    )


def as_jsonable(result: RouteResult) -> dict[str, object]:
    """Convert an immutable route result to a stable JSON-compatible object."""
    return asdict(result)
