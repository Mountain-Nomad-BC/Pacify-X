from collections import Counter
from pathlib import Path
import hashlib
import json

import pytest

from runtime import artifact_reachability as owner


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if type(value) is bytes else json.dumps(value).encode("utf-8")
    path.write_bytes(raw)
    return path


def fixture(root):
    write(
        root,
        "registry/workflow_execution_bindings.json",
        {
            "schema_version": "1.0",
            "count": 1,
            "bindings": [
                {
                    "path": "orchestration/workflows/example.yaml",
                    "entrypoint": "runtime.example:validate",
                    "mode": "executable_validator",
                }
            ],
        },
    )
    write(
        root,
        "registry/project_stream_handlers.json",
        {
            "schema_version": "1.0",
            "executable_count": 1,
            "plan_only_count": 0,
            "workflows": [
                {
                    "orchestration_id": "sample",
                    "handler": "runtime.example.execute",
                    "status": "executable",
                }
            ],
        },
    )
    write(root, "orchestration/workflows/example.yaml", b"workflow: example\n")
    write(
        root,
        "orchestration/workflows/project_stream/sample.yaml",
        b"workflow: sample\n",
    )
    write(root, "providers/agency_agents/agents/example.md", b"agent body\n")
    write(root, "providers/agency_agents/manifests/example.json", b"{}\n")
    write(root, "providers/agency_agents/LICENSE", b"fixture license\n")
    write(root, ".px/skills/example/agents/openai.yaml", b"interface: example\n")
    write(root, "templates/project_stream/example.yaml", b"template: example\n")
    write(
        root,
        "bootstrap/commissioning/reference/questionnaire_answers.template.yaml",
        b"answer: example\n",
    )
    write(root, "other/example.yml", b"other: example\n")
    return root


def test_valid_inventory_preserves_exact_classifications_order_and_hashes(tmp_path):
    root = fixture(tmp_path)
    result = owner.build_artifact_reachability(root)
    expected = [
        (
            "registry/project_stream_handlers.json",
            "registry",
            "runtime/project_stream_orchestrator.py",
            "release_validated",
        ),
        (
            "registry/workflow_execution_bindings.json",
            "registry",
            "runtime/structural_integrity.py",
            "release_validated",
        ),
        (
            "orchestration/workflows/example.yaml",
            "orchestration",
            "runtime/structural_integrity.py",
            "executable_validator",
        ),
        (
            "orchestration/workflows/project_stream/sample.yaml",
            "orchestration",
            "runtime/structural_integrity.py",
            "executable",
        ),
        (
            "providers/agency_agents/agents/example.md",
            "provider_asset",
            "runtime/agent_provider.py",
            "lazy_selected_agent_body",
        ),
        (
            "providers/agency_agents/LICENSE",
            "provider_asset",
            "runtime/agent_provider.py",
            "provider_license",
        ),
        (
            "providers/agency_agents/manifests/example.json",
            "provider_asset",
            "runtime/agent_provider.py",
            "lazy_selected_agent_manifest",
        ),
        (
            ".px/skills/example/agents/openai.yaml",
            "yaml",
            ".px/skills/example/SKILL.md",
            "lazy_skill_interface",
        ),
        (
            "bootstrap/commissioning/reference/questionnaire_answers.template.yaml",
            "yaml",
            "bootstrap/commissioning/reference/README_START_HERE.md",
            "documented_commissioning_template",
        ),
        (
            "other/example.yml",
            "yaml",
            "runtime/structural_integrity.py",
            "unclassified_yaml",
        ),
        (
            "templates/project_stream/example.yaml",
            "yaml",
            "runtime/project_control_plane.py",
            "runtime_validated_template",
        ),
    ]
    assert [
        (x["path"], x["kind"], x["owner"], x["reachability"]) for x in result["records"]
    ] == expected
    assert result["record_count"] == 11
    assert all(
        x["sha256"] == hashlib.sha256((root / x["path"]).read_bytes()).hexdigest()
        for x in result["records"]
    )
    flows = {
        x["path"]: x["entrypoint"]
        for x in result["records"]
        if x["kind"] == "orchestration"
    }
    assert flows == {
        "orchestration/workflows/example.yaml": "runtime.example:validate",
        "orchestration/workflows/project_stream/sample.yaml": "runtime.example:execute",
    }


def test_unbound_workflow_stays_explicitly_unbound(tmp_path):
    root = fixture(tmp_path)
    write(root, "orchestration/workflows/unbound.yaml", b"workflow: unknown\n")
    row = next(
        x
        for x in owner.build_artifact_reachability(root)["records"]
        if x["path"].endswith("/unbound.yaml")
    )
    assert row["entrypoint"] == "" and row["reachability"] == "unbound"


def test_each_selected_image_is_opened_once_including_both_controls(
    tmp_path, monkeypatch
):
    root = fixture(tmp_path)
    original = Path.open
    seen = Counter()

    def track(path, *args, **kwargs):
        if path.is_relative_to(root):
            seen[path.relative_to(root).as_posix()] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", track)
    result = owner.build_artifact_reachability(root)
    assert seen == Counter({row["path"]: 1 for row in result["records"]})


def test_control_hash_uses_same_image_as_declared_binding(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    path = root / "registry/project_stream_handlers.json"
    original = Path.open
    opens = 0

    def mutate_before_second_open(candidate, *args, **kwargs):
        nonlocal opens
        if candidate == path:
            opens += 1
            if opens == 2:
                with original(path, "wb") as stream:
                    stream.write(
                        b'{"schema_version":"1.0","executable_count":0,"plan_only_count":0,"workflows":[]}'
                    )
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", mutate_before_second_open)
    rows = owner.build_artifact_reachability(root)["records"]
    flow = next(
        x
        for x in rows
        if x["path"] == "orchestration/workflows/project_stream/sample.yaml"
    )
    assert flow["reachability"] == "executable"
    assert opens == 1


@pytest.mark.parametrize(
    "directory",
    [
        "node_modules",
        "registry/node_modules",
        "providers/agency_agents/node_modules",
        "quarantine",
    ],
)
def test_excluded_subtrees_are_pruned_before_descent_or_body_reads(
    tmp_path, monkeypatch, directory
):
    import os

    root = fixture(tmp_path)
    write(root, directory + "/ignored.yaml", b"excluded fixture\n")
    forbidden = root / directory
    original = os.scandir

    def scan(path):
        if Path(path) == forbidden:
            raise AssertionError("excluded subtree was enumerated")
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert all(
        not row["path"].startswith(directory + "/")
        for row in owner.build_artifact_reachability(root)["records"]
    )


def test_live_projection_cycles_and_unselected_bodies_are_never_opened(
    tmp_path, monkeypatch
):
    root = fixture(tmp_path)
    names = [
        "artifact_reachability.json",
        "test_group_index.json",
        "current_evidence_index.json",
        "completion_status.json",
        "px_world_state.json",
        "operational_gap_ledger.head.json",
        "operational_gap_ledger.snapshot.json",
        "engine_identity.json",
    ]
    forbidden = {write(root, "registry/" + name, b"must not open") for name in names}
    forbidden.add(write(root, "runtime/unselected.py", b"must not open"))
    original = Path.open

    def open_file(path, *args, **kwargs):
        assert path not in forbidden, "excluded or unselected body opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    assert owner.build_artifact_reachability(root)["record_count"] == 11


@pytest.mark.parametrize(
    "relative",
    [
        "registry/workflow_execution_bindings.json",
        "registry/project_stream_handlers.json",
    ],
)
@pytest.mark.parametrize(
    "kind", ["duplicate", "wrong-count", "bool-count", "nonobject-row", "wrong-field"]
)
def test_control_relationships_are_typed_unique_and_counted(tmp_path, relative, kind):
    root = fixture(tmp_path)
    path = root / relative
    doc = json.loads(path.read_bytes())
    key = "bindings" if "bindings" in doc else "workflows"
    count = "count" if key == "bindings" else "executable_count"
    if kind == "duplicate":
        doc[key].append(dict(doc[key][0]))
        doc[count] += 1
    elif kind == "wrong-count":
        doc[count] += 1
    elif kind == "bool-count":
        doc[count] = True
    elif kind == "nonobject-row":
        doc[key] = [None]
    elif key == "bindings":
        doc[key][0]["entrypoint"] = True
    else:
        doc[key][0]["handler"] = True
    write(root, relative, doc)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b'{"schema_version":"1.0","schema_version":"1.0","count":0,"bindings":[]}',
        b'{"schema_version":"1.0","count":0,"bindings":[],"n":NaN}',
        b'{"schema_version":"1.0","count":0,"bindings":[],"n":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
    ids=["array", "duplicate-key", "nonfinite", "depth"],
)
def test_control_json_is_bounded_and_unambiguous(tmp_path, payload):
    root = fixture(tmp_path)
    write(root, "registry/workflow_execution_bindings.json", payload)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


@pytest.mark.parametrize(
    "kind",
    [
        "path-traversal",
        "unsupported-mode",
        "unsupported-version",
        "nfc-alias",
        "case-alias",
    ],
)
def test_workflow_binding_identity_is_canonical(tmp_path, kind):
    root = fixture(tmp_path)
    relative = "registry/workflow_execution_bindings.json"
    doc = json.loads((root / relative).read_bytes())
    if kind == "path-traversal":
        doc["bindings"][0]["path"] = "orchestration/workflows/../example.yaml"
    elif kind == "unsupported-mode":
        doc["bindings"][0]["mode"] = "claimed_running"
    elif kind == "unsupported-version":
        doc["schema_version"] = "future"
    else:
        first = dict(doc["bindings"][0])
        second = dict(first)
        first["path"] = (
            "orchestration/workflows/\u00e9.yaml"
            if kind == "nfc-alias"
            else "orchestration/workflows/One.yaml"
        )
        second["path"] = (
            "orchestration/workflows/e\u0301.yaml"
            if kind == "nfc-alias"
            else "orchestration/workflows/one.yaml"
        )
        doc["bindings"] = [first, second]
        doc["count"] = 2
    write(root, relative, doc)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


def test_all_selected_sizes_are_checked_before_any_body_open(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    path = root / "providers/agency_agents/agents/oversized.md"
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    original = Path.open

    def refuse_reads(candidate, mode="r", *args, **kwargs):
        if candidate.is_relative_to(root) and "r" in mode:
            raise AssertionError("body opened before selected-size preflight")
        return original(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse_reads)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


def test_control_size_limit_precedes_body_open(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    path = root / "registry/workflow_execution_bindings.json"
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    original = Path.open

    def refuse(candidate, *args, **kwargs):
        if candidate.is_relative_to(root):
            raise AssertionError("oversized control was opened")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


def test_invalid_second_control_is_refused_before_other_artifact_hashing(
    tmp_path, monkeypatch
):
    root = fixture(tmp_path)
    write(root, "registry/aaa-unrelated.json", b"{}\n")
    write(
        root,
        "registry/project_stream_handlers.json",
        {
            "schema_version": "1.0",
            "executable_count": 0,
            "plan_only_count": 0,
            "workflows": [None],
        },
    )
    original = Path.open
    allowed = {
        root / "registry/workflow_execution_bindings.json",
        root / "registry/project_stream_handlers.json",
    }

    def refuse(candidate, *args, **kwargs):
        if candidate.is_relative_to(root) and candidate not in allowed:
            raise AssertionError("artifact hashed before control validation")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


def test_original_path_guard_runs_before_resolution(tmp_path, monkeypatch):
    from runtime import archive_io

    root = fixture(tmp_path)
    seen = []

    def reject(path):
        seen.append(path)
        raise ValueError("simulated original-link refusal")

    monkeypatch.setattr(archive_io, "reject_path_links", reject)
    from runtime import input_files

    monkeypatch.setattr(input_files, "reject_path_links", reject)
    with pytest.raises(ValueError, match="original-link refusal"):
        owner.build_artifact_reachability(root)
    assert seen == [root]


@pytest.mark.parametrize("name", ["_sha", "_load"])
def test_direct_reader_helpers_refuse_oversized_images(tmp_path, name):
    path = tmp_path / "input.json"
    limit = 8 * 1024 * 1024 if name == "_sha" else 1024 * 1024
    if name == "_load":
        path.write_bytes(b"{}" + b" " * (limit - 1))
    else:
        with path.open("wb") as stream:
            stream.truncate(limit + 1)
    with pytest.raises(ValueError):
        getattr(owner, name)(path)


def test_aggregate_selected_budget_refuses_before_any_body_open(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    # Each image is individually valid; together they exceed256MiB.
    for number in range(32):
        path = root / f"providers/agency_agents/agents/part-{number:02}.md"
        with path.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024)
    original = Path.open

    def refuse(candidate, *args, **kwargs):
        if candidate.is_relative_to(root):
            raise AssertionError("body opened before aggregate metadata admission")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(ValueError):
        owner.build_artifact_reachability(root)


def test_normalized_filesystem_aliases_cannot_create_ambiguous_records(tmp_path):
    root = fixture(tmp_path)
    first = write(root, "other/\u00e9.yaml", b"first\n")
    second = write(root, "other/e\u0301.yaml", b"second\n")
    if first.samefile(second):
        # A normalizing filesystem has only one actual directory entry.
        rows = owner.build_artifact_reachability(root)["records"]
        assert (
            len(
                [
                    x
                    for x in rows
                    if x["path"] not in {"other/example.yml"}
                    and x["path"].startswith("other/")
                ]
            )
            == 1
        )
    else:
        with pytest.raises(ValueError):
            owner.build_artifact_reachability(root)


def test_existing_cycle_guard_with_an_owned_minimal_fixture(tmp_path, monkeypatch):
    from tests import test_generated_artifacts as existing

    root = fixture(tmp_path)
    for name in (
        "artifact_reachability.json",
        "test_group_index.json",
        "current_evidence_index.json",
        "completion_status.json",
        "px_world_state.json",
        "operational_gap_ledger.head.json",
        "operational_gap_ledger.snapshot.json",
        "engine_identity.json",
    ):
        write(root, "registry/" + name, b"excluded fixture")
    monkeypatch.setattr(existing, "ROOT", root)
    existing.test_artifact_reachability_excludes_live_receipt_projection_cycle()


def test_yaml_selection_preserves_platform_glob_case_rules(tmp_path):
    root = fixture(tmp_path)
    extras = {
        write(root, "other/upper.YAML", b"other: uppercase\n"),
        write(root, "orchestration/workflows/upper.YAML", b"workflow: uppercase\n"),
    }
    # The old inventory used Path.rglob; its suffix case rule is platform-native.
    expected = {path.relative_to(root).as_posix() for path in root.rglob("*.yaml") if path in extras}
    rows = owner.build_artifact_reachability(root)["records"]
    assert {row["path"] for row in rows if row["path"].endswith("upper.YAML")} == expected
    for row in rows:
        if row["path"] == "orchestration/workflows/upper.YAML":
            assert row["kind"] == "orchestration" and row["reachability"] == "unbound"
