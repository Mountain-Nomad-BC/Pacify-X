"""Python-authoritative graph contract for the standard Agent Studio builder.

The graph is a typed projection of one :class:`AgentSpec`.  Its nested values
are copied and revalidated on consumption. It is
not an authority record and it cannot grant execution.  Compilation is closed:
unknown node kinds, ports, relations, configuration keys, or topology are
rejected instead of being ignored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable, Mapping

from .studio_models import (
    AgentSpec,
    IDENTITY,
    LIFECYCLE_STATES,
    canonical_bytes,
    digest,
)
from .json_io import validate_json_value
from .numeric_inputs import bounded_sequence, bounded_integer, finite_number


# Prepared helpers, inserted before the existing port table at application.
MAX_GRAPH_BYTES = 1024 * 1024
MAX_CONFIG_BYTES = 128 * 1024
MAX_SCHEMA_BYTES = 64 * 1024
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_BINDINGS = 256


def _actual_text(value, label, *, maximum=128, empty=False):
    if type(value) is not str or len(value) > maximum:
        raise ValueError(f"agent builder {label} must be bounded actual text")
    if (
        len(value.encode("utf-8")) > maximum
        or any(ord(c) < 32 for c in value)
        or (not empty and not value.strip())
    ):
        raise ValueError(f"agent builder {label} must be bounded actual text")
    return value


def _identity_text(value, label):
    return _actual_text(value, label).strip().lower()


def _actual_object(value, label, maximum):
    if (
        type(value) is not dict
        or len(value) > maximum
        or any(type(key) is not str for key in value)
    ):
        raise ValueError(
            f"agent builder {label} must be a bounded object with actual text keys"
        )
    return value


def _json_preflight(value, maximum):
    """Admit exact compact JSON bytes before full canonical encoding/copying."""
    validate_json_value(value, max_depth=32, max_nodes=100000)
    used = 0

    def add(count):
        nonlocal used
        used += count
        if used > maximum:
            raise ValueError("agent builder compact JSON byte budget exceeded")

    def visit(item):
        kind = type(item)
        if kind is dict:
            add(2 + max(0, len(item) - 1) + len(item))
            for key, child in item.items():
                visit(key)
                visit(child)
        elif kind is list:
            add(2 + max(0, len(item) - 1))
            for child in item:
                visit(child)
        else:
            if kind is str and len(item) > maximum:
                raise ValueError("agent builder string exceeds byte budget")
            if kind is int and item.bit_length() > 1024:
                raise ValueError("agent builder integer exceeds bounded representation")
            # A scalar token is bounded before encoding; total bytes are reserved
            # before the complete canonical object can be allocated.
            add(
                len(
                    json.dumps(
                        item, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                    ).encode("utf-8")
                )
            )

    visit(value)


def _sequence(value, label, maximum, *, minimum=0):
    return bounded_sequence(
        value, "agent builder " + label, maximum=maximum, minimum=minimum
    )


def _bindings(value, label, *, minimum=0):
    rows = _sequence(value, label, MAX_BINDINGS, minimum=minimum)
    normalized = [_actual_text(item, label).strip() for item in rows]
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate agent builder binding identity")
    return rows


def _schema_input(value, label):
    _actual_object(value, label, 100000)
    if type(value.get("type")) is not str or value["type"] != "object":
        raise ValueError("agent builder schema root type must be object")
    _json_preflight(value, MAX_SCHEMA_BYTES)

    def shape(schema):
        if type(schema) is not dict:
            raise ValueError("agent builder schema properties must be objects")
        if "type" in schema and (
            type(schema["type"]) is not str
            or schema["type"]
            not in {"object", "array", "string", "integer", "number", "boolean", "null"}
        ):
            raise ValueError("agent builder schema type is unsupported")
        if "required" in schema:
            _bindings(schema["required"], "required schema keys")
        properties = schema.get("properties", {})
        if type(properties) is not dict or len(properties) > MAX_BINDINGS:
            raise ValueError("agent builder schema properties must be bounded")
        for name, child in properties.items():
            _actual_text(name, "schema property")
            shape(child)
        if "additionalProperties" in schema and type(
            schema["additionalProperties"]
        ) not in (bool, dict):
            raise ValueError(
                "agent builder additionalProperties must be a boolean or schema"
            )
        if type(schema.get("additionalProperties")) is dict:
            shape(schema["additionalProperties"])
        if "items" in schema:
            shape(schema["items"])

    shape(value)


def _model_input(value):
    _actual_object(value, "model", 7)
    allowed = {
        "provider",
        "vendor",
        "family",
        "model_id",
        "version",
        "max_output_tokens",
        "temperature",
    }
    if (
        type(value) is not dict
        or not {"provider", "family", "model_id"} <= set(value)
        or set(value) - allowed
    ):
        raise ValueError("agent builder model fields are invalid")
    for name in ("provider", "vendor", "family", "model_id", "version"):
        if name in value:
            _actual_text(
                value[name],
                "model " + name,
                maximum=512,
                empty=name in {"vendor", "version"},
            )
    if value["provider"].strip().lower() not in {
        "deterministic",
        "vscode-lm",
        "pacify-local",
    }:
        raise ValueError("agent builder model provider is not admitted")
    if "max_output_tokens" in value:
        bounded_integer(
            value["max_output_tokens"], "model output tokens", maximum=32768
        )
    if "temperature" in value:
        finite_number(value["temperature"], "model temperature", minimum=0, maximum=2)


def _config_input(kind, value):
    _actual_object(value, "config keys", len(CONFIG_KEYS[kind]))
    if type(value) is not dict or frozenset(value) != CONFIG_KEYS[kind]:
        raise ValueError(
            f"agent builder {kind} config keys do not match the closed contract"
        )
    if kind == "identity":
        for name, item in value.items():
            _actual_text(item, name, maximum=512 if name == "owner" else 128)
    elif kind == "behavior":
        text = _actual_text(value["instruction_sha256"], "instruction SHA-256")
        if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
            raise ValueError("agent builder instruction identity is invalid")
    elif kind == "harness":
        _actual_text(value["harness_id"], "harness ID")
    elif kind == "model":
        _model_input(value["model"])
    elif kind == "contracts":
        for name, item in value.items():
            _schema_input(item, name)
    elif kind == "candidate":
        _actual_text(value["lifecycle"], "lifecycle")
        if value["lifecycle"] not in LIFECYCLE_STATES:
            raise ValueError("agent builder lifecycle is invalid")
    else:
        for name, item in value.items():
            _bindings(item, name, minimum=1 if kind == "tests" else 0)
    return value


def _typed_ports(value):
    rows = _sequence(value, "ports", 3, minimum=1)
    if any(type(item) is not AgentBuilderPort for item in rows):
        raise ValueError("agent builder ports must be actual port records")
    return tuple(AgentBuilderPort(p.port_id, p.direction, p.data_type) for p in rows)


def _typed_nodes(value):
    rows = _sequence(value, "nodes", 12, minimum=9)
    if any(type(item) is not AgentBuilderNode for item in rows):
        raise ValueError("agent builder nodes must be actual node records")
    return tuple(AgentBuilderNode(n.node_id, n.kind, n.ports, n.config) for n in rows)


def _typed_edges(value):
    rows = _sequence(value, "edges", 15, minimum=9)
    if any(type(item) is not AgentBuilderEdge for item in rows):
        raise ValueError("agent builder edges must be actual edge records")
    return tuple(
        AgentBuilderEdge(
            e.edge_id,
            e.source_node,
            e.source_port,
            e.target_node,
            e.target_port,
            e.relation,
        )
        for e in rows
    )


def _checked_graph(graph):
    if type(graph) is not AgentBuilderGraph:
        raise ValueError("agent builder graph must be an actual graph record")
    return AgentBuilderGraph(
        graph.schema_version, graph.agent_id, graph.nodes, graph.edges
    )


def _record_graph_input(graph):
    nodes = _sequence(graph.nodes, "nodes", 12, minimum=9)
    edges = _sequence(graph.edges, "edges", 15, minimum=9)
    if any(type(n) is not AgentBuilderNode for n in nodes) or any(
        type(e) is not AgentBuilderEdge for e in edges
    ):
        raise ValueError("agent builder graph members must be actual records")
    raw_nodes = []
    for node in nodes:
        ports = _sequence(node.ports, "ports", 3, minimum=1)
        if any(type(p) is not AgentBuilderPort for p in ports):
            raise ValueError("agent builder ports must be actual port records")
        raw_nodes.append(
            {
                "node_id": node.node_id,
                "kind": node.kind,
                "ports": [
                    {
                        "port_id": p.port_id,
                        "direction": p.direction,
                        "data_type": p.data_type,
                    }
                    for p in ports
                ],
                "config": node.config,
            }
        )
    raw_edges = [
        {
            name: getattr(edge, name)
            for name in (
                "edge_id",
                "source_node",
                "source_port",
                "target_node",
                "target_port",
                "relation",
            )
        }
        for edge in edges
    ]
    _raw_graph_input(
        {
            "schema_version": graph.schema_version,
            "agent_id": graph.agent_id,
            "nodes": raw_nodes,
            "edges": raw_edges,
        }
    )


def _checked_spec(spec):
    if type(spec) is not AgentSpec:
        raise ValueError("agent builder specification must be an actual AgentSpec")
    for name in (
        "agent_id",
        "version",
        "project_id",
        "owner",
        "harness_id",
        "instruction_sha256",
        "lifecycle",
    ):
        _actual_text(getattr(spec, name), name, maximum=512 if name == "owner" else 128)
    for name in (
        "capability_binding_ids",
        "effect_grant_ids",
        "required_tests",
        "tool_binding_ids",
        "memory_binding_ids",
        "handoff_agent_ids",
    ):
        _bindings(
            getattr(spec, name), name, minimum=1 if name == "required_tests" else 0
        )
    _model_input(spec.model)
    _schema_input(spec.input_schema, "input schema")
    _schema_input(spec.output_schema, "output schema")
    # All record fields and collection sizes are admitted before deep copying.
    record = asdict(spec)
    return AgentSpec(**record)


def _raw_graph_input(value):
    _actual_object(value, "graph", 4)
    if type(value) is not dict or frozenset(value) != {
        "schema_version",
        "agent_id",
        "nodes",
        "edges",
    }:
        raise ValueError("agent builder graph keys do not match the closed contract")
    for name, maximum, minimum in [("nodes", 12, 9), ("edges", 15, 9)]:
        if type(value[name]) is not list:
            raise ValueError("agent builder nodes and edges must be arrays")
        _sequence(value[name], name, maximum, minimum=minimum)
    for node in value["nodes"]:
        _actual_object(node, "node", 4)
        if type(node) is not dict or type(node.get("ports")) is not list:
            raise ValueError(
                "agent builder node and ports must be typed objects/arrays"
            )
        _sequence(node["ports"], "ports", 3, minimum=1)
    _json_preflight(value, MAX_GRAPH_BYTES)


def _coordinate(value):
    try:
        return finite_number(
            value, "layout coordinate", minimum=-100000, maximum=100000
        )
    except ValueError as error:
        raise ValueError(
            "agent builder node layout is outside the bounded canvas"
        ) from error


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
        port_id = _identity_text(self.port_id, "port ID")
        direction = _identity_text(self.direction, "port direction")
        data_type = _identity_text(self.data_type, "port data type")
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


def _json_object(
    value: Mapping[str, object], label: str, *, maximum: int = MAX_CONFIG_BYTES
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"agent builder {label} must be an object")
    _json_preflight(value, maximum)
    return json.loads(canonical_bytes(value))


@dataclass(frozen=True, slots=True)
class AgentBuilderNode:
    node_id: str
    kind: str
    ports: tuple[AgentBuilderPort, ...]
    config: Mapping[str, object]

    def __post_init__(self) -> None:
        node_id = _identity_text(self.node_id, "node ID")
        kind = _identity_text(self.kind, "node kind")
        if kind not in PORTS_BY_KIND or node_id != NODE_IDS[kind]:
            raise ValueError("agent builder node identity does not match its kind")
        ports = _typed_ports(self.ports)
        if ports != PORTS_BY_KIND[kind]:
            raise ValueError(
                f"agent builder {kind} ports do not match the closed contract"
            )
        config = _json_object(_config_input(kind, self.config), f"{kind} config")
        if frozenset(config) != CONFIG_KEYS[kind]:
            raise ValueError(
                f"agent builder {kind} config keys do not match the closed contract"
            )
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
            name: _identity_text(getattr(self, name), name)
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
        _edge(
            "capabilities", "out:authority", "authority", "in:authority", "authorizes"
        ),
        _edge("contracts", "out:contract", "tests", "in:contract", "constrains"),
        _edge("authority", "out:validation", "tests", "in:validation", "validates"),
        _edge("tests", "out:candidate", "candidate", "in:candidate", "produces"),
    ]
    if "tools" in kinds:
        rows.extend(
            (
                _edge(
                    "capabilities", "out:capability", "tools", "in:capability", "binds"
                ),
                _edge(
                    "tools", "out:authority", "authority", "in:authority", "authorizes"
                ),
            )
        )
    if "handoffs" in kinds:
        rows.extend(
            (
                _edge(
                    "capabilities",
                    "out:capability",
                    "handoffs",
                    "in:capability",
                    "hands-off",
                ),
                _edge(
                    "handoffs",
                    "out:authority",
                    "authority",
                    "in:authority",
                    "authorizes",
                ),
            )
        )
    if "memory" in kinds:
        rows.extend(
            (
                _edge(
                    "behavior", "out:definition", "memory", "in:definition", "retrieves"
                ),
                _edge(
                    "memory", "out:authority", "authority", "in:authority", "authorizes"
                ),
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
        if (
            type(self.schema_version) is not str
            or self.schema_version != GRAPH_SCHEMA_VERSION
        ):
            raise ValueError("unsupported agent builder graph schema")
        agent_id = _identity_text(self.agent_id, "agent ID")
        if not IDENTITY.fullmatch(agent_id):
            raise ValueError("invalid agent builder graph agent ID")
        _record_graph_input(self)
        nodes = _typed_nodes(self.nodes)
        edges = _typed_edges(self.edges)
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
            raise ValueError(
                "agent builder edges do not match the closed executable topology"
            )
        identity = next(node for node in nodes if node.kind == "identity")
        if identity.config["agent_id"] != agent_id:
            raise ValueError(
                "agent builder graph identity does not match its identity node"
            )
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

    def node(self, kind: str) -> AgentBuilderNode | None:
        return next((node for node in self.nodes if node.kind == kind), None)


def agent_builder_graph_from_mapping(value: Mapping[str, object]) -> AgentBuilderGraph:
    _raw_graph_input(value)
    if type(value) is not dict or frozenset(value) != {
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
        if type(raw) is not dict or frozenset(raw) != {
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
            if type(item) is not dict or frozenset(item) != {
                "port_id",
                "direction",
                "data_type",
            }:
                raise ValueError(
                    "agent builder port keys do not match the closed contract"
                )
            ports.append(
                AgentBuilderPort(
                    item["port_id"],
                    item["direction"],
                    item["data_type"],
                )
            )
        config = raw.get("config")
        if not isinstance(config, Mapping):
            raise ValueError("agent builder node config must be an object")
        nodes.append(
            AgentBuilderNode(raw["node_id"], raw["kind"], tuple(ports), config)
        )
    edges: list[AgentBuilderEdge] = []
    edge_keys = {
        "edge_id",
        "source_node",
        "source_port",
        "target_node",
        "target_port",
        "relation",
    }
    for raw in raw_edges:
        if not isinstance(raw, Mapping) or frozenset(raw) != edge_keys:
            raise ValueError("agent builder edge keys do not match the closed contract")
        edges.append(
            AgentBuilderEdge(
                *(
                    raw[key]
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
        _actual_text(value["schema_version"], "graph schema"),
        value["agent_id"],
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

    spec = _checked_spec(spec)
    requested: frozenset[str] | None = None
    if node_kinds is not None:
        normalized = tuple(
            _identity_text(kind, "node kind")
            for kind in _sequence(node_kinds, "node kind selection", 12)
        )
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
    graph = _checked_graph(graph)
    required = {kind: graph.node(kind) for kind in NODE_ORDER}
    identity = required["identity"].config
    behavior = required["behavior"].config
    model = required["model"].config
    contracts = required["contracts"].config
    tools = required["tools"].config["binding_ids"] if required["tools"] else []
    handoffs = required["handoffs"].config["agent_ids"] if required["handoffs"] else []
    memory = required["memory"].config["binding_ids"] if required["memory"] else []
    return AgentSpec(
        identity["agent_id"],
        identity["version"],
        identity["project_id"],
        identity["owner"],
        required["harness"].config["harness_id"],
        behavior["instruction_sha256"],
        tuple(item for item in required["capabilities"].config["binding_ids"]),
        tuple(item for item in required["authority"].config["grant_ids"]),
        tuple(item for item in required["tests"].config["test_ids"]),
        required["candidate"].config["lifecycle"],
        model=dict(model["model"]),
        tool_binding_ids=tuple(item for item in tools),
        memory_binding_ids=tuple(item for item in memory),
        handoff_agent_ids=tuple(item for item in handoffs),
        input_schema=dict(contracts["input_schema"]),
        output_schema=dict(contracts["output_schema"]),
    )


def assert_agent_builder_graph_matches_spec(
    graph: AgentBuilderGraph, spec: AgentSpec
) -> None:
    spec = _checked_spec(spec)
    compiled = compile_agent_builder_graph(graph)
    if asdict(compiled) != asdict(spec):
        raise ValueError(
            "agent builder graph does not compile to the supplied agent specification"
        )


def normalize_agent_editor_layout(
    graph: AgentBuilderGraph, value: Mapping[str, object] | None = None
) -> dict[str, dict[str, float]]:
    graph = _checked_graph(graph)
    supplied = {} if value is None else value
    if type(supplied) is not dict or len(supplied) > 12:
        raise ValueError("agent builder editor layout must be an object")
    node_ids = {node.node_id for node in graph.nodes}
    if any(type(key) is not str or key not in node_ids for key in supplied):
        raise ValueError("agent builder editor layout references an unknown node")
    result: dict[str, dict[str, float]] = {}
    for index, node in enumerate(graph.nodes):
        raw = supplied.get(node.node_id, {})
        _actual_object(raw, "node layout", 2)
        if type(raw) is not dict or any(key not in {"x", "y"} for key in raw):
            raise ValueError("agent builder node layout must contain only x and y")
        x = _coordinate(raw.get("x", 48 + (index % 4) * 260))
        y = _coordinate(raw.get("y", 48 + (index // 4) * 150))
        result[node.node_id] = {"x": x, "y": y}
    return result


def agent_builder_artifacts(
    graph: AgentBuilderGraph,
    spec: AgentSpec,
    editor_layout: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    graph = _checked_graph(graph)
    spec = _checked_spec(spec)
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
    envelope_specs = [
        (
            graph_envelope,
            {"schema_version", "record", "sha256"},
            GRAPH_SCHEMA_VERSION,
            ("sha256",),
        ),
        (
            layout_envelope,
            {"schema_version", "graph_sha256", "layout", "layout_sha256"},
            LAYOUT_SCHEMA_VERSION,
            ("graph_sha256", "layout_sha256"),
        ),
        (
            compiler_receipt,
            {
                "schema_version",
                "compiler",
                "graph_sha256",
                "layout_sha256",
                "agent_spec_sha256",
                "deterministic",
                "authority_granted",
                "host_authority_retained",
                "receipt_sha256",
            },
            COMPILER_SCHEMA_VERSION,
            ("graph_sha256", "layout_sha256", "agent_spec_sha256", "receipt_sha256"),
        ),
    ]
    for envelope, keys, schema, hashes in envelope_specs:
        _actual_object(envelope, "envelope", len(keys))
        if (
            type(envelope) is not dict
            or frozenset(envelope) != keys
            or type(envelope.get("schema_version")) is not str
            or envelope["schema_version"] != schema
        ):
            raise PermissionError("agent builder envelope fields are invalid")
        for key in hashes:
            value = envelope[key]
            if (
                type(value) is not str
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise PermissionError("agent builder envelope hash identity is invalid")
    if (
        type(compiler_receipt["compiler"]) is not str
        or compiler_receipt["compiler"]
        != "runtime.agent_builder.compile_agent_builder_graph"
    ):
        raise PermissionError("agent builder compiler identity is invalid")
    if (
        compiler_receipt["deterministic"] is not True
        or compiler_receipt["authority_granted"] is not False
        or compiler_receipt["host_authority_retained"] is not True
    ):
        raise PermissionError(
            "agent builder compiler receipt flags are not actual booleans"
        )
    _raw_graph_input(graph_envelope["record"])
    raw_layout = layout_envelope["layout"]
    _actual_object(raw_layout, "layout", 12)
    if type(raw_layout) is not dict or len(raw_layout) > 12:
        raise ValueError("agent builder editor layout must be a bounded object")
    for key, coordinates in raw_layout.items():
        _actual_text(key, "layout node ID")
        _actual_object(coordinates, "node layout", 2)
        if type(coordinates) is not dict or set(coordinates) - {"x", "y"}:
            raise ValueError("agent builder node layout must contain only x and y")
        for value in coordinates.values():
            _coordinate(value)
    graph_envelope = _json_object(
        graph_envelope, "graph envelope", maximum=MAX_ENVELOPE_BYTES
    )
    layout_envelope = _json_object(
        layout_envelope, "layout envelope", maximum=MAX_ENVELOPE_BYTES
    )
    compiler_receipt = _json_object(
        compiler_receipt, "compiler receipt", maximum=MAX_ENVELOPE_BYTES
    )
    spec = _checked_spec(spec)
    graph_record = graph_envelope.get("record")
    _raw_graph_input(graph_record)
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
    if (
        compiler_receipt.get("deterministic") is not True
        or compiler_receipt.get("authority_granted") is not False
        or compiler_receipt.get("host_authority_retained") is not True
    ):
        raise PermissionError(
            "agent builder compiler receipt flags are not actual booleans"
        )
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
