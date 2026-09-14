"""Causal dependency contracts on owned graphs/projects; no root reconciliation."""

from __future__ import annotations

import json
import hashlib
import itertools
import copy
from pathlib import Path

import pytest

from runtime.generated_dependency import generated_dependency_graph
from runtime.dependency_invalidation import (
    adapt_generated_dependency_graph,
    build_dependency_graph,
    compute_invalidation_cone,
    load_dependency_authority,
)
from runtime.dependency_audit import validate_dependency_closure
from scripts.build_python_dependency_ownership import build as build_imports
from runtime.bounded_walk import WalkLimits
from runtime.projection_dependencies import revision_for_path


ROOT = Path(__file__).resolve().parents[1]


def _universal_graph():
    return build_dependency_graph(
        ROOT,
        [
            {"node_id": "a", "kind": "source", "revision": "1"},
            {"node_id": "b", "kind": "projection", "revision": "1"},
        ],
        [{"dependency": "a", "consumer": "b"}],
    )


def test_long_generated_graph_survives_adapter_and_universal_consumer():
    graph = generated_dependency_graph(
        {f"n{i:04d}": [f"n{i - 1:04d}"] for i in range(1, 1500)}
    )
    nodes, edges = adapt_generated_dependency_graph(
        graph, revisions={f"n{i:04d}": "1" for i in range(1500)}
    )
    universal = build_dependency_graph(ROOT, nodes, edges)
    assert len(universal["nodes"]) == 1500
    assert len(universal["edges"]) == 1499
    assert universal["cycle_components"] == []


def test_universal_cycles_use_complete_components_and_respect_reject_policy():
    policy = load_dependency_authority(ROOT)
    policy["allowed_cycle_components"] = [["a", "b", "c"]]
    nodes = [
        {"node_id": name, "kind": "source", "revision": "1"} for name in ["a", "b", "c"]
    ]
    edges = [
        {"dependency": source, "consumer": target}
        for source, target in [("a", "b"), ("b", "a"), ("a", "c"), ("c", "b")]
    ]
    graph = build_dependency_graph(ROOT, nodes, edges, authority=policy)
    assert graph["cycle_components"] == [["a", "b", "c"]]
    policy["cycle_policy"] = "reject"
    with pytest.raises(ValueError, match="cycle"):
        build_dependency_graph(ROOT, nodes, edges, authority=policy)


@pytest.mark.parametrize(
    "mutation",
    ["schema", "duplicate-node", "unknown-edge", "kind", "policy", "revision"],
)
def test_invalidation_cone_rejects_malformed_graph_policy_or_revision(mutation):
    graph = _universal_graph()
    policy = load_dependency_authority(ROOT)
    revisions = {"a": "2"}
    if mutation == "schema":
        graph["schema_version"] = "unknown"
    elif mutation == "duplicate-node":
        graph["nodes"].append(copy.deepcopy(graph["nodes"][0]))
    elif mutation == "unknown-edge":
        graph["edges"].append({"dependency": "b", "consumer": "missing"})
    elif mutation == "kind":
        graph["nodes"][0]["kind"] = "unknown"
    elif mutation == "policy":
        policy["node_kind_count"] = True
    else:
        revisions["a"] = []
    with pytest.raises(ValueError):
        compute_invalidation_cone(graph, revisions, authority=policy)


def test_invalidation_cone_reports_partial_revision_coverage_explicitly():
    graph = _universal_graph()
    policy = load_dependency_authority(ROOT)
    partial = compute_invalidation_cone(graph, {"a": "1"}, authority=policy)
    assert partial["seed_nodes"] == []
    assert partial["complete_revision_coverage"] is False
    assert partial["unevaluated_nodes"] == ["b"]
    complete = compute_invalidation_cone(graph, {"a": "1", "b": "1"}, authority=policy)
    assert complete["complete_revision_coverage"] is True
    assert complete["unevaluated_nodes"] == []


def test_universal_edge_budget_counts_duplicate_inputs(monkeypatch):
    graph = _universal_graph()
    monkeypatch.setattr("runtime.dependency_invalidation.MAX_EDGES", 1)
    with pytest.raises(ValueError, match="edge budget"):
        build_dependency_graph(ROOT, graph["nodes"], graph["edges"] * 2)


def test_generated_graph_consumes_each_dependency_iterator_once():
    expected = generated_dependency_graph({"b": ["a"], "c": ["b"]})
    observed = generated_dependency_graph({"b": iter(["a"]), "c": iter(["b"])})
    assert observed == expected
    assert observed["edges"] == [
        {"source": "a", "target": "b", "kind": "input"},
        {"source": "b", "target": "c", "kind": "input"},
    ]


def test_generated_self_loop_returns_structured_cycle_failure():
    result = generated_dependency_graph({"a": ["a"]})
    assert result["valid"] is False
    assert result["cycles"] == [["a"]]
    assert result["failures"] == [
        {"code": "RP-GEN-002", "message": "generated dependency cycle: a -> a"}
    ]


def test_generated_long_chain_does_not_depend_on_python_recursion_depth():
    result = generated_dependency_graph(
        {f"n{i:04d}": [f"n{i - 1:04d}"] for i in range(1, 1500)}
    )
    assert result["valid"]
    assert len(result["nodes"]) == 1500 and len(result["edges"]) == 1499


@pytest.mark.parametrize(
    "declarations", [{"b": "abc"}, {"b": [False]}, {"b": [""]}, {1: ["a"]}, {"b": None}]
)
def test_generated_graph_rejects_coercive_or_malformed_identities(declarations):
    with pytest.raises(ValueError):
        generated_dependency_graph(declarations)


def test_actual_generated_graph_adapts_edges_and_isolated_nodes():
    generated = generated_dependency_graph({"b": ["a"], "isolated": []})
    nodes, edges = adapt_generated_dependency_graph(
        generated, revisions={"a": "1", "b": "2", "isolated": "3"}
    )
    assert nodes == [
        {"node_id": "a", "kind": "source", "revision": "1"},
        {"node_id": "b", "kind": "source", "revision": "2"},
        {"node_id": "isolated", "kind": "source", "revision": "3"},
    ]
    assert edges == [{"dependency": "a", "consumer": "b"}]


@pytest.mark.parametrize(
    "edge",
    [
        {"from": "a", "to": "b", "source": "b", "target": "a"},
        {"from": "a"},
        {"from": False, "to": "b"},
        "invalid",
    ],
)
def test_generated_adapter_refuses_malformed_edges_instead_of_silently_dropping_them(
    edge,
):
    with pytest.raises(ValueError):
        adapt_generated_dependency_graph(
            {"edges": [edge]}, revisions={"a": "1", "b": "1"}
        )


def test_generated_adapter_requires_exact_revision_identity():
    with pytest.raises(ValueError):
        adapt_generated_dependency_graph(
            {"edges": [{"from": "a", "to": "b"}]}, revisions={"a": "1"}
        )


def test_generated_graph_output_budget_counts_repeated_target_names(monkeypatch):
    monkeypatch.setattr(
        "runtime.generated_dependency.MAX_RESULT_BYTES", 4096, raising=False
    )
    with pytest.raises(ValueError, match="byte budget"):
        generated_dependency_graph({"target" * 200: [f"source{i}" for i in range(8)]})


def test_cycle_diagnostic_does_not_invent_edge_order_from_sorted_component():
    result = generated_dependency_graph({"c": ["a"], "b": ["c"], "a": ["b"]})
    assert (
        result["failures"][0]["message"]
        == "generated dependency cycle component: a, b, c"
    )


@pytest.mark.parametrize("kind", [[], None, False, "unknown"])
def test_generated_adapter_rejects_invalid_kinds_with_value_error(kind):
    with pytest.raises(ValueError):
        adapt_generated_dependency_graph({"edges": []}, revisions={}, default_kind=kind)


def _dependency_project(tmp_path: Path, dependency: str | None):
    root = tmp_path / "project"
    for path in ["runtime", "registry", "policies", ".github/workflows"]:
        (root / path).mkdir(parents=True, exist_ok=True)
    (root / "runtime/fixture.py").write_text("import yaml\n", encoding="utf-8")
    (root / "registry/python_surface_ownership.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "records": [{"path": "runtime/fixture.py", "packaged": True}],
            }
        ),
        encoding="utf-8",
    )
    registry = build_imports(root)
    assert registry["records"][0]["classification"] == "declared_required"
    (root / "registry/python_dependency_ownership.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    dependencies = [] if dependency is None else [dependency]
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools==84.0.0"]\n[project]\ndependencies='
        + json.dumps(dependencies)
        + "\n[project.optional-dependencies]\nrelease=[]\n",
        encoding="utf-8",
    )
    (root / "requirements-release.txt").write_text("", encoding="utf-8")
    (root / "policies/platform-support.json").write_text(
        '{"python_minors": [], "ci_runners": {}}', encoding="utf-8"
    )
    for name in ("ci.yml", "scheduled-assurance.yml"):
        (root / ".github/workflows" / name).write_text(
            "python -m pip install --require-hashes -r requirements-release.txt\n",
            encoding="utf-8",
        )
    (root / ".github/workflows/release.yml").write_text("", encoding="utf-8")
    return root


def test_actual_import_builder_classification_requires_runtime_declaration(tmp_path):
    root = _dependency_project(tmp_path, None)
    result = validate_dependency_closure(root)
    assert not result["valid"]
    assert "undeclared runtime distribution: PyYAML" in result["errors"]


def test_import_audit_accepts_present_declared_runtime_dependency(tmp_path):
    assert validate_dependency_closure(_dependency_project(tmp_path, "PyYAML==6.0.3"))[
        "valid"
    ]


@pytest.mark.parametrize(
    "mutation", ["outside", "duplicate", "coercive-packaged", "linked"]
)
def test_import_inventory_rejects_unsafe_selection_before_source_reads(
    tmp_path, monkeypatch, mutation
):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    inventory = root / "registry/python_surface_ownership.json"
    payload = json.loads(inventory.read_text())
    record = payload["records"][0]
    if mutation == "outside":
        (tmp_path / "outside.py").write_text("import yaml\n")
        record["path"] = "../outside.py"
    elif mutation == "duplicate":
        payload["records"].append(dict(record))
    elif mutation == "coercive-packaged":
        record["packaged"] = "true"
    else:
        source = root / "runtime/fixture.py"
        backing = source.with_name("fixture-backing.py")
        source.rename(backing)
        try:
            source.symlink_to(backing)
        except OSError as exc:
            pytest.skip(f"filesystem symlink unavailable: {exc}")
    inventory.write_text(json.dumps(payload))
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.suffix == ".py":
            pytest.fail("invalid inventory reached source acquisition")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        build_imports(root)


def test_import_inventory_aggregate_budget_precedes_source_reads(tmp_path, monkeypatch):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    monkeypatch.setattr(
        "scripts.build_python_dependency_ownership.MAX_SOURCE_BYTES", 1, raising=False
    )
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.suffix == ".py":
            pytest.fail("source byte budget must precede acquisition")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        build_imports(root)


def test_import_builder_main_uses_one_inventory_image(tmp_path, monkeypatch, capsys):
    import scripts.build_python_dependency_ownership as builder

    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    calls = []
    original = builder.build

    def counted(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(builder, "build", counted)
    monkeypatch.setattr(
        "sys.argv", ["build_python_dependency_ownership.py", "--root", str(root)]
    )
    assert builder.main() == 0
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["modules"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-classification",
        "duplicate-module",
        "coercive-distribution",
        "unsafe-path",
    ],
)
def test_dependency_audit_rejects_invalid_inventory_records(tmp_path, mutation):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    path = root / "registry/python_dependency_ownership.json"
    payload = json.loads(path.read_text())
    record = payload["records"][0]
    if mutation == "unknown-classification":
        record["classification"] = "unknown"
    elif mutation == "duplicate-module":
        payload["records"].append(dict(record))
    elif mutation == "coercive-distribution":
        record.update(classification="standard_library", distribution=True)
    else:
        record["paths"] = ["../outside.py"]
    path.write_text(json.dumps(payload))
    result = validate_dependency_closure(root)
    assert not result["valid"] and result["errors"]


def test_dependency_audit_lock_facts_share_one_acquired_image(tmp_path, monkeypatch):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    lock = root / "requirements-release.txt"
    original = Path.open
    opens = []

    def counted(path, *args, **kwargs):
        if path == lock:
            opens.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    result = validate_dependency_closure(root)
    assert result["valid"]
    assert result["lock_sha256"] == hashlib.sha256(b"").hexdigest()
    assert len(opens) == 1


def test_dependency_audit_missing_metadata_returns_invalid_result(tmp_path):
    result = validate_dependency_closure(tmp_path)
    assert not result["valid"] and result["errors"]


def test_dependency_audit_accepts_current_control_images_in_owned_fixture(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in [
        "registry/python_dependency_ownership.json",
        "pyproject.toml",
        "requirements-release.txt",
        "policies/platform-support.json",
        ".github/workflows/ci.yml",
        ".github/workflows/scheduled-assurance.yml",
        ".github/workflows/release.yml",
    ]:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source / name).read_bytes())
    result = validate_dependency_closure(tmp_path)
    assert result["valid"], result["errors"]
    assert result["module_count"] > 0


@pytest.mark.parametrize(
    "config", ['project="bad"\n', 'build-system="bad"\n[project]\ndependencies=[]\n']
)
def test_dependency_audit_rejects_scalar_control_tables(tmp_path, config):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    (root / "pyproject.toml").write_text(config)
    result = validate_dependency_closure(root)
    assert not result["valid"] and result["errors"]


def test_import_token_budget_stops_before_ast_allocation(tmp_path, monkeypatch):
    root = _dependency_project(tmp_path, "PyYAML==6.0.3")
    monkeypatch.setattr(
        "scripts.build_python_dependency_ownership.MAX_SOURCE_TOKENS", 1
    )
    monkeypatch.setattr(
        "scripts.build_python_dependency_ownership.ast.parse",
        lambda *a, **k: pytest.fail("token budget must precede AST parsing"),
    )
    with pytest.raises(ValueError, match="token budget"):
        build_imports(root)


def test_revision_exact_byte_limit_and_empty_file_remain_valid(tmp_path):
    (tmp_path / "file.txt").write_bytes(b"abc")
    assert (
        revision_for_path(tmp_path, "file.txt", limits=WalkLimits(max_bytes=3))
        == hashlib.sha256(b"abc").hexdigest()
    )
    with pytest.raises(ValueError, match="byte budget"):
        revision_for_path(tmp_path, "file.txt", limits=WalkLimits(max_bytes=2))
    (tmp_path / "file.txt").write_bytes(b"")
    assert (
        revision_for_path(tmp_path, "file.txt", limits=WalkLimits(max_bytes=1))
        == hashlib.sha256(b"").hexdigest()
    )


def test_generated_components_match_independent_reachability_for_every_three_node_graph():
    nodes = ["a", "b", "c"]
    possible = list(itertools.product(nodes, repeat=2))
    for bits in range(1 << len(possible)):
        edges = [edge for index, edge in enumerate(possible) if bits & (1 << index)]
        declarations = {node: [] for node in nodes}
        reach = {node: {node} for node in nodes}
        for source, target in edges:
            declarations[target].append(source)
            reach[source].add(target)
        for middle in nodes:
            for source in nodes:
                if middle in reach[source]:
                    reach[source].update(reach[middle])
        expected = {
            tuple(
                sorted(
                    target
                    for target in nodes
                    if target in reach[source] and source in reach[target]
                )
            )
            for source in nodes
        }
        result = generated_dependency_graph(declarations)
        assert {
            tuple(component) for component in result["strongly_connected_components"]
        } == expected
        assert {tuple(component) for component in result["cycles"]} == {
            component
            for component in expected
            if len(component) > 1 or (component[0], component[0]) in edges
        }


def test_dependency_edge_budget_counts_duplicates_before_deduplication(monkeypatch):
    monkeypatch.setattr("runtime.generated_dependency.MAX_EDGES", 4)
    seen = []

    def inputs():
        for index in range(6):
            seen.append(index)
            if index == 5:
                pytest.fail("edge iterator advanced after budget rejection")
            yield "a"

    with pytest.raises(ValueError, match="edge budget"):
        generated_dependency_graph({"b": inputs()})
    assert seen == list(range(5))


def test_revision_digest_preserves_framing_and_acquires_each_body_once(
    tmp_path, monkeypatch
):
    tree = tmp_path / "tree"
    (tree / "a").mkdir(parents=True)
    bodies = {"a/file.txt": b"one", "a.txt": b"two"}
    for name, body in bodies.items():
        (tree / name).write_bytes(body)
    original = Path.open
    opened = []

    def counted(path, *args, **kwargs):
        if path in [tree / name for name in bodies]:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    expected = hashlib.sha256(b"px.projection-tree/1.0\0")
    for name in ["a/file.txt", "a.txt"]:
        encoded = name.encode()
        body = bodies[name]
        expected.update(len(encoded).to_bytes(8, "big"))
        expected.update(encoded)
        expected.update(len(body).to_bytes(8, "big"))
        expected.update(body)
    assert revision_for_path(tmp_path, "tree") == expected.hexdigest()
    assert sorted(opened) == sorted(tree / name for name in bodies)


@pytest.mark.parametrize("target", ["root", "nested"])
def test_revision_rejects_original_or_nested_link_metadata_before_acquisition(
    tmp_path, monkeypatch, target
):
    source_root = tmp_path / "source"
    tree = source_root / "tree"
    tree.mkdir(parents=True)
    child = tree / "data.txt"
    child.write_bytes(b"source")
    if target == "root":
        linked_root = tmp_path / "linked-root"
        if __import__("os").name == "nt":
            import _winapi

            _winapi.CreateJunction(str(source_root), str(linked_root))
        else:
            linked_root.symlink_to(source_root, target_is_directory=True)
        source_root = linked_root
    else:
        backing = source_root / "backing.txt"
        child.rename(backing)
        try:
            child.symlink_to(backing)
        except OSError as exc:
            pytest.skip(f"filesystem symlink unavailable: {exc}")
    original_open = Path.open

    def guarded(path, *args, **kwargs):
        if path.suffix == ".txt":
            pytest.fail("linked revision reached payload acquisition")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError, match="link|symlink"):
        revision_for_path(source_root, "tree")


@pytest.mark.parametrize("limits", [WalkLimits(max_files=1), WalkLimits(max_bytes=5)])
def test_revision_complete_inventory_budget_precedes_payload_reads(
    tmp_path, monkeypatch, limits
):
    tree = tmp_path / "tree"
    tree.mkdir()
    for name in ["one.txt", "two.txt"]:
        (tree / name).write_bytes(b"abc")
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.parent == tree:
            pytest.fail("inventory budget must precede payload acquisition")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        revision_for_path(tmp_path, "tree", limits=limits)
