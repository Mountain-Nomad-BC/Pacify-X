"""Typed metadata graph spanning skills, capabilities, builders, tools, models, knowledge, and integrations."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AssetNode:
    node_id: str
    asset_type: str
    status: str


@dataclass(frozen=True, slots=True)
class AssetEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True, slots=True)
class SystemGraph:
    nodes: tuple[AssetNode, ...]
    edges: tuple[AssetEdge, ...]


def _json(root: Path, name: str) -> dict:
    return json.loads((root / "registry" / name).read_text(encoding="utf-8"))


def build_system_graph(root: Path) -> SystemGraph:
    root = root.resolve()
    nodes: dict[str, AssetNode] = {}
    uses: list[tuple[str, str]] = []

    def add(node_id: str, asset_type: str, status: str, targets=()) -> None:
        if node_id in nodes:
            raise ValueError(f"duplicate system-graph node: {node_id}")
        nodes[node_id] = AssetNode(node_id, asset_type, status)
        uses.extend((node_id, str(target)) for target in targets)

    capability_map = _json(root, "capability_map.json")
    for item in capability_map.get("active_capabilities", ()):
        contract = json.loads((root / item["contract"]).read_text(encoding="utf-8"))
        add(item["id"], "capability", "active", contract.get("dependencies", ()))
    catalog = tomllib.loads((root / "registry/skill_catalog.toml").read_text(encoding="utf-8"))
    for item in catalog.get("skills", ()):
        # A runtime capability may also expose a lazy skill interface under the
        # same canonical identifier. Represent that shared identity once.
        if item["id"] in nodes and nodes[item["id"]].asset_type == "capability":
            continue
        add(item["id"], "skill", item["status"], (item["admission_record"],) if item["admission_record"] != item["id"] else ())
    for name, key, asset_type in (
        ("builders.json", "builders", "builder"), ("tools.json", "tools", "tool"),
        ("knowledge_sources.json", "knowledge_sources", "knowledge"), ("integrations.json", "integrations", "integration"),
    ):
        for item in _json(root, name).get(key, ()):
            add(item["id"], asset_type, item.get("status", "active"), item.get("uses", ()))
    for item in _json(root, "models.json").get("models", ()):
        add(item["model_id"], "model", "available" if item["available"] else "unavailable")

    edges: list[AssetEdge] = []
    for source, target in uses:
        if target not in nodes:
            raise ValueError(f"unknown system-graph target: {source} -> {target}")
        edges.append(AssetEdge(source, target, "uses"))
    return SystemGraph(tuple(sorted(nodes.values(), key=lambda item: (item.asset_type, item.node_id))), tuple(sorted(edges, key=lambda item: (item.source, item.target, item.relation))))
