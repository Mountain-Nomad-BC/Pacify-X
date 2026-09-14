from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
import json

import pytest

from runtime import agent_builder as builder
from runtime.studio_models import AgentSpec


def spec():
    return AgentSpec(
        "agent:bounded-builder",
        "1.2.3",
        "project:demo",
        "human:owner",
        "harness:px",
        "a" * 64,
        ("binding:capability",),
        ("grant:read",),
        ("identity", "sandbox"),
        "draft",
        tool_binding_ids=("binding:tool",),
        memory_binding_ids=("binding:memory",),
        handoff_agent_ids=("agent:delegate",),
    )


def raw_graph():
    return json.loads(json.dumps(asdict(builder.agent_builder_graph_from_spec(spec()))))


@pytest.mark.parametrize(
    "value",
    [False, 0, "", [], ()],
    ids=["false", "zero", "empty-text", "array", "tuple"],
)
def test_falsey_layout_is_not_an_empty_object(value):
    graph = builder.agent_builder_graph_from_spec(spec())
    with pytest.raises(ValueError):
        builder.normalize_agent_editor_layout(graph, value)


@pytest.mark.parametrize(
    "value",
    [True, "12", None, float("nan"), float("inf"), -float("inf")],
    ids=["bool", "text", "null", "nan", "positive-inf", "negative-inf"],
)
def test_layout_coordinates_are_actual_finite_numbers(value):
    graph = builder.agent_builder_graph_from_spec(spec())
    with pytest.raises(ValueError):
        builder.normalize_agent_editor_layout(
            graph, {"agent-node:identity": {"x": value}}
        )


def test_layout_only_change_preserves_graph_and_spec_identity():
    current = spec()
    graph = builder.agent_builder_graph_from_spec(current)
    assert builder.normalize_agent_editor_layout(
        graph, None
    ) == builder.normalize_agent_editor_layout(graph, {})
    before = builder.agent_builder_artifacts(graph, current)
    after = builder.agent_builder_artifacts(
        graph, current, {"agent-node:identity": {"x": 100, "y": -50}}
    )
    assert before[0] == after[0]
    assert before[2]["agent_spec_sha256"] == after[2]["agent_spec_sha256"]
    assert before[1]["layout_sha256"] != after[1]["layout_sha256"]
    assert before[2]["receipt_sha256"] != after[2]["receipt_sha256"]
    assert builder.verify_agent_builder_artifacts(*after, current)[0] == graph


@pytest.mark.parametrize(
    "field", ["deterministic", "authority_granted", "host_authority_retained"]
)
def test_numeric_receipt_flags_cannot_equal_authority_booleans(field):
    current = spec()
    records = builder.agent_builder_artifacts(
        builder.agent_builder_graph_from_spec(current), current
    )
    receipt = dict(records[2])
    receipt[field] = int(receipt[field])
    with pytest.raises((ValueError, PermissionError)):
        builder.verify_agent_builder_artifacts(records[0], records[1], receipt, current)


class Coercible:
    def __str__(self):
        raise AssertionError("opaque value was coerced")


def test_port_fields_are_checked_before_string_coercion():
    with pytest.raises(ValueError):
        builder.AgentBuilderPort(Coercible(), "output", "definition")


@pytest.mark.parametrize(
    "kind,key,value",
    [
        ("capabilities", "binding_ids", "ab"),
        ("capabilities", "binding_ids", [True]),
        ("authority", "grant_ids", {"grant:read": True}),
        ("tests", "test_ids", [123]),
        ("identity", "owner", True),
        ("harness", "harness_id", 123),
    ],
    ids=[
        "binding-string",
        "binding-bool",
        "grant-mapping",
        "test-integer",
        "owner-bool",
        "harness-integer",
    ],
)
def test_node_config_types_refuse_before_canonical_encoding(
    monkeypatch, kind, key, value
):
    raw = raw_graph()
    row = next(x for x in raw["nodes"] if x["kind"] == kind)
    row["config"][key] = value
    original = builder.canonical_bytes
    calls = []

    def tracked(payload):
        calls.append(payload)
        return original(payload)

    monkeypatch.setattr(builder, "canonical_bytes", tracked)
    with pytest.raises(ValueError):
        builder.AgentBuilderNode(
            row["node_id"], kind, builder.PORTS_BY_KIND[kind], row["config"]
        )
    assert calls == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_output_tokens", True),
        ("max_output_tokens", "64"),
        ("temperature", "0.5"),
        ("temperature", True),
        ("family", 123),
        ("vendor", False),
    ],
)
def test_model_fields_reject_coercion(key, value):
    raw = raw_graph()
    model = next(x for x in raw["nodes"] if x["kind"] == "model")
    model["config"]["model"][key] = value
    with pytest.raises(ValueError):
        builder.agent_builder_graph_from_mapping(raw)


@pytest.mark.parametrize("which", ["nodes", "edges", "ports", "bindings"])
def test_raw_count_limits_precede_serialization(monkeypatch, which):
    raw = raw_graph()
    if which == "nodes":
        raw["nodes"] *= 2
    elif which == "edges":
        raw["edges"] *= 2
    elif which == "ports":
        raw["nodes"][0]["ports"] *= 4
    else:
        row = next(x for x in raw["nodes"] if x["kind"] == "capabilities")
        row["config"]["binding_ids"] = [f"binding:{i}" for i in range(257)]

    def forbidden(_):
        raise AssertionError("full canonical serialization before count refusal")

    monkeypatch.setattr(builder, "canonical_bytes", forbidden)
    with pytest.raises(ValueError):
        if which == "bindings":
            builder.AgentBuilderNode(
                row["node_id"],
                row["kind"],
                builder.PORTS_BY_KIND["capabilities"],
                row["config"],
            )
        else:
            builder.agent_builder_graph_from_mapping(raw)


@pytest.mark.parametrize(
    "mutation", ["required-string", "property-scalar", "type-list", "additional-text"]
)
def test_contract_shape_is_strict_before_compilation(mutation):
    raw = raw_graph()
    schema = next(x for x in raw["nodes"] if x["kind"] == "contracts")["config"][
        "input_schema"
    ]
    if mutation == "required-string":
        schema["required"] = "objective"
    elif mutation == "property-scalar":
        schema["properties"] = {"objective": "string"}
    elif mutation == "type-list":
        schema["properties"] = {"objective": {"type": ["string", "null"]}}
    else:
        schema["additionalProperties"] = "false"
    with pytest.raises(ValueError):
        builder.agent_builder_graph_from_mapping(raw)


def test_schema_size_refuses_before_full_canonical_encoding(monkeypatch):
    raw = raw_graph()
    row = next(x for x in raw["nodes"] if x["kind"] == "contracts")
    row["config"]["input_schema"]["description"] = "x" * 65536

    def forbidden(_):
        raise AssertionError("oversized schema fully serialized")

    monkeypatch.setattr(builder, "canonical_bytes", forbidden)
    with pytest.raises(ValueError):
        builder.AgentBuilderNode(
            row["node_id"],
            row["kind"],
            builder.PORTS_BY_KIND["contracts"],
            row["config"],
        )


@pytest.mark.parametrize("mode", ["compile", "artifacts", "layout"])
def test_mutated_nested_configuration_is_revalidated(mode):
    current = spec()
    graph = builder.agent_builder_graph_from_spec(current)
    graph.node("capabilities").config["binding_ids"] = "ab"
    with pytest.raises(ValueError):
        if mode == "compile":
            builder.compile_agent_builder_graph(graph)
        elif mode == "artifacts":
            builder.agent_builder_artifacts(graph, current)
        else:
            builder.normalize_agent_editor_layout(graph)


def test_graph_constructor_does_not_retain_external_node_config_aliases():
    original = builder.agent_builder_graph_from_spec(spec())
    snapshot = builder.AgentBuilderGraph(
        original.schema_version, original.agent_id, original.nodes, original.edges
    )
    original.node("identity").config["owner"] = "different:owner"
    assert snapshot.node("identity").config["owner"] == "human:owner"


def test_opaque_mapping_refuses_without_iteration():
    class Opaque(Mapping):
        def __getitem__(self, key):
            raise AssertionError("opaque getter invoked")

        def __iter__(self):
            raise AssertionError("opaque mapping iterated")

        def __len__(self):
            return 4

    with pytest.raises(ValueError):
        builder.agent_builder_graph_from_mapping(Opaque())


def test_node_kind_generator_is_not_materialized():
    def values():
        raise AssertionError("unbounded iterator consumed")
        yield "identity"

    with pytest.raises(ValueError):
        builder.agent_builder_graph_from_spec(spec(), node_kinds=values())


def test_populated_optional_bindings_cannot_be_hidden_by_visual_selection():
    current = spec()
    required = tuple(
        k for k in builder.NODE_ORDER if k not in builder.OPTIONAL_NODE_KINDS
    )
    graph = builder.agent_builder_graph_from_spec(current, node_kinds=required)
    assert all(graph.node(k) is not None for k in builder.OPTIONAL_NODE_KINDS)
    assert builder.compile_agent_builder_graph(graph) == current
    empty = replace(
        current, tool_binding_ids=(), memory_binding_ids=(), handoff_agent_ids=()
    )
    assert all(
        builder.agent_builder_graph_from_spec(empty, node_kinds=required).node(k)
        is None
        for k in builder.OPTIONAL_NODE_KINDS
    )


def test_compact_config_limit_does_not_count_pretty_print_whitespace():
    schema = {"type": "object", "description": "x" * 30000}
    config = {"input_schema": schema, "output_schema": schema}
    row = builder.AgentBuilderNode(
        builder.NODE_IDS["contracts"],
        "contracts",
        builder.PORTS_BY_KIND["contracts"],
        config,
    )
    assert row.config == config


def test_cyclic_config_is_rejected_as_bounded_input():
    config = {"binding_ids": []}
    config["binding_ids"].append(config)
    with pytest.raises(ValueError):
        builder.AgentBuilderNode(
            builder.NODE_IDS["capabilities"],
            "capabilities",
            builder.PORTS_BY_KIND["capabilities"],
            config,
        )


def test_envelope_graph_counts_precede_copy_or_hash(monkeypatch):
    current = spec()
    records = builder.agent_builder_artifacts(
        builder.agent_builder_graph_from_spec(current), current
    )
    records[0]["record"]["nodes"] *= 2

    def forbidden(_):
        raise AssertionError("oversized envelope copied or hashed")

    monkeypatch.setattr(builder, "canonical_bytes", forbidden)
    monkeypatch.setattr(builder, "digest", forbidden)
    with pytest.raises((ValueError, PermissionError)):
        builder.verify_agent_builder_artifacts(*records, current)
