"""Canonical architecture-atlas parity and integrity checks."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import hashlib
import pytest
from docs.architecture.tools import build_atlas


ROOT = Path(__file__).resolve().parents[1]
@pytest.fixture(scope="module", autouse=True)
def current_atlas(tmp_path_factory):
    """Build from admitted declarations and measured bytes, without old graphs."""
    global ATLAS, BASELINE, SHARD_MANIFEST, NODES, EDGES, SYSTEMS, RELATIONSHIPS, METRICS
    workspace = tmp_path_factory.mktemp("current-atlas")
    repo = workspace / "source"
    repo.mkdir()
    for relative in ("policies/rev1xx-validation.json", "policies/release-artifact-policy.json", "tests/test_architecture_atlas.py", "runtime/cli.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for source in (ROOT / "registry/planning/rev1xx").glob("*.json"):
        if re.fullmatch(r"[0-9a-f]{64}\.json", source.name):
            value = json.loads(source.read_bytes())
            if value.get("schema_version") == "px.rev1xx-punch-cards/1.0":
                target = repo / "registry/planning/rev1xx" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    rows, _, _ = build_atlas.inventory(repo, 100000, 2 * 1024**3)
    BASELINE, _ = build_atlas.current_declaration_model(repo, rows)
    ATLAS = workspace / "atlas"
    build_atlas.build(repo, ATLAS, workspace / "absent-historical-reference")
    SHARD_MANIFEST = _json("data/node_shards_manifest.json")
    NODES = [node for shard in SHARD_MANIFEST["shards"] for node in _jsonl(shard["path"])]
    EDGES = _jsonl("data/edges.jsonl")
    SYSTEMS = _json("data/canonical_systems.json")
    RELATIONSHIPS = _json("data/canonical_relationships.json")
    METRICS = _json("data/metrics.json")
    yield repo


def _json(path: str):
    return json.loads((ATLAS / path).read_text(encoding="utf-8"))


def _jsonl(path: str):
    return [
        json.loads(line)
        for line in (ATLAS / path).read_text(encoding="utf-8").splitlines()
    ]


def test_preserves_every_canonical_system_id() -> None:
    assert {node["id"] for node in BASELINE["nodes"]} == {
        node["id"] for node in SYSTEMS
    }


def test_preserves_every_semantic_edge_id_and_endpoints() -> None:
    expected = {
        edge["id"]: (edge["source"], edge["target"]) for edge in BASELINE["edges"]
    }
    actual = {
        edge["id"]: (edge["source"], edge["target"])
        for edge in RELATIONSHIPS
        if edge["id"] in expected
    }
    assert actual == expected


def test_unique_node_and_edge_ids() -> None:
    for rows in (NODES, EDGES):
        assert len(rows) == len({row["id"] for row in rows})


def test_no_dangling_edges() -> None:
    identifiers = {node["id"] for node in NODES}
    assert all(
        edge["source"] in identifiers and edge["target"] in identifiers
        for edge in EDGES
    )


def test_system_nodes_use_structured_canonical_data() -> None:
    systems = [node for node in NODES if node["kind"] == "system"]
    assert systems
    assert all(node.get("note") is None for node in systems)


def test_source_file_denominator_is_exact_and_nonrecursive() -> None:
    rows = json.loads(
        (ATLAS / "data/source_inventory.json").read_text(encoding="utf-8")
    )
    paths = {row["path"] for row in rows}
    assert paths == {node["path"] for node in NODES if node["kind"] == "file"}
    assert len(rows) == METRICS["files"]
    assert "tests/test_architecture_atlas.py" in paths
    assert not any(path.startswith("docs/architecture/") for path in paths)
    assert not any(path.startswith(".tmp/") for path in paths)


def test_generated_text_has_no_common_mojibake() -> None:
    markers = ("â€”", "â€“", "Â·", "ï¿½", "\ufffd")
    checked_suffixes = {".md", ".json", ".jsonl", ".js", ".html", ".css"}
    corrupt = []
    for path in ATLAS.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in checked_suffixes
            and "reference" not in path.relative_to(ATLAS).parts
        ):
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in markers):
                corrupt.append(path.relative_to(ATLAS).as_posix())
    assert corrupt == []


def test_layout_is_complete_and_finite() -> None:
    assert all(
        len(node["position"]) == 3
        and all(math.isfinite(value) for value in node["position"])
        for node in NODES
    )


def test_all_flow_steps_exist() -> None:
    identifiers = {node["id"] for node in BASELINE["nodes"]}
    assert all(
        step in identifiers
        for flow in _json("data/canonical_flows.json")
        for step in flow["steps"]
    )


def test_exact_views_cameras_and_journeys() -> None:
    assert len(_json("data/views.json")) == 11
    assert len(_json("data/cameras.json")) == 11
    assert len(_json("data/journeys.json")) == 12


def test_no_fabricated_runtime_or_certification() -> None:
    assert all(
        node.get("runtime_observed") is False and node.get("certified") is False
        for node in NODES
    )


def test_offline_viewer_has_no_external_dependency() -> None:
    assets = "\n".join(
        (ATLAS / path).read_text(encoding="utf-8")
        for path in ("index.html", "viewer.js", "viewer.css")
    )
    assert re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', assets) is None


def test_layer_membership_is_total() -> None:
    layers = {layer["id"] for layer in BASELINE["layers"]}
    assert all(node["layer"] in layers for node in NODES)


def test_preserves_original_flows_and_findings() -> None:
    assert _json("data/canonical_flows.json") == BASELINE["flows"]
    assert _json("data/canonical_findings.json") == BASELINE["findings"]


def test_node_shards_are_complete_bounded_and_content_bound() -> None:
    import hashlib

    assert len(SHARD_MANIFEST["shards"]) == 16
    assert SHARD_MANIFEST["records"] == len(NODES) == METRICS["nodes_total"]
    assert {
        path.relative_to(ATLAS).as_posix()
        for path in (ATLAS / "data/node_shards").glob("*.jsonl")
    } == {shard["path"] for shard in SHARD_MANIFEST["shards"]}
    for shard in SHARD_MANIFEST["shards"]:
        payload = (ATLAS / shard["path"]).read_bytes()
        assert len(payload) == shard["bytes"] <= 4 * 1024**2
        assert hashlib.sha256(payload).hexdigest() == shard["sha256"]
        assert len(payload.splitlines()) == shard["records"]


def test_all_generated_wiki_links_resolve() -> None:
    unresolved = []
    for note in (ATLAS / "vault").rglob("*.md"):
        for match in re.finditer(
            r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", note.read_text(encoding="utf-8")
        ):
            target = match.group(1)
            if not (ATLAS / "vault" / (target + ".md")).is_file():
                unresolved.append((str(note), target))
    assert unresolved == []


def test_current_source_hashes_are_independently_bound(current_atlas):
    for row in _json("data/source_inventory.json"):
        assert hashlib.sha256((current_atlas / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    assert len(SYSTEMS) == 60
    assert all(node["implementation_verified"] is False for node in SYSTEMS)
    assert BASELINE["metadata"]["historical_prerequisites"] is False


def test_current_declarations_reject_post_capture_change(current_atlas):
    rows, _, _ = build_atlas.inventory(current_atlas, 100000, 2 * 1024**3)
    policy = current_atlas / "policies/rev1xx-validation.json"
    original = policy.read_bytes()
    try:
        policy.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="policy changed"):
            build_atlas.current_declaration_model(current_atlas, rows)
    finally:
        policy.write_bytes(original)


def test_current_atlas_rejects_ambiguous_declarations(current_atlas):
    source = next((current_atlas / "registry/planning/rev1xx").glob("*.json"))
    value = json.loads(source.read_bytes())
    value["cards"][0]["title"] += " competing input"
    payload = json.dumps(value, sort_keys=True).encode()
    competitor = source.parent / (hashlib.sha256(payload).hexdigest() + ".json")
    try:
        competitor.write_bytes(payload)
        rows, _, _ = build_atlas.inventory(current_atlas, 100000, 2 * 1024**3)
        with pytest.raises(ValueError, match="unambiguous"):
            build_atlas.current_declaration_model(current_atlas, rows)
    finally:
        competitor.unlink()
