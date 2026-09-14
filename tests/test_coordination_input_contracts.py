"""Coordination authority rejects malformed or unbounded intake before semantics."""

import json

import pytest

from runtime import state_invariants as module
from tests.test_state_invariants import _states, _seal_state, _task


@pytest.mark.parametrize(
    "path,value",
    [
        (("tasks",), None),
        (("tasks",), False),
        (("tasks",), {}),
        (("plans",), None),
        (("claims",), None),
        (("sessions",), None),
        (("tasks", 0, "status"), []),
        (("plans", 0, "status"), {}),
        (("claims", 0, "status"), []),
        (("tasks", 1, "depends_on"), None),
        (("tasks", 1, "depends_on"), [{}]),
        (("claims", 0, "targets"), None),
        (("claims", 0, "targets"), [{}]),
        (("tasks", 0, "usage", "tokens"), 10**400),
    ],
)
def test_malformed_state_returns_structured_rejection(tmp_path, path, value):
    _, candidate, _ = _states(tmp_path)
    target = candidate
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    _seal_state(candidate)
    report = module.validate_coordination_state(candidate)
    assert report["valid"] is False and report["violations"]


def test_reduced_conformance_handles_null_task_array(tmp_path):
    _, candidate, _ = _states(tmp_path)
    candidate["tasks"] = None
    report = module.coordination_conformance_report(candidate)
    assert report["valid"] is False
    assert "PX-COORD-TASK-CLAIM-MISMATCH" in report["violation_ids"]


def test_deep_unknown_metadata_rejected_before_hash_recursion(tmp_path, monkeypatch):
    _, candidate, _ = _states(tmp_path)
    nested = {}
    candidate["unknown_metadata"] = nested
    for _ in range(1500):
        nested["next"] = {}
        nested = nested["next"]
    monkeypatch.setattr(
        module,
        "_stable_hash",
        lambda value: pytest.fail("hashing preceded bounded structural preflight"),
    )
    report = module.validate_coordination_state(candidate)
    assert report["valid"] is False and report["violations"]


def test_malformed_previous_state_is_structured_before_transition_work(tmp_path):
    previous, candidate, event = _states(tmp_path)
    previous["tasks"] = None
    report = module.validate_coordination_state(
        candidate, previous_state=previous, event=event
    )
    assert report["valid"] is False


@pytest.mark.parametrize("event", [[], "event", 3])
def test_malformed_event_is_structured_before_ancestry_work(tmp_path, event):
    previous, candidate, _ = _states(tmp_path)
    report = module.validate_coordination_state(
        candidate, previous_state=previous, event=event
    )
    assert report["valid"] is False


@pytest.mark.parametrize("cycle", [False, True])
def test_long_dependency_chain_uses_bounded_nonrecursive_traversal(tmp_path, cycle):
    state, _, _ = _states(tmp_path)
    state["tasks"] = [
        _task(
            f"task-{i:04}",
            "planned",
            dependency=f"task-{i + 1:04}" if i < 1499 else None,
        )
        for i in range(1500)
    ]
    state["plans"][0]["task_ids"] = [task["id"] for task in state["tasks"]]
    if cycle:
        state["tasks"][-1]["depends_on"] = ["task-0000"]
    _seal_state(state)
    report = module.validate_coordination_state(state)
    assert report["valid"] is (not cycle)
    if cycle:
        assert any(item["code"] == "dag_cycle" for item in report["violations"])


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1, "a": 2}\n',
        b'{"value": NaN}\n',
        b'{"nested": ' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}\n",
    ],
    ids=["duplicate-key", "nonfinite", "deep-json"],
)
def test_jsonl_uses_strict_bounded_json_semantics(tmp_path, raw):
    path = tmp_path / "events.jsonl"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        module._read_jsonl(path, maximum_bytes=65536, maximum_records=10)


def _memory_record(layer, identifier):
    return {
        "project_id": "project-a",
        "layer": layer,
        "memory_id": identifier,
        "revision": 1,
    }


def test_memory_record_limit_is_global_across_files(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_MEMORY_RECORDS", 2)
    folder = tmp_path / "memory"
    folder.mkdir()
    for filename, layer in [
        ("project.jsonl", "project"),
        ("state.jsonl", "state"),
        ("system-candidates.jsonl", "system_candidate"),
    ]:
        (folder / filename).write_text(json.dumps(_memory_record(layer, layer)) + "\n")
    with pytest.raises(ValueError, match="record"):
        module._read_memory_records(tmp_path, "project-a")


def test_startup_duplicate_state_field_rejects_without_mutation(tmp_path):
    state, _, _ = _states(tmp_path)
    root = tmp_path / ".engineering-bootstrap/coordination"
    root.mkdir(parents=True)
    path = root / "state.json"
    raw = json.dumps(state)[:-1] + ', "tasks": null}'
    path.write_text(raw)
    with pytest.raises(module.StateInvariantError):
        module.validate_coordination_startup(tmp_path)
    assert path.read_text() == raw


def _forbid_open(monkeypatch, paths):
    from pathlib import Path

    original = Path.open

    def checked(path, *args, **kwargs):
        if path in paths:
            pytest.fail("input body acquired before complete preflight")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)


def test_oversized_state_rejected_before_open(tmp_path, monkeypatch):
    path = tmp_path / ".engineering-bootstrap/coordination/state.json"
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.truncate(module.MAX_STATE_BYTES + 1)
    _forbid_open(monkeypatch, {path})
    with pytest.raises(module.StateInvariantError):
        module.validate_coordination_startup(tmp_path)


def test_jsonl_byte_preflight_precedes_open(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"x" * 17)
    _forbid_open(monkeypatch, {path})
    with pytest.raises(ValueError, match="bounded JSONL"):
        module._read_jsonl(path, maximum_bytes=16, maximum_records=1)


def test_total_memory_bytes_precede_any_memory_read(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_MEMORY_BYTES", 16)
    folder = tmp_path / "memory"
    folder.mkdir()
    paths = {folder / "project.jsonl", folder / "state.jsonl"}
    for path in paths:
        path.write_bytes(b"x" * 9)
    _forbid_open(monkeypatch, paths)
    with pytest.raises(ValueError, match="byte budget"):
        module._read_memory_records(tmp_path, "project-a")


def test_total_memory_file_count_precedes_body_acquisition(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_MEMORY_FILES", 5)
    folder = tmp_path / "memory/sessions"
    folder.mkdir(parents=True)
    paths = {folder / f"{index}.jsonl" for index in range(3)}
    for path in paths:
        path.write_text("{}\n")
    _forbid_open(monkeypatch, paths)
    with pytest.raises(ValueError, match="file count"):
        module._read_memory_records(tmp_path, "project-a")


def test_graph_edge_budget_precedes_graph_traversal(tmp_path, monkeypatch):
    state, _, _ = _states(tmp_path)
    state["tasks"][0]["depends_on"] = ["task-b"]
    _seal_state(state)
    monkeypatch.setattr(module, "MAX_DEPENDENCY_EDGES", 1)
    monkeypatch.setattr(
        module,
        "strongly_connected_components",
        lambda *args: pytest.fail("graph traversed before edge admission"),
    )
    report = module.validate_coordination_state(state)
    assert report["valid"] is False
    assert "edge budget" in str(report["violations"])


def test_jsonl_record_count_precedes_decoding_next_record(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"{}\nnot-json\n")
    with pytest.raises(ValueError, match="record limit"):
        module._read_jsonl(path, maximum_bytes=64, maximum_records=1)


def test_jsonl_checks_cooperative_deadline(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="duration budget"):
        module._read_jsonl(path, maximum_bytes=64, maximum_records=1, deadline=0.0)


@pytest.mark.parametrize("case", ["empty-active-targets", "scope-comparison-budget"])
def test_complete_claim_work_is_admitted_before_graph_and_scope_checks(
    tmp_path, monkeypatch, case
):
    _, candidate, _ = _states(tmp_path)
    if case == "empty-active-targets":
        candidate["claims"][0]["targets"] = []
    else:
        candidate["tasks"][1]["claim_targets"] = [
            f"runtime/path-{index}" for index in range(20)
        ]
        monkeypatch.setattr(module, "MAX_TARGET_COMPARISONS", 10, raising=False)
    _seal_state(candidate)
    monkeypatch.setattr(
        module,
        "strongly_connected_components",
        lambda *args: pytest.fail(
            "semantic work preceded complete claim work admission"
        ),
    )
    report = module.validate_coordination_state(candidate)
    assert report["valid"] is False


@pytest.mark.parametrize("malformed", [False, True])
def test_recovery_coordinator_consumes_structured_startup_result_without_rewrite(
    tmp_path, malformed
):
    from runtime.recovery import RecoveryConfiguration, RecoveryCoordinator
    from tests.test_state_invariants import _write_startup_store

    _write_startup_store(tmp_path)
    state = tmp_path / ".engineering-bootstrap/coordination/state.json"
    if malformed:
        state.write_text(state.read_text()[:-1] + ', "tasks": null}')
    original = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = RecoveryCoordinator(RecoveryConfiguration(tmp_path)).reconcile()
    component = next(
        row
        for row in report["components"]
        if row["component"] == "coordination_invariants"
    )
    assert component["status"] == ("blocked" if malformed else "healthy")
    assert report["valid"] is (not malformed)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == original
