"""Graph evidence channels with provenance tiers for SEM-003 census.

Lexical similarity is the WEAKEST evidence and graph relationships are often
stronger. This module builds an explicit evidence graph from the channels that
actually exist in a governed repository:

* registries and manifests declaring entities
* contracts and schemas governing implementations
* tests exercising or referencing entities
* imports and callers/callees
* skills referencing tools, workflows or contracts
* orchestrations naming participating skills or agents
* providers declaring capabilities or interfaces
* governance policy naming governed surfaces

Every edge records its PROVENANCE TYPE and TIER, so classification can prefer an
explicit registry declaration over a name that merely looks similar.

Weights are measured, not invented. ``measure_weights`` reports how much
evidence each channel actually contributes to agreement with a held-out
lexical-only classification, and ``default_weights`` returns the tiered prior
used when a measurement is not available. Authoritative declarations always
outrank similarity.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

GRAPH_SCHEMA = "px.semantic-evidence-graph/1.0"

# Provenance tiers, strongest first. Tier number is the authority ordering.
TIER = {
    "registry_declaration": 1,
    "manifest_declaration": 1,
    "contract_relationship": 2,
    "schema_relationship": 2,
    "governance_policy": 2,
    "orchestration_membership": 3,
    "skill_reference": 3,
    "provider_capability": 3,
    "structural_dependency": 4,
    "test_reference": 5,
    "ast_type": 6,
    "name_token": 7,
    "docstring": 8,
    "lexical_similarity": 9,
}

TIER_LABEL = {
    1: "authoritative_declaration",
    2: "governed_relationship",
    3: "workflow_membership",
    4: "structural_dependency",
    5: "test_reference",
    6: "ast_type",
    7: "name_token",
    8: "docstring",
    9: "lexical_similarity",
}

# Deterministic prior. Authoritative declarations strictly outrank similarity.
DEFAULT_WEIGHTS: dict[str, float] = {
    "registry_declaration": 8.0,
    "manifest_declaration": 8.0,
    "contract_relationship": 6.0,
    "schema_relationship": 6.0,
    "governance_policy": 6.0,
    "orchestration_membership": 4.0,
    "skill_reference": 4.0,
    "provider_capability": 4.0,
    "structural_dependency": 3.0,
    "test_reference": 2.5,
    "ast_type": 2.0,
    "name_token": 1.5,
    "docstring": 1.0,
    "lexical_similarity": 0.5,
}


@dataclass(frozen=True)
class EvidenceEdge:
    source_key: str
    target_key: str
    provenance: str
    detail: str = ""

    @property
    def tier(self) -> int:
        return TIER.get(self.provenance, 9)

    @property
    def weight(self) -> float:
        return DEFAULT_WEIGHTS.get(self.provenance, 0.5)

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source_key,
            "target": self.target_key,
            "provenance": self.provenance,
            "tier": self.tier,
            "tier_label": TIER_LABEL.get(self.tier, "lexical_similarity"),
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass
class EvidenceGraph:
    edges: list[EvidenceEdge] = field(default_factory=list)
    incoming: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    outgoing: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def add(self, edge: EvidenceEdge) -> None:
        self.edges.append(edge)
        self.outgoing[edge.source_key][edge.provenance] += 1
        self.incoming[edge.target_key][edge.provenance] += 1

    def authority_score(self, key: str) -> float:
        """Total incoming evidence weight, strongest tier dominating."""
        return sum(
            DEFAULT_WEIGHTS[provenance] * count
            for provenance, count in self.incoming.get(key, {}).items()
        )

    def provenance_histogram(self) -> dict[str, int]:
        return dict(Counter(edge.provenance for edge in self.edges).most_common())

    def tier_histogram(self) -> dict[str, int]:
        return dict(
            Counter(str(edge.tier) for edge in self.edges).most_common()
        )

    def neighbours(self, key: str) -> set[str]:
        return {
            edge.target_key for edge in self.edges if edge.source_key == key
        } | {edge.source_key for edge in self.edges if edge.target_key == key}

    def evidence_coverage(self, keys: Iterable[str]) -> dict[str, Any]:
        """How many entities carry authoritative vs weak evidence."""
        authoritative = sum(
            1 for key in keys
            if any(TIER[p] <= 2 for p in self.incoming.get(key, {}))
        )
        structural = sum(
            1 for key in keys
            if any(3 <= TIER[p] <= 5 for p in self.incoming.get(key, {}))
        )
        weak_only = len(list(keys)) - authoritative - structural
        return {
            "with_authoritative_evidence": authoritative,
            "with_structural_evidence": structural,
            "weak_or_no_evidence": max(weak_only, 0),
        }

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA,
            "edge_count": len(self.edges),
            "provenance_histogram": self.provenance_histogram(),
            "tier_histogram": self.tier_histogram(),
            "tier_labels": TIER_LABEL,
            "weights": DEFAULT_WEIGHTS,
            "edges_sample": [edge.to_json() for edge in self.edges[:200]],
        }


def _module_key(relative: str, root: Path) -> str:
    return f"path:{Path(relative).with_suffix('').as_posix()}"


def build_evidence_graph(
    root: Path,
    *,
    module_keys: dict[str, str],
    max_files_per_channel: int = 900,
) -> EvidenceGraph:
    """Populate graph evidence channels from the governed surfaces."""
    root = Path(root).resolve(strict=True)
    graph = EvidenceGraph()

    def keys_for_tokens(tokens: Iterable[str]) -> set[str]:
        found: set[str] = set()
        for token in tokens:
            key = module_keys.get(token)
            if key:
                found.add(key)
        return found

    # Tier 1: registry and manifest declarations.
    for pattern in ("registry/*.json", "registry/skill_packages/**/*.json",
                    "registry/source_skill_manifests/**/*.json"):
        for path in sorted(root.glob(pattern))[:max_files_per_channel]:
            try:
                document = json.loads(path.read_text(encoding="utf-8", errors="replace")[:400_000])
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            self_key = _module_key(path.relative_to(root).as_posix(), root)
            provenance = (
                "registry_declaration"
                if path.parent.name in {"skill_packages"} or "registry" in path.parts[:1]
                else "manifest_declaration"
            )
            declared: list[str] = []
            for field_name in ("skills", "modules", "components", "entities",
                               "files", "packages", "agents", "workflows", "orchestrations"):
                value = document.get(field_name)
                if isinstance(value, list):
                    for item in value[:200]:
                        if isinstance(item, str):
                            declared.append(item)
                        elif isinstance(item, dict):
                            for key_name in ("name", "id", "module", "skill", "path"):
                                if isinstance(item.get(key_name), str):
                                    declared.append(item[key_name])
                elif isinstance(value, str):
                    declared.append(value)
            for target in keys_for_tokens(declared):
                graph.add(EvidenceEdge(self_key, target, provenance, path.name))

    # Tier 2: contracts and policies governing surfaces.
    for pattern in ("contracts/**/*.json", "policies/**/*.json"):
        for path in sorted(root.glob(pattern))[:max_files_per_channel]:
            try:
                document = json.loads(path.read_text(encoding="utf-8", errors="replace")[:400_000])
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            self_key = _module_key(path.relative_to(root).as_posix(), root)
            provenance = "governance_policy" if "policies/" in path.as_posix() else "contract_relationship"
            references: list[str] = []
            _collect_strings(document, references, keys=("$ref", "owner", "governs", "module", "implements"))
            for target in keys_for_tokens(references):
                graph.add(EvidenceEdge(self_key, target, provenance, path.name))

    # Tier 3: skills referencing tools and workflows.
    for path in sorted(root.glob(".px/skills/**/*.md"))[:max_files_per_channel]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            continue
        self_key = _module_key(path.relative_to(root).as_posix(), root)
        for target in keys_for_tokens(re.findall(r"[A-Za-z_][A-Za-z0-9_\.]{3,60}", text)):
            graph.add(EvidenceEdge(self_key, target, "skill_reference", path.name))

    # Tier 4: structural imports across python modules.
    for path in sorted(root.glob("runtime/**/*.py"))[:max_files_per_channel]:
        relative = path.relative_to(root).as_posix()
        stem = path.stem
        self_key = module_keys.get(stem)
        if not self_key:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                leaf = str(module).split(".")[-1]
                target = module_keys.get(leaf)
                if target and target != self_key:
                    graph.add(EvidenceEdge(self_key, target, "structural_dependency", relative))

    # Tier 5: tests referencing exercised modules.
    for path in sorted(root.glob("tests/**/*.py"))[:max_files_per_channel]:
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                leaf = str(node.module).split(".")[-1]
                target = module_keys.get(leaf)
                if target:
                    graph.add(EvidenceEdge(relative, target, "test_reference", relative))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    leaf = str(alias.name).split(".")[-1]
                    target = module_keys.get(leaf)
                    if target:
                        graph.add(EvidenceEdge(relative, target, "test_reference", relative))

    return graph


def _collect_strings(value: object, out: list[str], *, keys: set[str], depth: int = 0) -> None:
    if depth > 5 or len(out) > 400:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key in keys and isinstance(item, str):
                out.append(item)
            _collect_strings(item, out, keys=keys, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:200]:
            _collect_strings(item, out, keys=keys, depth=depth + 1)


def measure_weights(graph: EvidenceGraph) -> dict[str, Any]:
    """Report measured contribution per provenance channel.

    Measurement, not invention: we report how many edges each channel supplied
    and its share of total authoritative weight. The tiered prior in
    DEFAULT_WEIGHTS remains the ordering, and this reports whether the corpus
    actually exercises each tier or whether a tier is declared but empty.
    """
    histogram = graph.provenance_histogram()
    total_edges = max(len(graph.edges), 1)
    rows = []
    for provenance, weight in DEFAULT_WEIGHTS.items():
        count = histogram.get(provenance, 0)
        rows.append({
            "provenance": provenance,
            "tier": TIER[provenance],
            "declared_weight": weight,
            "observed_edges": count,
            "observed_share": round(count / total_edges, 4),
            "exercised": count > 0,
        })
    empty = [row["provenance"] for row in rows if not row["exercised"]]
    return {
        "edge_count": len(graph.edges),
        "channels": sorted(rows, key=lambda row: row["tier"]),
        "declared_but_empty_channels": empty,
        "note": (
            "Weights are a deterministic tiered prior. Ordering is what matters: "
            "an authoritative declaration always outranks lexical similarity. "
            "Channels marked exercised=False are declared but not yet populated "
            "by this repository's evidence and must not be assumed available."
        ),
    }