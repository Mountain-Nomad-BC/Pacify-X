from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.knowledge_core_controller import KnowledgeCoreController
from tests.test_knowledge_core_controller import _project


def controller(root):
    value = object.__new__(KnowledgeCoreController)
    value.project_root = root.resolve()
    value.root = root / ".engineering-bootstrap/studios/knowledge"
    value.authority = SimpleNamespace(verify_receipt=lambda payload: payload)
    return value


def forbid_body(monkeypatch, target):
    original = Path.open

    def checked(path, *args, **kwargs):
        if path == target:
            pytest.fail("rejected input body was opened")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)


def fake_size(monkeypatch, target, size):
    original = Path.stat

    def checked(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path != target:
            return value
        fields = list(value)
        fields[6] = size
        return type(value)(fields)

    monkeypatch.setattr(Path, "stat", checked)


@pytest.mark.parametrize("operation", ["source", "evidence", "signed"])
def test_knowledge_rejects_oversized_images_before_open(
    tmp_path, monkeypatch, operation
):
    c = controller(tmp_path)
    target = tmp_path / "source.txt"
    target.write_text("small physical fixture", encoding="utf-8")
    maximum = 4 * 1024 * 1024 if operation == "signed" else 64 * 1024 * 1024
    fake_size(monkeypatch, target, maximum + 1)
    forbid_body(monkeypatch, target)
    if operation == "source":
        with pytest.raises((ValueError, PermissionError)):
            c._path_snapshot(target)
    elif operation == "evidence":
        snapshots, errors = c._evidence_snapshots(["source.txt#sha256=" + "0" * 64])
        assert not snapshots and errors
    else:
        with pytest.raises((ValueError, PermissionError)):
            c._verify_signed(target)


def test_knowledge_signed_json_rejects_duplicate_keys(tmp_path):
    c = controller(tmp_path)
    path = tmp_path / "receipt.json"
    path.write_text('{"state":"blocked","state":"admitted"}', encoding="utf-8")
    with pytest.raises((ValueError, PermissionError)):
        c._verify_signed(path)


def test_knowledge_registry_rejects_duplicate_identity(tmp_path):
    root = _project(tmp_path)
    c = controller(root)
    path = root / "registry/knowledge_sources.json"
    value = json.loads(path.read_text())
    value["knowledge_sources"].append(
        {**value["knowledge_sources"][0], "location": "different.md"}
    )
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, PermissionError)):
        c._sources()


def test_knowledge_policy_bound_precedes_control_directory_write(tmp_path, monkeypatch):
    root = _project(tmp_path)
    path = root / "policies/learning-promotion.json"
    path.write_text(path.read_text() + " " * (64 * 1024), encoding="utf-8")
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-authority"))
    forbid_body(monkeypatch, path)
    with pytest.raises((ValueError, PermissionError)):
        KnowledgeCoreController(root)
    assert not (root / ".engineering-bootstrap").exists()
    assert not (root / "host-authority").exists()


@pytest.mark.skipif(
    __import__("os").name != "nt", reason="Actual Windows junction boundary"
)
@pytest.mark.parametrize("operation", ["source", "evidence", "signed", "constructor"])
def test_knowledge_original_junction_spelling_is_refused(
    tmp_path, operation, monkeypatch
):
    import _winapi

    project = tmp_path / "project"
    project.mkdir()
    _project(project)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("external data", encoding="utf-8")
    (outside / "receipt.json").write_text("{}", encoding="utf-8")
    link = project / "linked"
    _winapi.CreateJunction(str(outside), str(link))
    c = controller(project)
    if operation == "evidence":
        snapshots, errors = c._evidence_snapshots(
            ["linked/data.txt#sha256=" + hashlib.sha256(b"external data").hexdigest()]
        )
        assert not snapshots and errors
    elif operation == "source":
        with pytest.raises((ValueError, PermissionError)):
            c._path_snapshot(link)
    elif operation == "signed":
        with pytest.raises((ValueError, PermissionError)):
            c._verify_signed(link / "receipt.json")
    else:
        alias = tmp_path / "project-alias"
        _winapi.CreateJunction(str(project), str(alias))
        monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-authority"))
        with pytest.raises((ValueError, PermissionError)):
            KnowledgeCoreController(alias)
        assert not (project / ".engineering-bootstrap").exists()
        assert not (tmp_path / "host-authority").exists()


def test_knowledge_snapshot_preserves_exact_existing_framing(tmp_path):
    c = controller(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "B.txt").write_bytes(b"B\r\n")
    (source / "a.txt").write_bytes("a Unicode \u03bb".encode("utf-8"))
    rows = [
        {
            "path": p.name,
            "bytes": len(p.read_bytes()),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in [source / "B.txt", source / "a.txt"]
    ]
    canonical = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert c._path_snapshot(source) == {
        "kind": "tree",
        "files": 2,
        "bytes": sum(row["bytes"] for row in rows),
        "content_sha256": hashlib.sha256(canonical).hexdigest(),
    }


@pytest.mark.parametrize("operation", ["source-tree", "evidence-set"])
def test_knowledge_complete_byte_preflight_precedes_first_body(
    tmp_path, monkeypatch, operation
):
    c = controller(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    paths = [source / (str(i) + ".txt") for i in range(5)]
    for p in paths:
        p.write_text("small fixture", encoding="utf-8")
    original_stat = Path.stat
    original_open = Path.open

    def metadata(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path not in paths:
            return value
        fields = list(value)
        fields[6] = 64 * 1024 * 1024
        return type(value)(fields)

    def opened(path, *args, **kwargs):
        if path in paths:
            pytest.fail("aggregate input was read before complete byte preflight")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(Path, "open", opened)
    if operation == "source-tree":
        with pytest.raises((ValueError, PermissionError)):
            c._path_snapshot(source)
    else:
        refs = [
            p.relative_to(tmp_path).as_posix() + "#sha256=" + "0" * 64 for p in paths
        ]
        with pytest.raises((ValueError, PermissionError)):
            c._evidence_snapshots(refs)


@pytest.mark.parametrize(
    "operation", ["content", "learning-publication", "proposal-publication"]
)
def test_knowledge_input_preflight_precedes_canonical_serialization(
    tmp_path, monkeypatch, operation
):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("unadmitted input reached canonical serialization")

    monkeypatch.setattr(module, "canonical_bytes", forbidden)
    payload = {
        "content": "x" * (8 * 1024 * 1024 + 1),
        "proposal_id": "proposal:demo",
        "pipeline_id": "learning:demo",
        "sequence": 1,
        "updated_utc": "2026-09-09T00:00:00Z",
    }
    with pytest.raises((ValueError, PermissionError)):
        if operation == "content":
            c._validate_learning_content(payload, "test content")
        elif operation == "learning-publication":
            c._publish_learning(payload, actor="test", operation="test", previous=None)
        else:
            c._publish(payload, actor="test", operation="test", previous=None)


def test_knowledge_history_total_is_checked_before_first_event_body(
    tmp_path, monkeypatch
):
    c = controller(tmp_path)
    proposal = "proposal:demo"
    root = c._proposal_root(proposal)
    events = root / "events"
    events.mkdir(parents=True)
    head = {
        "schema_version": "px.knowledge-proposal/1.0",
        "proposal_id": proposal,
        "state": "candidate",
        "sequence": 9,
        "candidate": {},
        "authority_state": "codex-host-retained",
    }
    (root / "head.json").write_text(json.dumps(head), encoding="utf-8")
    paths = [events / (str(i).zfill(8) + ".json") for i in range(1, 10)]
    for p in paths:
        p.write_text("{}", encoding="utf-8")
    original_stat = Path.stat
    original_open = Path.open

    def metadata(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path not in paths:
            return value
        fields = list(value)
        fields[6] = 4 * 1024 * 1024
        return type(value)(fields)

    def opened(path, *args, **kwargs):
        if path in paths:
            pytest.fail("oversized history event opened before aggregate preflight")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises((ValueError, PermissionError)):
        c._read(proposal)


@pytest.mark.parametrize("limit", [True, 1.5, "2"])
def test_knowledge_browse_limit_is_an_actual_integer(tmp_path, limit):
    with pytest.raises(ValueError):
        controller(tmp_path).browse(limit=limit)


@pytest.mark.parametrize(
    "query", [True, [], "x" * 4097], ids=["boolean", "sequence", "oversized"]
)
def test_knowledge_browse_query_is_bounded_text(tmp_path, query):
    with pytest.raises(ValueError):
        controller(tmp_path).browse(query=query)


def test_knowledge_collection_refuses_unclassified_entry_before_body(tmp_path):
    c = controller(tmp_path)
    directory = c.root / "proposals"
    directory.mkdir(parents=True)
    (directory / "unclassified.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        c.browse()


def test_knowledge_rejects_opaque_candidate_before_access(tmp_path):
    with pytest.raises(ValueError):
        controller(tmp_path).propose(
            object(), source_ids=[], evidence_refs=[], approved=True, proposed_by="test"
        )


def test_nested_knowledge_reads_share_budget_and_failure_resets_it(
    tmp_path, monkeypatch
):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)
    target = tmp_path / "data.txt"
    target.write_text("fixture", encoding="utf-8")
    fake_size(monkeypatch, target, 64 * 1024 * 1024)
    reads = []

    def image(path, info, **kwargs):
        reads.append(path)
        return b"fixture"

    monkeypatch.setattr(module, "read_file_image", image)

    @module._input_scope
    def nested(owner):
        for _ in range(5):
            owner._image(target, maximum=64 * 1024 * 1024)

    with pytest.raises(ValueError, match="aggregate image budget"):
        nested(c)
    assert len(reads) == 4
    assert c._image(target, maximum=64 * 1024 * 1024) == b"fixture"
    assert len(reads) == 5


def test_expired_nested_acquisition_does_not_open_another_image(tmp_path, monkeypatch):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)
    target = tmp_path / "data.txt"
    target.write_text("fixture", encoding="utf-8")
    clock = [100.0]
    reads = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def image(path, info, **kwargs):
        reads.append(path)
        clock[0] += 61
        return b"fixture"

    monkeypatch.setattr(module, "read_file_image", image)

    @module._input_scope
    def nested(owner):
        owner._image(target)
        owner._image(target)

    with pytest.raises(ValueError, match="duration budget"):
        nested(c)
    assert reads == [target]
    assert c._image(target) == b"fixture"


@pytest.mark.skipif(
    __import__("os").name != "nt", reason="Actual Windows junction boundary"
)
def test_knowledge_evidence_refuses_a_junction_inside_the_same_project(tmp_path):
    import _winapi

    real = tmp_path / "real"
    real.mkdir()
    (real / "data.txt").write_bytes(b"data")
    _winapi.CreateJunction(str(real), str(tmp_path / "alias"))
    snapshots, errors = controller(tmp_path)._evidence_snapshots(
        ["alias/data.txt#sha256=" + hashlib.sha256(b"data").hexdigest()]
    )
    assert not snapshots and errors


def test_knowledge_history_refuses_unclassified_retained_entry(tmp_path):
    c = controller(tmp_path)
    root = c._proposal_root("proposal:demo")
    events = root / "events"
    events.mkdir(parents=True)
    path = events / "unknown.json"
    path.write_text("{}", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unclassified"):
        c._history_paths(root)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field",
    ["minimum_trials_per_confidence_gate", "maximum_retained_pipeline_history_bytes"],
)
def test_knowledge_policy_limits_are_actual_integers_before_writes(
    tmp_path, monkeypatch, field
):
    root = _project(tmp_path)
    path = root / "policies/learning-promotion.json"
    policy = json.loads(path.read_text())
    policy[field] = float(policy[field])
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-authority"))
    with pytest.raises((ValueError, PermissionError)):
        KnowledgeCoreController(root)
    assert not (root / ".engineering-bootstrap").exists()


def test_knowledge_constructor_requires_actual_read_only_flag(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        KnowledgeCoreController(root, read_only="false")


@pytest.mark.parametrize("field", ["actor", "operation"])
def test_knowledge_publication_labels_are_bounded_before_hashing(
    tmp_path, monkeypatch, field
):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)
    original = module.canonical_bytes

    def canonical(value):
        if isinstance(value, dict) and len(value.get(field, "")) > 256:
            pytest.fail("unadmitted publication label reached hashing")
        return original(value)

    monkeypatch.setattr(module, "canonical_bytes", canonical)
    state = {
        "proposal_id": "proposal:demo",
        "sequence": 1,
        "updated_utc": "2026-09-09T00:00:00Z",
    }
    labels = {"actor": "test", "operation": "test"}
    labels[field] = "x" * 4097
    with pytest.raises(ValueError):
        c._publish(state, previous=None, **labels)


def test_knowledge_publication_caps_the_actual_ascii_encoded_record(
    tmp_path, monkeypatch
):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)
    c.authority = SimpleNamespace(sign_receipt=lambda value: value)
    writes = []
    monkeypatch.setattr(module, "write_json_atomic", lambda *args: writes.append(args))
    event = {"text": "\u03bb" * 750000}
    root = c._proposal_root("proposal:demo")
    with pytest.raises(ValueError):
        c._publish_pair(root / "events/00000001.json", event, root / "head.json", {})
    assert not writes


def test_knowledge_publication_refuses_to_exceed_retained_history(
    tmp_path, monkeypatch
):
    import runtime.knowledge_core_controller as module

    c = controller(tmp_path)
    c.authority = SimpleNamespace(sign_receipt=lambda value: value)
    root = c._proposal_root("proposal:demo")
    events = root / "events"
    events.mkdir(parents=True)
    paths = [events / (str(i).zfill(8) + ".json") for i in range(1, 9)]
    for path in paths:
        path.write_text("{}", encoding="utf-8")
    original_stat = Path.stat

    def metadata(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path not in paths:
            return value
        fields = list(value)
        fields[6] = 4 * 1024 * 1024
        return type(value)(fields)

    monkeypatch.setattr(Path, "stat", metadata)
    writes = []
    monkeypatch.setattr(module, "write_json_atomic", lambda *args: writes.append(args))
    with pytest.raises(ValueError):
        c._publish_pair(
            events / "00000009.json", {"value": "next"}, root / "head.json", {}
        )
    assert not writes


def test_proposal_payload_is_admitted_before_creating_its_directory(tmp_path):
    c = controller(tmp_path)
    references = [str(i) + ":" + ("x" * 3990) for i in range(600)]
    with pytest.raises(ValueError):
        c.propose(
            {"id": "knowledge:demo", "kind": "fact", "content": {"statement": "test"}},
            source_ids=["source:one"],
            evidence_refs=references,
            approved=True,
            proposed_by="test",
        )
    assert not c.root.exists()


def test_persisted_record_budget_matches_the_existing_writer(tmp_path):
    from runtime.studio_models import write_json_atomic

    value = {
        "unicode": "\u03bb\U0001f600",
        "escaping": 'a\n\t"\\b',
        "nested": [None, False, 1.0, {"key": "value"}],
    }
    path = tmp_path / "record.json"
    write_json_atomic(path, value)
    assert KnowledgeCoreController._persisted_record_size(value) == path.stat().st_size
