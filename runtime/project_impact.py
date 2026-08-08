"""Bounded, evidence-backed change impact analysis over a PACIFY-X project map."""

from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .project_intelligence import _load_json, _load_jsonl, _map_dir, validate_project_map


def _walk(
    starts: Iterable[str],
    adjacency: Mapping[str, set[str]],
    *,
    max_depth: int,
    max_nodes: int,
) -> tuple[dict[str, int], bool]:
    depths = {str(node): 0 for node in starts}
    queue = deque(sorted(depths))
    truncated = False
    while queue:
        source = queue.popleft()
        depth = depths[source]
        if depth >= max_depth:
            continue
        for target in sorted(adjacency.get(source, ())):
            if target in depths:
                continue
            if len(depths) >= max_nodes:
                truncated = True
                return depths, truncated
            depths[target] = depth + 1
            queue.append(target)
    return depths, truncated


def _symbol_id(record: Mapping[str, object]) -> str:
    return f"symbol:{record['path']}:{record.get('qualname')}"


def _symbol_candidate(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": _symbol_id(record),
        "path": record.get("path"),
        "name": record.get("name"),
        "qualname": record.get("qualname"),
        "kind": record.get("kind"),
        "line_start": record.get("line_start"),
        "line_end": record.get("line_end"),
    }


def _resolve_target(
    target: str, symbols: list[dict[str, Any]], inventory_paths: set[str]
) -> tuple[str | None, list[dict[str, object]], str | None]:
    normalized = target.strip().replace("\\", "/")
    if not normalized:
        return None, [], "target must be nonempty"
    if normalized.startswith("file:"):
        normalized = normalized.removeprefix("file:")
    if normalized in inventory_paths:
        return f"file:{normalized}", [], None

    exact_id = [record for record in symbols if _symbol_id(record) == target]
    if len(exact_id) == 1:
        return _symbol_id(exact_id[0]), [], None

    path_hint = None
    name_hint = normalized
    if "::" in normalized:
        path_hint, name_hint = normalized.split("::", 1)
        path_hint = path_hint.strip("/")
    matches = [
        record
        for record in symbols
        if str(record.get("qualname")) == name_hint
        or str(record.get("name")) == name_hint
    ]
    if path_hint:
        matches = [record for record in matches if str(record.get("path")) == path_hint]
    if len(matches) == 1:
        return _symbol_id(matches[0]), [], None
    candidates = [_symbol_candidate(record) for record in matches[:50]]
    if candidates:
        return None, candidates, "target is ambiguous; use path::qualname or the full symbol id"
    return None, [], "target was not found in the current project map"


def _adjacency(
    edges: Iterable[Mapping[str, object]], *, reverse: bool
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge.get("from", ""))
        target = str(edge.get("to", ""))
        if not source or not target:
            continue
        if reverse:
            source, target = target, source
        result[source].add(target)
    return result


def _risk(
    *,
    direct: int,
    transitive: int,
    files: int,
    routes: int,
    contracts: int,
    services: int,
    tests: int,
    truncated: bool,
) -> tuple[int, str]:
    score = min(
        100,
        5
        + direct * 6
        + max(0, transitive - direct) * 2
        + max(0, files - 1) * 2
        + routes * 8
        + contracts * 6
        + services * 10
        + min(tests, 10)
        + (15 if truncated else 0),
    )
    if score >= 70:
        return score, "critical"
    if score >= 40:
        return score, "high"
    if score >= 20:
        return score, "medium"
    return score, "low"


def analyze_project_impact(
    project_or_map: Path,
    target: str,
    *,
    direction: str = "upstream",
    max_depth: int = 4,
    max_nodes: int = 500,
    require_fresh: bool = True,
) -> dict[str, object]:
    """Return bounded callers, importing files, routes, contracts, tests, and services."""
    if direction not in {"upstream", "downstream", "both"}:
        raise ValueError("direction must be upstream, downstream, or both")
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    if max_nodes < 1 or max_nodes > 10_000:
        raise ValueError("max_nodes must be between 1 and 10000")

    validation = validate_project_map(project_or_map, check_freshness=require_fresh)
    if not validation.get("valid"):
        return {
            "schema_version": "1.0",
            "valid": False,
            "target": target,
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "repair": "Build or refresh the project map before impact analysis.",
        }

    map_dir = _map_dir(project_or_map)
    manifest = _load_json(map_dir / "project-manifest.json")
    symbols = _load_jsonl(map_dir / "symbol-index.jsonl")
    inventory = _load_jsonl(map_dir / "file-inventory.jsonl")
    inventory_paths = {str(record["path"]) for record in inventory}
    target_id, candidates, resolution_error = _resolve_target(
        target, symbols, inventory_paths
    )
    if target_id is None:
        return {
            "schema_version": "1.0",
            "valid": False,
            "target": target,
            "map_revision": manifest.get("map_revision"),
            "error": resolution_error,
            "candidates": candidates,
        }

    call_graph = _load_json(map_dir / "call-graph.json")
    dependency_graph = _load_json(map_dir / "dependency-graph.json")
    traceability = _load_json(map_dir / "traceability-map.json")
    runtime = _load_json(map_dir / "runtime-topology.json")

    call_edges = list(call_graph.get("edges", ()))
    dependency_edges = [
        edge
        for edge in dependency_graph.get("edges", ())
        if edge.get("kind") in {"imports", "service_depends_on"}
    ]
    if direction == "both":
        call_adj = _adjacency(call_edges, reverse=False)
        dep_adj = _adjacency(dependency_edges, reverse=False)
        for node, neighbors in _adjacency(call_edges, reverse=True).items():
            call_adj[node].update(neighbors)
        for node, neighbors in _adjacency(dependency_edges, reverse=True).items():
            dep_adj[node].update(neighbors)
    else:
        reverse = direction == "upstream"
        call_adj = _adjacency(call_edges, reverse=reverse)
        dep_adj = _adjacency(dependency_edges, reverse=reverse)

    target_is_file = target_id.startswith("file:")
    target_path = (
        target_id.removeprefix("file:")
        if target_is_file
        else target_id.removeprefix("symbol:").rsplit(":", 1)[0]
    )
    symbol_starts = (
        [
            _symbol_id(record)
            for record in symbols
            if str(record.get("path")) == target_path
        ]
        if target_is_file
        else [target_id]
    )
    call_depths, call_truncated = _walk(
        symbol_starts, call_adj, max_depth=max_depth, max_nodes=max_nodes
    )
    impacted_symbol_ids = set(call_depths)
    symbol_by_id = {_symbol_id(record): record for record in symbols}
    symbol_files = {
        str(symbol_by_id[symbol_id]["path"])
        for symbol_id in impacted_symbol_ids
        if symbol_id in symbol_by_id
    }
    file_starts = {f"file:{target_path}", *(f"file:{path}" for path in symbol_files)}
    file_depths, dependency_truncated = _walk(
        file_starts, dep_adj, max_depth=max_depth, max_nodes=max_nodes
    )
    impacted_files = sorted(
        {
            node.removeprefix("file:")
            for node in file_depths
            if node.startswith("file:")
        }
        | symbol_files
        | {target_path}
    )

    trace_by_file = {
        str(record.get("implementation")): record
        for record in traceability.get("records", ())
    }
    tests: set[str] = set()
    contracts: set[str] = set()
    routes: set[str] = set()
    for path in impacted_files:
        record = trace_by_file.get(path, {})
        tests.update(str(item) for item in record.get("tests", ()))
        contracts.update(str(item) for item in record.get("contracts", ()) if item)
        routes.update(str(item) for item in record.get("routes", ()) if item)
    services = sorted(
        {
            str(service.get("name") or service.get("id"))
            for service in runtime.get("services", ())
            if str(service.get("source", "")) in impacted_files
        }
    )

    direct_nodes = {
        node for node, depth in call_depths.items() if depth == 1
    } | {node for node, depth in file_depths.items() if depth == 1}
    all_nodes = set(call_depths) | set(file_depths)
    truncated = call_truncated or dependency_truncated
    score, level = _risk(
        direct=len(direct_nodes),
        transitive=max(0, len(all_nodes) - len(symbol_starts) - len(file_starts)),
        files=len(impacted_files),
        routes=len(routes),
        contracts=len(contracts),
        services=len(services),
        tests=len(tests),
        truncated=truncated,
    )
    impacted_symbols = [
        {
            **_symbol_candidate(symbol_by_id[node]),
            "depth": call_depths[node],
        }
        for node in sorted(impacted_symbol_ids, key=lambda item: (call_depths[item], item))
        if node in symbol_by_id and node not in symbol_starts
    ]
    file_records = [
        {
            "path": path,
            "depth": file_depths.get(f"file:{path}", 0),
            "basis": "call_or_import_graph",
        }
        for path in sorted(
            impacted_files,
            key=lambda item: (file_depths.get(f"file:{item}", 0), item),
        )
    ]
    return {
        "schema_version": "1.0",
        "valid": True,
        "target": target,
        "resolved_target": target_id,
        "target_path": target_path,
        "direction": direction,
        "map_dir": map_dir.as_posix(),
        "map_revision": manifest.get("map_revision"),
        "source_inventory_sha256": manifest.get("source_inventory_sha256"),
        "freshness_checked": require_fresh,
        "risk": {
            "level": level,
            "score": score,
            "direct_affected_nodes": len(direct_nodes),
            "transitive_affected_nodes": max(
                0, len(all_nodes) - len(symbol_starts) - len(file_starts)
            ),
            "truncated": truncated,
        },
        "affected_symbols": impacted_symbols,
        "affected_files": file_records,
        "affected_routes": sorted(routes),
        "affected_contracts": sorted(contracts),
        "affected_tests": sorted(tests),
        "affected_services": services,
        "limits": {"max_depth": max_depth, "max_nodes": max_nodes},
        "evidence": [
            "project-manifest.json",
            "symbol-index.jsonl",
            "call-graph.json",
            "dependency-graph.json",
            "traceability-map.json",
            "runtime-topology.json",
        ],
        "limitations": [
            "Static call resolution is incomplete for dynamic dispatch, reflection, generated code, and runtime dependency injection.",
            "A high/critical result requires user warning before edits; a low result does not remove the need for tests.",
        ],
    }


def validate_project_change_intelligence_orchestration(
    root: Path,
) -> dict[str, object]:
    """Validate the native mapping/impact workflow and its executable owners."""
    path = root.resolve() / "orchestration/workflows/project-change-intelligence.yaml"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [str(error)]}
    expected = (
        ("map", "map-project-intelligence", ()),
        ("retrieve", "query-project-map", ("map",)),
        ("impact", "query-project-map", ("map", "retrieve")),
        ("verify", "verify-outcome", ("impact",)),
    )
    actual = tuple(
        (
            str(step.get("id", "")),
            str(step.get("skill", "")),
            tuple(map(str, step.get("depends_on", ()))),
        )
        for step in payload.get("steps", ())
        if isinstance(step, Mapping)
    )
    errors: list[str] = []
    if payload.get("id") != "project-change-intelligence":
        errors.append("project change intelligence workflow id is invalid")
    if actual != expected:
        errors.append("project change intelligence steps are incomplete, duplicated, or out of order")
    if not str(payload.get("failure_policy", "")).strip():
        errors.append("project change intelligence failure policy is missing")
    if not (root / "contracts/project-impact.schema.json").is_file():
        errors.append("project impact receipt contract is missing")
    return {
        "valid": not errors,
        "workflow_id": payload.get("id"),
        "step_count": len(actual),
        "errors": errors,
    }
