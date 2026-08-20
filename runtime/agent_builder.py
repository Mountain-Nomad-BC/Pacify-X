"""Python-authoritative graph contract for the standard Agent Studio builder.

The graph is an immutable, typed projection of one :class:`AgentSpec`.  It is
not an authority record and it cannot grant execution.  Compilation is closed:
unknown node kinds, ports, relations, configuration keys, or topology are
rejected instead of being ignored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable, Mapping

from .studio_models import AgentSpec, IDENTITY, canonical_bytes, digest


GRAPH_SCHEMA_VERSION = "px.agent-builder-graph/1.0"
LAYOUT_SCHEMA_VERSION = "px.agent-builder-layout/1.0"
COMPILER_SCHEMA_VERSION = "px.agent-builder-compiler-receipt/1.0"

NODE_ORDER = (
    "identity",
    "behavior",
    "model",
    "harness",
    "capabilities",
    "tools",
    "handoffs",
    "memory",
    "contracts",
    "authority",
    "tests",
    "candidate",
)
OPTIONAL_NODE_KINDS = frozenset({"tools", "handoffs", "memory"})
NODE_IDS = {kind: f"agent-node:{kind}" for kind in NODE_ORDER}


@dataclass(frozen=True, slots=True)
class AgentBuilderPort:
    port_id: str
    direction: str
    data_type: str

    def __post_init__(self) -> None:
        port_id = str(self.port_id).strip().lower()
        direction = str(self.direction).strip().lower()
        data_type = str(self.data_type).strip().lower()
        if not IDENTITY.fullmatch(port_id):
            raise ValueError("invalid agent builder port ID")
        if direction not in {"input", "output"}:
            raise ValueError("agent builder port direction must be input or output")
        if data_type not in {
            "definition",
            "model-route",
            "capability",
            "authority",
            "contract",
            "validation",
            "candidate",
        }:
            raise ValueError("invalid agent builder port data type")
        object.__setattr__(self, "port_id", port_id)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "data_type", data_type)


def _port(port_id: str, direction: str, data_type: str) -> AgentBuilderPort:
    return AgentBuilderPort(port_id, direction, data_type)


PORTS_BY_KIND: dict[str, tuple[AgentBuilderPort, ...]] = {
    "identity": (_port("out:definition", "output", "definition"),),
    "behavior": (
        _port("in:definition", "input", "definition"),
        _port("out:definition", "output", "definition"),
    ),
    "model": (
        _port("in:definition", "input", "definition"),
        _port("out:model-route", "output", "model-route"),
    ),
    "harness": (
        _port("in:model-route", "input", "model-route"),
        _port("out:capability", "output", "capability"),
    ),
    "capabilities": (
        _port("in:capability", "input", "capability"),
        _port("out:capability", "output", "capability"),
        _port("out:authority", "output", "authority"),
    ),
    "tools": (
        _port("in:capability", "input", "capability"),
        _port("out:authority", "output", "authority"),
    ),
    "handoffs": (
        _port("in:capability", "input", "capability"),
        _port("out:authority", "output", "authority"),
    ),
    "memory": (
        _port("in:definition", "input", "definition"),
        _port("out:authority", "output", "authority"),
    ),
    "contracts": (
        _port("in:definition", "input", "definition"),
        _port("out:contract", "output", "contract"),
    ),
    "authority": (
        _port("in:authority", "input", "authority"),
        _port("out:validation", "output", "validation"),
    ),
    "tests": (
        _port("in:validation", "input", "validation"),
        _port("in:contract", "input", "contract"),
        _port("out:candidate", "output", "candidate"),
    ),
    "candidate": (_port("in:candidate", "input", "candidate"),),
}

CONFIG_KEYS: dict[str, frozenset[str]] = {
    "identity": frozenset({"agent_id", "version", "project_id", "owner"}),
    "behavior": frozenset({"instruction_sha256"}),
    "model": frozenset({"model"}),
    "harness": frozenset({"harness_id"}),
    "capabilities": frozenset({"binding_ids"}),
    "tools": frozenset({"binding_ids"}),
    "handoffs": frozenset({"agent_ids"}),
    "memory": frozenset({"binding_ids"}),
    "contracts": frozenset({"input_schema", "output_schema"}),
    "authority": frozenset({"grant_ids"}),
    "tests": frozenset({"test_ids"}),
    "candidate": frozenset({"lifecycle"}),
}


def _json_object(value: Mapping[str, object], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"agent builder {label} must be an object")
    normalized = json.loads(canonical_bytes(dict(value)))
    if len(canonical_bytes(normalized)) > 128 * 1024:
        raise ValueError(f"agent builder {label} exceeds 128 KiB")
    return normalized


@dataclass(frozen=True, slots=True)
class AgentBuilderNode:
    node_id: str
    kind: str
    ports: tuple[AgentBuilderPort, ...]
    config: Mapping[str, object]

    def __post_init__(self) -> None:
        node_id = str(self.node_id).strip().lower()
        kind = str(self.kind).strip().lower()
        if kind not in PORTS_BY_KIND or node_id != NODE_IDS[kind]:
            raise ValueError("agent builder node identity does not match its kind")
        ports = tuple(self.ports)
        if ports != PORTS_BY_KIND[kind]:
            raise ValueError(f"agent builder {kind} ports do not match the closed contract")
        config = _json_object(self.config, f"{kind} config")
        if frozenset(config) != CONFIG_KEYS[kind]:
            raise ValueError(f"agent builder {kind} config keys do not match the closed contract")
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "ports", ports)
        object.__setattr__(self, "config", config)


@dataclass(frozen=True, slots=True)
class AgentBuilderEdge:
    edge_id: str
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    relation: str

    def __post_init__(self) -> None:
        values = {
            name: str(getattr(self, name)).strip().lower()
            for name in (
                "edge_id",
                "source_node",
                "source_port",
                "target_node",
                "target_port",
                "relation",
            )
        }
        if not all(IDENTITY.fullmatch(value) for value in values.values()):
            raise ValueError("invalid agent builder edge identity")
        for name, value in values.items():
            object.__setattr__(self, name, value)


def _edge(
    source_kind: str,
    source_port: str,
    target_kind: str,
    target_port: str,
    relation: str,
) -> AgentBuilderEdge:
    source = NODE_IDS[source_kind]
    target = NODE_IDS[target_kind]
    material = f"{source}|{source_port}|{target}|{target_port}|{relation}"
    edge_id = "agent-edge:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return AgentBuilderEdge(edge_id, source, source_port, target, target_port, relation)


def _expected_edges(kinds: frozenset[str]) -> tuple[AgentBuilderEdge, ...]:
    rows = [
        _edge("identity", "out:definition", "behavior", "in:definition", "owns"),
        _edge("behavior", "out:definition", "model", "in:definition", "prompts"),
        _edge("model", "out:model-route", "harness", "in:model-route", "routes"),
        _edge("harness", "out:capability", "capabilities", "in:capability", "requests"),
        _edge("behavior", "out:definition", "contracts", "in:definition", "defines"),
        _edge("capabilities", "out:authority", "authority", "in:authority", "authorizes"),
        _edge("contracts", "out:contract", "tests", "in:contract", "constrains"),
        _edge("authority", "out:validation", "tests", "in:validation", "validates"),
        _edge("tests", "out:candidate", "candidate", "in:candidate", "produces"),
    ]
    if "tools" in kinds:
        rows.extend(
            (
                _edge("capabilities", "out:capability", "tools", "in:capability", "binds"),
                _edge("tools", "out:authority", "authority", "in:authority", "authorizes"),
            )
        )
    if "handoffs" in kinds:
        rows.extend(
            (
                _edge("capabilities", "out:capability", "handoffs", "in:capability", "hands-off"),
                _edge("handoffs", "out:authority", "authority", "in:authority", "authorizes"),
            )
        )
    if "memory" in kinds:
        rows.extend(
            (
                _edge("behavior", "out:definition", "memory", "in:definition", "retrieves"),
                _edge("memory", "out:authority", "authority", "in:authority", "authorizes"),
            )
        )
    return tuple(sorted(rows, key=lambda item: item.edge_id))


@dataclass(frozen=True, slots=True)
class AgentBuilderGraph:
    schema_version: str
    agent_id: str
    nodes: tuple[AgentBuilderNode, ...]
    edges: tuple[AgentBuilderEdge, ...]

    def __post_init__(self) -> None:
        if self.schema_version != GRAPH_SCHEMA_VERSION:
            raise ValueError("unsupported agent builder graph schema")
        agent_id = str(self.agent_id).strip().lower()
        if not IDENTITY.fullmatch(agent_id):
            raise ValueError("invalid agent builder graph agent ID")
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        if len(nodes) != len({node.node_id for node in nodes}):
            raise ValueError("duplicate agent builder node ID")
        if len(nodes) != len({node.kind for node in nodes}):
            raise ValueError("duplicate agent builder node kind")
        if nodes != tuple(sorted(nodes, key=lambda node: NODE_ORDER.index(node.kind))):
            raise ValueError("agent builder nodes are not in canonical order")
        kinds = frozenset(node.kind for node in nodes)
        required = frozenset(NODE_ORDER) - OPTIONAL_NODE_KINDS
        if not required.issubset(kinds) or not kinds.issubset(frozenset(NODE_ORDER)):
            raise ValueError("agent builder graph node set is incomplete or unknown")
        if len(edges) != len({edge.edge_id for edge in edges}):
            raise ValueError("duplicate agent builder edge ID")
        by_id = {node.node_id: node for node in nodes}
        for edge in edges:
            source = by_id.get(edge.source_node)
            target = by_id.get(edge.target_node)
            if source is None or target is None:
                raise ValueError("agent builder edge references an unknown node")
            source_port = next(
                (item for item in source.ports if item.port_id == edge.source_port),
                None,
            )
            target_port = next(
                (item for item in target.ports if item.port_id == edge.target_port),
                None,
            )
            if source_port is None or target_port is None:
                raise ValueError("agent builder edge references an unknown port")
            if source_port.direction != "output" or target_port.direction != "input":
                raise ValueError("agent builder edge direction is invalid")
            if source_port.data_type != target_port.data_type:
                raise ValueError("agent builder edge port types are incompatible")
        expected = _expected_edges(kinds)
        if edges != expected:
            raise ValueError("agent builder edges do not match the closed executable topology")
        identity = next(node for node in nodes if node.kind == "identity")
        if identity.config["agent_id"] != agent_id:
            raise ValueError("agent builder graph identity does not match its identity node")
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

    def node(self, kind: str) -> AgentBuilderNode | None:
        return next((node for node in self.nodes if node.kind == kind), None)


def agent_builder_graph_from_mapping(value: Mapping[str, object]) -> AgentBuilderGraph:
    if not isinstance(value, Mapping) or frozenset(value) != {
        "schema_version",
        "agent_id",
        "nodes",
        "edges",
    }:
        raise ValueError("agent builder graph keys do not match the closed contract")
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("agent builder nodes and edges must be arrays")
    nodes: list[AgentBuilderNode] = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping) or frozenset(raw) != {
            "node_id",
            "kind",
            "ports",
            "config",
        }:
            raise ValueError("agent builder node keys do not match the closed contract")
        raw_ports = raw.get("ports")
        if not isinstance(raw_ports, list):
            raise ValueError("agent builder ports must be an array")
        ports = []
        for item in raw_ports:
            if not isinstance(item, Mapping) or frozenset(item) != {
                "port_id",
                "direction",
                "data_type",
            }:
                raise ValueError("agent builder port keys do not match the closed contract")
            ports.append(
                AgentBuilderPort(
                    str(item["port_id"]),
                    str(item["direction"]),
                    str(item["data_type"]),
                )
            )
        config = raw.get("config")
        if not isinstance(config, Mapping):
            raise ValueError("agent builder node config must be an object")
        nodes.append(
            AgentBuilderNode(
                str(raw["node_id"]), str(raw["kind"]), tuple(ports), config
            )
        )
    edges: list[AgentBuilderEdge] = []
    edge_keys = {"edge_id", "source_node", "source_port", "target_node", "target_port", "relation"}
    for raw in raw_edges:
        if not isinstance(raw, Mapping) or frozenset(raw) != edge_keys:
            raise ValueError("agent builder edge keys do not match the closed contract")
        edges.append(
            AgentBuilderEdge(
                *(
                    str(raw[key])
                    for key in (
                        "edge_id",
                        "source_node",
                        "source_port",
                        "target_node",
                        "target_port",
                        "relation",
                    )
                )
            )
        )
    return AgentBuilderGraph(
        str(value["schema_version"]),
        str(value["agent_id"]),
        tuple(nodes),
        tuple(edges),
    )


def _node(kind: str, config: Mapping[str, object]) -> AgentBuilderNode:
    return AgentBuilderNode(NODE_IDS[kind], kind, PORTS_BY_KIND[kind], config)


def agent_builder_graph_from_spec(
    spec: AgentSpec, *, node_kinds: Iterable[str] | None = None
) -> AgentBuilderGraph:
    """Project ``spec`` while preserving an explicitly edited optional node set.

    Required node kinds remain immutable. Optional kinds may be retained with an
    empty AgentSpec list so the visual topology can round-trip independently of
    its editor layout. Connections remain compiler-derived and closed.
    """

    requested: frozenset[str] | None = None
    if node_kinds is not None:
        normalized = tuple(str(kind).strip().lower() for kind in node_kinds)
        requested = frozenset(normalized)
        required = frozenset(NODE_ORDER) - OPTIONAL_NODE_KINDS
        if len(normalized) != len(requested):
            raise ValueError("agent builder node kinds contain duplicates")
        if not required.issubset(requested) or not requested.issubset(
            frozenset(NODE_ORDER)
        ):
            raise ValueError("agent builder node kind set is incomplete or unknown")

    nodes = [
        _node(
            "identity",
            {
                "agent_id": spec.agent_id,
                "version": spec.version,
                "project_id": spec.project_id,
                "owner": spec.owner,
            },
        ),
        _node("behavior", {"instruction_sha256": spec.instruction_sha256}),
        _node("model", {"model": dict(spec.model)}),
        _node("harness", {"harness_id": spec.harness_id}),
        _node("capabilities", {"binding_ids": list(spec.capability_binding_ids)}),
    ]
    if spec.tool_binding_ids or (requested is not None and "tools" in requested):
        nodes.append(_node("tools", {"binding_ids": list(spec.tool_binding_ids)}))
    if spec.handoff_agent_ids or (requested is not None and "handoffs" in requested):
        nodes.append(_node("handoffs", {"agent_ids": list(spec.handoff_agent_ids)}))
    if spec.memory_binding_ids or (requested is not None and "memory" in requested):
        nodes.append(_node("memory", {"binding_ids": list(spec.memory_binding_ids)}))
    nodes.extend(
        (
            _node(
                "contracts",
                {
                    "input_schema": dict(spec.input_schema),
                    "output_schema": dict(spec.output_schema),
                },
            ),
            _node("authority", {"grant_ids": list(spec.effect_grant_ids)}),
            _node("tests", {"test_ids": list(spec.required_tests)}),
            _node("candidate", {"lifecycle": spec.lifecycle}),
        )
    )
    ordered = tuple(sorted(nodes, key=lambda node: NODE_ORDER.index(node.kind)))
    return AgentBuilderGraph(
        GRAPH_SCHEMA_VERSION,
        spec.agent_id,
        ordered,
        _expected_edges(frozenset(node.kind for node in ordered)),
    )


def compile_agent_builder_graph(graph: AgentBuilderGraph) -> AgentSpec:
    required = {kind: graph.node(kind) for kind in NODE_ORDER}
    identity = required["identity"].config
    behavior = required["behavior"].config
    model = required["model"].config
    contracts = required["contracts"].config
    tools = required["tools"].config["binding_ids"] if required["tools"] else []
    handoffs = required["handoffs"].config["agent_ids"] if required["handoffs"] else []
    memory = required["memory"].config["binding_ids"] if required["memory"] else []
    return AgentSpec(
        str(identity["agent_id"]),
        str(identity["version"]),
        str(identity["project_id"]),
        str(identity["owner"]),
        str(required["harness"].config["harness_id"]),
        str(behavior["instruction_sha256"]),
        tuple(str(item) for item in required["capabilities"].config["binding_ids"]),
        tuple(str(item) for item in required["authority"].config["grant_ids"]),
        tuple(str(item) for item in required["tests"].config["test_ids"]),
        str(required["candidate"].config["lifecycle"]),
        model=dict(model["model"]),
        tool_binding_ids=tuple(str(item) for item in tools),
        memory_binding_ids=tuple(str(item) for item in memory),
        handoff_agent_ids=tuple(str(item) for item in handoffs),
        input_schema=dict(contracts["input_schema"]),
        output_schema=dict(contracts["output_schema"]),
    )


def assert_agent_builder_graph_matches_spec(
    graph: AgentBuilderGraph, spec: AgentSpec
) -> None:
    compiled = compile_agent_builder_graph(graph)
    if asdict(compiled) != asdict(spec):
        raise ValueError(
            "agent builder graph does not compile to the supplied agent specification"
        )


def normalize_agent_editor_layout(
    graph: AgentBuilderGraph, value: Mapping[str, object] | None = None
) -> dict[str, dict[str, float]]:
    supplied = value or {}
    if not isinstance(supplied, Mapping):
        raise ValueError("agent builder editor layout must be an object")
    node_ids = {node.node_id for node in graph.nodes}
    if any(str(key) not in node_ids for key in supplied):
        raise ValueError("agent builder editor layout references an unknown node")
    result: dict[str, dict[str, float]] = {}
    for index, node in enumerate(graph.nodes):
        raw = supplied.get(node.node_id, {})
        if not isinstance(raw, Mapping) or any(key not in {"x", "y"} for key in raw):
            raise ValueError("agent builder node layout must contain only x and y")
        x = float(raw.get("x", 48 + (index % 4) * 260))
        y = float(raw.get("y", 48 + (index // 4) * 150))
        if not math.isfinite(x) or not math.isfinite(y) or abs(x) > 100_000 or abs(y) > 100_000:
            raise ValueError("agent builder node layout is outside the bounded canvas")
        result[node.node_id] = {"x": x, "y": y}
    return result


def agent_builder_artifacts(
    graph: AgentBuilderGraph,
    spec: AgentSpec,
    editor_layout: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    assert_agent_builder_graph_matches_spec(graph, spec)
    # Artifact values must already have the same JSON shapes that will be
    # reloaded from disk.  ``asdict`` retains tuple members in memory, which
    # makes a newly generated envelope compare unequal to its byte-identical
    # persisted/reloaded form and breaks exact idempotent replay.
    graph_value = json.loads(canonical_bytes(asdict(graph)))
    graph_sha256 = digest(graph_value)
    graph_envelope = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "record": graph_value,
        "sha256": graph_sha256,
    }
    layout = normalize_agent_editor_layout(graph, editor_layout)
    layout_sha256 = digest(layout)
    layout_envelope = {
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "graph_sha256": graph_sha256,
        "layout": layout,
        "layout_sha256": layout_sha256,
    }
    spec_value = asdict(spec)
    compiler_receipt = {
        "schema_version": COMPILER_SCHEMA_VERSION,
        "compiler": "runtime.agent_builder.compile_agent_builder_graph",
        "graph_sha256": graph_sha256,
        "layout_sha256": layout_sha256,
        "agent_spec_sha256": digest(spec_value),
        "deterministic": True,
        "authority_granted": False,
        "host_authority_retained": True,
    }
    compiler_receipt["receipt_sha256"] = digest(compiler_receipt)
    return graph_envelope, layout_envelope, compiler_receipt


def verify_agent_builder_artifacts(
    graph_envelope: Mapping[str, object],
    layout_envelope: Mapping[str, object],
    compiler_receipt: Mapping[str, object],
    spec: AgentSpec,
) -> tuple[AgentBuilderGraph, dict[str, dict[str, float]]]:
    graph_record = graph_envelope.get("record")
    if (
        frozenset(graph_envelope) != {"schema_version", "record", "sha256"}
        or graph_envelope.get("schema_version") != GRAPH_SCHEMA_VERSION
        or not isinstance(graph_record, Mapping)
        or graph_envelope.get("sha256") != digest(graph_record)
    ):
        raise PermissionError("agent builder graph envelope authentication failed")
    graph = agent_builder_graph_from_mapping(graph_record)
    assert_agent_builder_graph_matches_spec(graph, spec)
    layout = layout_envelope.get("layout")
    if (
        frozenset(layout_envelope)
        != {"schema_version", "graph_sha256", "layout", "layout_sha256"}
        or layout_envelope.get("schema_version") != LAYOUT_SCHEMA_VERSION
        or layout_envelope.get("graph_sha256") != graph_envelope.get("sha256")
        or not isinstance(layout, Mapping)
    ):
        raise PermissionError("agent builder layout envelope authentication failed")
    normalized_layout = normalize_agent_editor_layout(graph, layout)
    if layout_envelope.get("layout_sha256") != digest(normalized_layout):
        raise PermissionError("agent builder layout content hash mismatch")
    receipt = dict(compiler_receipt)
    receipt_sha256 = receipt.pop("receipt_sha256", None)
    expected = {
        "schema_version": COMPILER_SCHEMA_VERSION,
        "compiler": "runtime.agent_builder.compile_agent_builder_graph",
        "graph_sha256": graph_envelope.get("sha256"),
        "layout_sha256": layout_envelope.get("layout_sha256"),
        "agent_spec_sha256": digest(asdict(spec)),
        "deterministic": True,
        "authority_granted": False,
        "host_authority_retained": True,
    }
    if receipt != expected or receipt_sha256 != digest(expected):
        raise PermissionError("agent builder compiler receipt authentication failed")
    return graph, normalized_layout
