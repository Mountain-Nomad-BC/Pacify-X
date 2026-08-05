"""Deterministic, proposal-only engineering intelligence analyses.

These analyzers operate on supplied manifests and source text. They do not edit
code, install tools, or promote recommendations automatically.
"""

from __future__ import annotations

import ast
from collections import deque
import hashlib
import json
import re
from typing import Iterable, Mapping


TOKEN = re.compile(r"[a-z0-9_]+")


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def architecture_drift(
    baseline: Mapping[str, Iterable[str]], current: Mapping[str, Iterable[str]]
) -> dict[str, object]:
    old = {str(node): set(map(str, edges)) for node, edges in baseline.items()}
    new = {str(node): set(map(str, edges)) for node, edges in current.items()}
    added_nodes = sorted(set(new) - set(old))
    removed_nodes = sorted(set(old) - set(new))
    added_edges = sorted(
        (node, edge) for node in new for edge in new[node] - old.get(node, set())
    )
    removed_edges = sorted(
        (node, edge) for node in old for edge in old[node] - new.get(node, set())
    )
    denominator = max(1, len(old) + sum(map(len, old.values())))
    score = min(
        1.0,
        (len(added_nodes) + len(removed_nodes) + len(added_edges) + len(removed_edges))
        / denominator,
    )
    payload = {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }
    return {
        **payload,
        "drift_score": round(score, 6),
        "baseline_sha256": _stable(old),
        "current_sha256": _stable(new),
    }


def dependency_shockwave(
    graph: Mapping[str, Iterable[str]],
    changed: Iterable[str],
    *,
    max_depth: int = 8,
    max_nodes: int = 10_000,
) -> dict[str, object]:
    if max_depth < 1 or max_nodes < 1:
        raise ValueError("shockwave bounds must be positive")
    reverse: dict[str, set[str]] = {}
    for consumer, dependencies in graph.items():
        for dependency in dependencies:
            reverse.setdefault(str(dependency), set()).add(str(consumer))
    queue = deque((str(node), 0) for node in sorted(set(changed)))
    distance: dict[str, int] = {}
    while queue and len(distance) < max_nodes:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for consumer in sorted(reverse.get(node, ())):
            next_depth = depth + 1
            if consumer not in distance or next_depth < distance[consumer]:
                distance[consumer] = next_depth
                queue.append((consumer, next_depth))
    truncated = bool(queue)
    ranked = tuple(
        sorted(
            (
                {"component": node, "distance": depth, "risk": round(1 / depth, 6)}
                for node, depth in distance.items()
            ),
            key=lambda item: (item["distance"], item["component"]),
        )
    )
    return {
        "affected": ranked,
        "truncated": truncated,
        "max_depth": max_depth,
        "max_nodes": max_nodes,
    }


def semantic_drift(
    baseline: Mapping[str, Mapping[str, object]],
    current: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    findings = []
    for contract_id in sorted(set(baseline) | set(current)):
        old = baseline.get(contract_id)
        new = current.get(contract_id)
        if old is None or new is None:
            findings.append(
                {
                    "contract": contract_id,
                    "kind": "added" if old is None else "removed",
                    "severity": "high",
                }
            )
            continue
        for field in ("inputs", "outputs", "invariants", "effects", "errors"):
            before = old.get(field)
            after = new.get(field)
            if before != after:
                severity = "high" if field in {"invariants", "effects"} else "medium"
                findings.append(
                    {
                        "contract": contract_id,
                        "kind": f"{field}_changed",
                        "severity": severity,
                        "before": before,
                        "after": after,
                    }
                )
    return {
        "findings": tuple(findings),
        "drift": bool(findings),
        "fingerprint": _stable(findings),
    }


def knowledge_collisions(claims: Iterable[Mapping[str, object]]) -> dict[str, object]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for claim in claims:
        subject = str(claim.get("subject", "")).casefold().strip()
        if subject:
            grouped.setdefault(subject, []).append(claim)
    collisions = []
    for subject, values in sorted(grouped.items()):
        positions = {
            str(item.get("position", "")).casefold().strip()
            for item in values
            if item.get("position")
        }
        if len(positions) > 1:
            collisions.append(
                {
                    "subject": subject,
                    "positions": tuple(sorted(positions)),
                    "evidence": tuple(
                        sorted(
                            {
                                str(ref)
                                for item in values
                                for ref in item.get("evidence", ())
                            }
                        )
                    ),
                    "resolution": "human_or_experiment_required",
                }
            )
    return {"collisions": tuple(collisions), "automatic_resolution": False}


def future_debt(changes: Iterable[Mapping[str, object]]) -> dict[str, object]:
    findings = []
    for change in changes:
        factors = []
        if not change.get("tests"):
            factors.append("tests_missing")
        if not change.get("owner"):
            factors.append("owner_missing")
        if not change.get("rollback"):
            factors.append("rollback_missing")
        if float(change.get("coupling", 0)) > 0.7:
            factors.append("high_coupling")
        if change.get("deprecated_dependency") is True:
            factors.append("deprecated_dependency")
        findings.append(
            {
                "change_id": str(change.get("change_id", "unknown")),
                "risk": min(1.0, len(factors) / 5),
                "factors": tuple(factors),
            }
        )
    return {"findings": tuple(findings), "proposal_only": True}


def engineering_health(dimensions: Mapping[str, object]) -> dict[str, object]:
    scores = {}
    unknown = []
    for name in (
        "architecture",
        "dependencies",
        "contracts",
        "tests",
        "security",
        "operations",
        "knowledge",
    ):
        value = dimensions.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= float(value) <= 1
        ):
            unknown.append(name)
        else:
            scores[name] = float(value)
    coverage = len(scores) / 7
    score = sum(scores.values()) / max(1, len(scores))
    return {
        "score": round(score, 6),
        "coverage": round(coverage, 6),
        "dimensions": scores,
        "unknown": unknown,
        "certifying": not unknown,
    }


def code_genome(sources: Mapping[str, str]) -> dict[str, object]:
    files = []
    errors = []
    for path, source in sorted(sources.items()):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as error:
            errors.append({"path": path, "line": error.lineno, "kind": "syntax_error"})
            continue
        symbols = sorted(
            f"{type(node).__name__}:{node.name}:{len(node.args.args) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else 0}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        )
        imports = sorted(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        )
        files.append(
            {
                "path": path,
                "symbols": symbols,
                "imports": imports,
                "sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )
    return {
        "files": tuple(files),
        "parse_errors": tuple(errors),
        "genome_sha256": _stable(files),
        "executes_source": False,
    }


def project_fitness(
    requirements: Iterable[str], capabilities: Iterable[str]
) -> dict[str, object]:
    required = set(map(str, requirements))
    available = set(map(str, capabilities))
    covered = sorted(required & available)
    gaps = sorted(required - available)
    return {
        "score": round(len(covered) / max(1, len(required)), 6),
        "covered": covered,
        "gaps": gaps,
        "complete": not gaps,
    }


def refactoring_plan(*analyses: Mapping[str, object]) -> dict[str, object]:
    actions = []
    for analysis in analyses:
        for finding in analysis.get("findings", ()):
            actions.append(
                {
                    "finding": finding,
                    "action": "investigate_then_patch",
                    "approval_required": True,
                }
            )
        for node in analysis.get("removed_nodes", ()):
            actions.append(
                {
                    "finding": {"removed_node": node},
                    "action": "verify_dependents_and_contracts",
                    "approval_required": True,
                }
            )
    return {
        "actions": tuple(actions),
        "auto_apply": False,
        "plan_sha256": _stable(actions),
    }


def regression_hypotheses(
    changes: Iterable[Mapping[str, object]],
    failures: Iterable[Mapping[str, object]],
    dependency_graph: Mapping[str, Iterable[str]],
) -> dict[str, object]:
    """Rank evidence-backed regression hypotheses without asserting causality."""
    failed_components = {
        str(item.get("component", "")) for item in failures if item.get("component")
    }
    hypotheses = []
    for change in changes:
        component = str(change.get("component", ""))
        if not component:
            continue
        shockwave = dependency_shockwave(dependency_graph, [component])
        affected = {item["component"] for item in shockwave["affected"]} | {component}
        overlap = sorted(affected & failed_components)
        evidence = tuple(sorted(set(map(str, change.get("evidence", ())))))
        score = min(
            1.0,
            0.2 * len(overlap)
            + (0.2 if evidence else 0.0)
            + (0.2 if change.get("temporal_precedence") is True else 0.0),
        )
        if overlap:
            hypotheses.append(
                {
                    "change_id": str(change.get("change_id", "unknown")),
                    "component": component,
                    "affected_failures": overlap,
                    "evidence": evidence,
                    "score": round(score, 6),
                    "causality_proven": False,
                }
            )
    hypotheses.sort(key=lambda item: (-item["score"], item["change_id"]))
    return {
        "hypotheses": tuple(hypotheses),
        "causality_proven": False,
        "next": "isolate_and_reproduce",
    }


def framework_dna(
    project_topology: Mapping[str, Iterable[str]],
    decision_graph: Iterable[Mapping[str, object]],
    validated_patterns: Iterable[Mapping[str, object]],
    *,
    exclusions: Iterable[str] = (),
) -> dict[str, object]:
    patterns = tuple(
        item
        for item in validated_patterns
        if item.get("validated") is True and item.get("id")
    )
    principles = tuple(
        sorted(
            {str(item.get("principle")) for item in patterns if item.get("principle")}
        )
    )
    modules = tuple(
        {"pattern_id": str(item["id"]), "state": "candidate_bootstrap_module"}
        for item in patterns
    )
    profile = {
        "topology_sha256": _stable(
            {key: sorted(map(str, value)) for key, value in project_topology.items()}
        ),
        "decision_sha256": _stable(tuple(decision_graph)),
        "principles": principles,
        "bootstrap_modules": modules,
        "project_specific_exclusions": tuple(sorted(set(map(str, exclusions)))),
        "blind_copy": False,
        "auto_activate": False,
    }
    return {**profile, "dna_sha256": _stable(profile)}


def opportunity_backlog(metrics: Iterable[Mapping[str, object]]) -> dict[str, object]:
    candidates = []
    for item in metrics:
        repetitions = max(0, int(item.get("repetitions", 0)))
        minutes = max(0.0, float(item.get("minutes_each", 0)))
        error_rate = min(1.0, max(0.0, float(item.get("error_rate", 0))))
        risk = min(1.0, max(0.0, float(item.get("automation_risk", 1))))
        value = (repetitions * minutes) * (1 + error_rate) * (1 - risk)
        if value <= 0:
            continue
        candidates.append(
            {
                "activity": str(item.get("activity", "unknown")),
                "value_score": round(value, 6),
                "automation_hypothesis": str(
                    item.get("hypothesis", "measure a bounded automation experiment")
                ),
                "risk": risk,
                "state": "candidate",
            }
        )
    candidates.sort(key=lambda item: (-item["value_score"], item["activity"]))
    return {
        "opportunities": tuple(candidates),
        "measured": True,
        "novelty_ranked": False,
        "auto_activate": False,
    }


def pattern_candidates(
    records: Iterable[Mapping[str, object]], *, minimum_support: int = 2
) -> dict[str, object]:
    if minimum_support < 2:
        raise ValueError("pattern support must require repetition")
    groups: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        signature = str(record.get("signature", "")).strip()
        if signature:
            groups.setdefault(signature, []).append(record)
    patterns = []
    for signature, items in sorted(groups.items()):
        if len(items) < minimum_support:
            continue
        patterns.append(
            {
                "signature": signature,
                "support": len(items),
                "examples": tuple(
                    sorted(
                        str(item.get("example", ""))
                        for item in items
                        if item.get("example")
                    )
                ),
                "generalization_proposal": str(
                    items[0].get("generalization", "review recurring structure")
                ),
                "validated": False,
            }
        )
    return {"patterns": tuple(patterns), "repetition_is_proof": False}


def benchmark_lab(
    runs: Iterable[Mapping[str, object]], *, baseline_version: str | None = None
) -> dict[str, object]:
    values = tuple(runs)
    groups: dict[str, list[Mapping[str, object]]] = {}
    errors = []
    for run in values:
        for field in (
            "candidate_id",
            "version",
            "fixture_version",
            "quality",
            "latency",
            "cost",
            "resource",
        ):
            if field not in run:
                errors.append(f"field_missing:{field}")
        if not errors or all(field in run for field in ("candidate_id", "version")):
            groups.setdefault(
                f"{run.get('candidate_id')}@{run.get('version')}", []
            ).append(run)
    reports = []
    for identity, items in sorted(groups.items()):
        metrics = {}
        for metric in ("quality", "latency", "cost", "resource"):
            samples = [float(item[metric]) for item in items if metric in item]
            if samples:
                metrics[metric] = {
                    "mean": round(sum(samples) / len(samples), 6),
                    "min": min(samples),
                    "max": max(samples),
                    "samples": len(samples),
                }
        reports.append(
            {
                "candidate": identity,
                "metrics": metrics,
                "fixture_versions": tuple(
                    sorted({str(item.get("fixture_version")) for item in items})
                ),
            }
        )
    return {
        "reports": tuple(reports),
        "errors": tuple(sorted(set(errors))),
        "baseline_version": baseline_version,
        "uncertainty_reported": True,
        "regression_gate": "blocked" if errors or not reports else "evaluable",
        "single_run_certifies": False,
    }


def repository_digital_twin(
    inventory: Iterable[str],
    manifests: Mapping[str, Iterable[str]],
    static_edges: Iterable[tuple[str, str]],
    runtime_edges: Iterable[tuple[str, str]],
) -> dict[str, object]:
    nodes = set(map(str, inventory)) | set(map(str, manifests))
    edges = {
        tuple(map(str, edge)) for edge in (*tuple(static_edges), *tuple(runtime_edges))
    }
    for source, target in edges:
        nodes.update((source, target))
    alerts = tuple(
        sorted(
            {
                f"manifest_target_missing:{source}->{target}"
                for source, targets in manifests.items()
                for target in targets
                if str(target) not in nodes
            }
        )
    )
    graph = {"nodes": tuple(sorted(nodes)), "edges": tuple(sorted(edges))}
    return {
        "graph": graph,
        "version": _stable(graph),
        "inconsistency_alerts": alerts,
        "simulation_interface": (
            "dependency_shockwave",
            "architecture_drift",
            "resilience_digital_twin",
        ),
        "source_of_truth": False,
    }
