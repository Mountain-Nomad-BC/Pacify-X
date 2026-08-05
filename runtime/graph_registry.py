"""Deterministic builders and freshness checks for canonical registry graphs."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from .graphs import build_graphs
from .system_graph import build_system_graph


GENERATOR = "engineering_bootstrap.graph_registry/1.0.0"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _render(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_graph_artifacts(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    active = _load(root / "registry" / "capability_map.json")["active_capabilities"]
    contracts = [_load(root / item["contract"]) for item in active]
    graphs = build_graphs(contracts)
    artifacts: dict[str, bytes] = {}
    for name, edges in {
        "capability_graph.json": graphs.capability_edges,
        "io_graph.json": graphs.io_edges,
        "dependency_effect_graph.json": graphs.dependency_effect_edges,
    }.items():
        artifacts[name] = _render(
            {
                "schema_version": "1.0",
                "generator": GENERATOR,
                "nodes": graphs.capability_nodes,
                "edges": [asdict(edge) for edge in edges],
            }
        )
    system = build_system_graph(root)
    artifacts["system_asset_graph.json"] = _render(
        {
            "schema_version": "1.0",
            "generator": GENERATOR,
            "nodes": [asdict(item) for item in system.nodes],
            "edges": [asdict(item) for item in system.edges],
        }
    )
    orchestrations = _load(root / "registry" / "project_stream_orchestrations.json")[
        "orchestrations"
    ]
    edges: list[dict[str, Any]] = []
    nodes: set[str] = set()
    for orchestration in sorted(
        orchestrations, key=lambda item: item["orchestration_id"]
    ):
        source = orchestration["orchestration_id"]
        nodes.add(source)
        for order, target in enumerate(orchestration.get("skills", ())):
            nodes.add(target)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": "executes",
                    "order": order,
                }
            )
        for order, target in enumerate(orchestration.get("deferred_capabilities", ())):
            nodes.add(target)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": "deferred_enhancement",
                    "order": order,
                }
            )
    edges.sort(
        key=lambda item: (
            item["source"],
            item["relation"],
            item["order"],
            item["target"],
        )
    )
    artifacts["project_stream_dependency_graph.json"] = _render(
        {
            "schema_version": "2.0",
            "generator": GENERATOR,
            "orchestration_count": len(orchestrations),
            "node_count": len(nodes),
            "capability_reference_count": len(edges),
            "nodes": sorted(nodes),
            "edges": edges,
        }
    )
    source_paths = {
        "registry/capability_map.json",
        "registry/skill_catalog.toml",
        "registry/builders.json",
        "registry/tools.json",
        "registry/models.json",
        "registry/knowledge_sources.json",
        "registry/integrations.json",
        "registry/project_stream_orchestrations.json",
        "registry/agency_agent_registry.json",
        "registry/agency_agent_graph.json",
        *(str(item["contract"]) for item in active),
    }
    sources = [
        {"path": path, "sha256": _sha(root / path)} for path in sorted(source_paths)
    ]
    outputs = [
        {
            "path": f"registry/graphs/{name}",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for name, payload in sorted(artifacts.items())
    ]
    artifacts["graph_manifest.json"] = _render(
        {
            "schema_version": "1.0",
            "generator": GENERATOR,
            "policy": "derived metadata projection; regenerate and byte-compare before release",
            "sources": sources,
            "outputs": outputs,
        }
    )
    return artifacts


def write_graph_artifacts(root: Path, output: Path | None = None) -> dict[str, Any]:
    output = (output or root / "registry" / "graphs").resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_graph_artifacts(root)
    for name, payload in artifacts.items():
        (output / name).write_bytes(payload)
    return {
        "valid": True,
        "output": output.as_posix(),
        "artifact_count": len(artifacts),
    }


def validate_graph_artifacts(root: Path) -> dict[str, Any]:
    expected = build_graph_artifacts(root)
    graph_root = root / "registry" / "graphs"
    errors: list[str] = []
    actual_names = {path.name for path in graph_root.glob("*.json")}
    if actual_names != set(expected):
        errors.append(
            f"graph file set mismatch: expected {sorted(expected)}, found {sorted(actual_names)}"
        )
    for name, payload in expected.items():
        path = graph_root / name
        if not path.is_file() or path.read_bytes() != payload:
            errors.append(f"stale graph artifact: {name}")
    return {
        "valid": not errors,
        "artifact_count": len(expected),
        "generator": GENERATOR,
        "errors": errors,
    }
