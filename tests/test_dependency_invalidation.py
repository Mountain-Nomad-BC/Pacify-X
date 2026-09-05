from __future__ import annotations

import copy
from pathlib import Path

import pytest

from runtime.dependency_invalidation import (
    adapt_generated_dependency_graph,
    build_dependency_graph,
    compute_invalidation_cone,
    load_dependency_authority,
    validate_dependency_authority,
)
from runtime.project_impact import as_invalidation_inputs


ROOT = Path(__file__).resolve().parents[1]


def _graph():
    nodes = [
        {"node_id": "source:a", "kind": "source", "revision": "1"},
        {"node_id": "skill:b", "kind": "skill", "revision": "1"},
        {"node_id": "projection:c", "kind": "projection", "revision": "1"},
        {"node_id": "test:d", "kind": "test", "revision": "1"},
        {"node_id": "section:e", "kind": "section", "revision": "1"},
        {"node_id": "release:f", "kind": "release_evidence", "revision": "1"},
    ]
    edges = [
        {"dependency": "source:a", "consumer": "skill:b"},
        {"dependency": "skill:b", "consumer": "projection:c"},
        {"dependency": "projection:c", "consumer": "test:d"},
        {"dependency": "test:d", "consumer": "section:e"},
        {"dependency": "section:e", "consumer": "release:f"},
    ]
    return build_dependency_graph(ROOT, nodes, edges)


def test_live_dependency_authority_covers_every_required_kind() -> None:
    report = validate_dependency_authority(ROOT)
    assert report["valid"], report["errors"]
    assert report["node_kind_count"] == 11


def test_revision_drift_propagates_transitively_and_retains_history() -> None:
    result = compute_invalidation_cone(
        _graph(),
        {"source:a": "2"},
        authority=load_dependency_authority(ROOT),
    )
    assert result["seed_nodes"] == ["source:a"]
    assert result["direct_consumers"] == ["skill:b"]
    assert result["transitive_consumers"][-1] == "release:f"
    assert result["historical_records_retained"] is True
    assert all(item["required_rebuild_gate"] for item in result["stale_nodes"])


def test_unknown_nodes_and_undeclared_cycles_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown dependency edge"):
        build_dependency_graph(
            ROOT,
            [{"node_id": "source:a", "kind": "source", "revision": "1"}],
            [{"dependency": "source:a", "consumer": "missing"}],
        )
    with pytest.raises(ValueError, match="undeclared dependency cycles"):
        build_dependency_graph(
            ROOT,
            [
                {"node_id": "source:a", "kind": "source", "revision": "1"},
                {"node_id": "source:b", "kind": "source", "revision": "1"},
            ],
            [
                {"dependency": "source:a", "consumer": "source:b"},
                {"dependency": "source:b", "consumer": "source:a"},
            ],
        )


def test_missing_invalidation_owner_fails_closed() -> None:
    policy = load_dependency_authority(ROOT)
    policy = copy.deepcopy(policy)
    del policy["node_kinds"][0]["invalidation_owner"]
    report = validate_dependency_authority(ROOT, policy)
    assert not report["valid"]
    assert any("missing invalidation_owner" in error for error in report["errors"])


def test_generated_graph_and_project_impact_adapters_are_deterministic() -> None:
    generated = {"edges": [{"from": "source:a", "to": "source:b"}]}
    nodes, edges = adapt_generated_dependency_graph(
        generated, revisions={"source:a": "1", "source:b": "1"}
    )
    assert [item["node_id"] for item in nodes] == ["source:a", "source:b"]
    assert edges == [{"dependency": "source:a", "consumer": "source:b"}]

    impact = {
        "valid": True,
        "resolved_target": "file:runtime/a.py",
        "affected_files": [{"path": "runtime/b.py"}],
        "affected_tests": ["tests/test_b.py"],
    }
    revisions = {
        "file:runtime/a.py": "1",
        "file:runtime/b.py": "1",
        "test:tests/test_b.py": "1",
    }
    impact_nodes, impact_edges = as_invalidation_inputs(
        impact, revision_bindings=revisions
    )
    assert len(impact_nodes) == 3
    assert len(impact_edges) == 2
