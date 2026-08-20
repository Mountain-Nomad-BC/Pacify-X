from __future__ import annotations

from dataclasses import asdict, replace
import json

import pytest

from runtime.agent_builder import (
    GRAPH_SCHEMA_VERSION,
    NODE_ORDER,
    AgentBuilderGraph,
    agent_builder_artifacts,
    agent_builder_graph_from_mapping,
    agent_builder_graph_from_spec,
    assert_agent_builder_graph_matches_spec,
    compile_agent_builder_graph,
    normalize_agent_editor_layout,
    verify_agent_builder_artifacts,
)
from runtime.studio_models import AgentSpec


def _spec(*, lifecycle: str = "draft") -> AgentSpec:
    return AgentSpec(
        "agent:builder-demo",
        "1.2.3",
        "project:demo",
        "human:owner",
        "harness:px",
        "a" * 64,
        ("binding:capability",),
        ("grant:read",),
        ("identity", "sandbox"),
        lifecycle,
        tool_binding_ids=("binding:tool",),
        memory_binding_ids=("binding:memory",),
        handoff_agent_ids=("agent:delegate",),
        input_schema={"type": "object", "required": ["objective"]},
        output_schema={"type": "object", "required": ["result"]},
    )


def _json_value(value):
    return json.loads(json.dumps(value))


def test_agent_builder_graph_has_stable_typed_identity_and_compiles_exactly() -> None:
    spec = _spec()
    first = agent_builder_graph_from_spec(spec)
    second = agent_builder_graph_from_spec(spec)
    assert first == second
    assert first.schema_version == GRAPH_SCHEMA_VERSION
    assert [node.node_id for node in first.nodes] == [
        f"agent-node:{node.kind}" for node in first.nodes
    ]
    assert len({edge.edge_id for edge in first.edges}) == len(first.edges)
    assert all(edge.edge_id.startswith("agent-edge:") for edge in first.edges)
    assert compile_agent_builder_graph(first) == spec
    assert (
        agent_builder_graph_from_mapping(_json_value(asdict(first))) == first
    )


def test_explicit_empty_optional_node_round_trips_without_opening_connections() -> None:
    spec = replace(
        _spec(),
        tool_binding_ids=(),
        memory_binding_ids=(),
        handoff_agent_ids=(),
    )
    projected = agent_builder_graph_from_spec(spec)
    assert not {"tools", "memory", "handoffs"}.intersection(
        node.kind for node in projected.nodes
    )

    edited = agent_builder_graph_from_spec(spec, node_kinds=(*NODE_ORDER,))
    assert {"tools", "memory", "handoffs"}.issubset(
        node.kind for node in edited.nodes
    )
    assert compile_agent_builder_graph(edited) == spec
    assert edited == agent_builder_graph_from_mapping(_json_value(asdict(edited)))

    with pytest.raises(ValueError, match="incomplete or unknown"):
        agent_builder_graph_from_spec(spec, node_kinds=("tools",))


def test_agent_builder_graph_rejects_unknown_config_topology_and_spec_mismatch() -> None:
    spec = _spec()
    raw = _json_value(asdict(agent_builder_graph_from_spec(spec)))
    raw["nodes"][0]["config"]["visual_only"] = True
    with pytest.raises(ValueError, match="config keys"):
        agent_builder_graph_from_mapping(raw)

    raw = _json_value(asdict(agent_builder_graph_from_spec(spec)))
    raw["edges"][0]["relation"] = "decorates"
    with pytest.raises(ValueError, match="closed executable topology"):
        agent_builder_graph_from_mapping(raw)

    raw = _json_value(asdict(agent_builder_graph_from_spec(spec)))
    raw["nodes"].reverse()
    with pytest.raises(ValueError, match="canonical order"):
        agent_builder_graph_from_mapping(raw)

    with pytest.raises(ValueError, match="does not compile"):
        assert_agent_builder_graph_matches_spec(
            agent_builder_graph_from_spec(spec), _spec(lifecycle="candidate")
        )


def test_agent_builder_artifacts_bind_graph_layout_spec_and_authority_boundary() -> None:
    spec = _spec()
    graph = agent_builder_graph_from_spec(spec)
    graph_envelope, layout_envelope, compiler_receipt = agent_builder_artifacts(
        graph,
        spec,
        {"agent-node:identity": {"x": 15, "y": 25}},
    )
    reopened, layout = verify_agent_builder_artifacts(
        graph_envelope, layout_envelope, compiler_receipt, spec
    )
    assert reopened == graph and layout["agent-node:identity"] == {
        "x": 15.0,
        "y": 25.0,
    }
    assert compiler_receipt["authority_granted"] is False
    assert compiler_receipt["host_authority_retained"] is True

    changed = _json_value(layout_envelope)
    changed["layout"]["agent-node:identity"]["x"] = 99
    with pytest.raises(PermissionError, match="hash mismatch"):
        verify_agent_builder_artifacts(
            graph_envelope, changed, compiler_receipt, spec
        )


def test_agent_builder_layout_is_closed_and_bounded() -> None:
    graph = agent_builder_graph_from_spec(_spec())
    with pytest.raises(ValueError, match="unknown node"):
        normalize_agent_editor_layout(graph, {"agent-node:unknown": {"x": 0, "y": 0}})
    with pytest.raises(ValueError, match="bounded canvas"):
        normalize_agent_editor_layout(
            graph, {"agent-node:identity": {"x": 100_001, "y": 0}}
        )


def test_direct_graph_construction_rejects_noncanonical_node_order() -> None:
    graph = agent_builder_graph_from_spec(_spec())
    with pytest.raises(ValueError, match="canonical order"):
        AgentBuilderGraph(
            graph.schema_version,
            graph.agent_id,
            tuple(reversed(graph.nodes)),
            graph.edges,
        )
