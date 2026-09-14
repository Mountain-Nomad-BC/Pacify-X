from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import runtime.cognitive_core.index_builder as builder
from runtime.cognitive_core.navigator import CognitiveNavigator


def write_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def capability_project(root, count=1):
    return write_json(
        root,
        "registry/metacognitive_capabilities.json",
        {
            "capabilities": [
                {
                    "id": "cap-" + str(i),
                    "title": "Capability " + str(i),
                    "status": "active",
                    "integration_state": "mapped_tested_owner",
                    "target_owners": ["runtime/example.py"],
                }
                for i in range(count)
            ]
        },
    )


def skill_project(root):
    path = root / "registry/skill_catalog.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'schema_version="1.0"\nloading_rule="metadata_only_at_startup_body_after_selection"\ndefault_active_limit=1\nhard_active_limit=8\n[[skills]]\nid="example"\nversion="1.0"\nstatus="active"\nbody=".px/skills/example/SKILL.md"\ncontract="registry/skills/example.json"\nadmission_record="admission:example"\ntags=["test"]\n',
        encoding="utf-8",
    )
    write_json(
        root,
        "registry/semantic_capability_index.json",
        {"records": [{"id": "example", "description": "Example skill"}]},
    )
    return root


def leaf_project(root, *, digest=None):
    skill_project(root)
    body = write_json(
        root,
        ".px/skills/example/references/capabilities/leaf.json",
        {
            "id": "leaf",
            "title": "Leaf capability",
            "summary": "Bounded metadata",
            "procedure": ["RAW PROCEDURE CONTENT MUST NOT BECOME A RELATION"],
            "dependencies": [],
        },
    )
    write_json(
        root,
        ".px/skills/example/references/capability-index.json",
        {
            "count": 1,
            "records": [
                {
                    "id": "leaf",
                    "path": body.relative_to(root).as_posix(),
                    "sha256": digest or hashlib.sha256(body.read_bytes()).hexdigest(),
                    "when_to_use": "Use for leaf inspection",
                }
            ],
        },
    )
    return body


def test_missing_projection_status_does_not_become_active():
    records = {}
    builder._add(records, {"id": "missing", "kind": "capability"})
    assert records["capability:missing"]["status"] not in {"active", "admitted"}


def test_projection_merge_is_order_independent_and_fail_closed():
    first = {
        "id": "same",
        "kind": "capability",
        "owner": "owner-a",
        "status": "active",
        "path": "one.json",
        "source_sha256": "1" * 64,
        "risk": "R1",
    }
    second = {
        **first,
        "owner": "owner-b",
        "status": "revoked",
        "path": "two.json",
        "source_sha256": "2" * 64,
        "risk": "R3",
    }
    results = []
    for rows in [(first, second), (second, first)]:
        records = {}
        for row in rows:
            builder._add(records, row)
        results.append(records["capability:same"])
    assert results[0] == results[1]
    assert results[0]["status"] not in {
        "active",
        "admitted",
        "reference",
        "reference_only",
        "executable",
    }


def test_opaque_values_are_not_stringified_into_projection_metadata():
    with pytest.raises(ValueError):
        builder._add({}, {"id": "opaque", "kind": "capability", "aliases": [object()]})


def test_missing_integration_state_cannot_synthesize_admission(tmp_path):
    write_json(
        tmp_path,
        "registry/metacognitive_capabilities.json",
        {"capabilities": [{"id": "missing", "target_owners": ["runtime/example.py"]}]},
    )
    index = builder.build_cognitive_index(tmp_path)
    row = next(x for x in index["records"] if x["id"] == "missing")
    assert row["status"] not in {"active", "admitted"}


def test_each_registry_image_is_opened_once_per_build(tmp_path, monkeypatch):
    target = capability_project(tmp_path, count=50)
    original = Path.open
    opens = []

    def opened(path, *args, **kwargs):
        if path == target:
            opens.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    index = builder.build_cognitive_index(tmp_path)
    assert index["record_count"] == 50
    assert opens == [target]


def test_oversized_registry_is_refused_before_body_open(tmp_path, monkeypatch):
    target = capability_project(tmp_path)
    original_stat = Path.stat
    original_open = Path.open

    def metadata(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path != target:
            return value
        fields = list(value)
        fields[6] = 1024 * 1024 + 1
        return type(value)(fields)

    def opened(path, *args, **kwargs):
        if path == target:
            pytest.fail("oversized registry body opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_skill_description_reads_only_a_bounded_frontmatter_prefix(
    tmp_path, monkeypatch
):
    skill_project(tmp_path)
    write_json(
        tmp_path,
        "registry/semantic_capability_index.json",
        {"records": [{"id": "example", "description": ""}]},
    )
    body = tmp_path / ".px/skills/example/SKILL.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(
        "---\nname: example\ndescription: Small safe description\n---\n"
        + "x" * (2 * 1024 * 1024),
        encoding="utf-8",
    )
    original = Path.open
    observed = [0]

    class PrefixReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            if size < 0 or size > 65537:
                pytest.fail("skill body read exceeded prefix request")
            result = self.stream.read(size)
            observed[0] += len(result)
            if observed[0] > 65537:
                pytest.fail("skill description read beyond its total prefix budget")
            return result

    def opened(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return PrefixReader(stream) if path == body else stream

    monkeypatch.setattr(Path, "open", opened)
    index = builder.build_cognitive_index(tmp_path)
    assert (
        next(row for row in index["records"] if row["id"] == "example")["summary"]
        == "Small safe description"
    )
    assert observed[0] <= 65537


def test_raw_procedure_is_not_projected_as_relation_text(tmp_path):
    leaf_project(tmp_path)
    index = builder.build_cognitive_index(tmp_path)
    row = next(x for x in index["records"] if x["id"] == "leaf")
    assert all("RAW PROCEDURE" not in value for value in row["relations"])


def test_declared_body_digest_must_match_the_compiled_image(tmp_path):
    leaf_project(tmp_path, digest="0" * 64)
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


@pytest.mark.skipif(
    __import__("os").name != "nt", reason="Actual Windows junction boundary"
)
def test_index_compiler_refuses_original_root_junction(tmp_path):
    import _winapi

    real = tmp_path / "real"
    real.mkdir()
    capability_project(real)
    alias = tmp_path / "alias"
    _winapi.CreateJunction(str(real), str(alias))
    with pytest.raises(ValueError):
        builder.build_cognitive_index(alias)


def test_unambiguous_declared_metadata_stays_searchable(tmp_path):
    capability_project(tmp_path)
    index = builder.build_cognitive_index(tmp_path)
    result = CognitiveNavigator(index).search(
        "Capability 0", limit=1, selectable_only=False
    )
    assert result.hits[0].identifier == "cap-0"


def test_disposable_current_source_compilation_preserves_leaf_navigation(tmp_path):
    """Repair descriptor hashes only in an owned fixture to expose caller issues.

    Root descriptor staleness remains a release reconciliation obligation. This
    fixture proves compiler/consumer compatibility after that separate action.
    """
    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[1]
    inputs = builder._CompilationInputs(root)
    for relative in tuple(inputs.inventory):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(inputs.image(root / relative))
    stale = []
    for path in inputs.indices:
        relative = path.relative_to(root)
        payload = inputs.json(path)
        for row in builder._rows(payload):
            body = row.get("path")
            if not body:
                continue
            digest = inputs.digest(root / body)
            for field in ("sha256", "source_sha256"):
                named_lineage = field == "source_sha256" and body.endswith(
                    "capability-scheduling.yaml"
                )
                if named_lineage:
                    named = next(
                        item
                        for item in inputs.json(root / body)["workflows"]
                        if item["name"] == row["id"]
                    )
                    assert row[field] == named["source_sha256"]
                if field in row and row[field] != digest and not named_lineage:
                    stale.append((relative.as_posix(), body, field, row[field], digest))
                    row[field] = digest
        write_json(tmp_path, relative, payload)
    print("DISPOSABLE_DESCRIPTOR_RECONCILIATION", json.dumps(stale))
    index = builder.build_cognitive_index(tmp_path)
    Draft202012Validator(
        json.loads(
            (root / "contracts/cognitive/cognitive-index.schema.json").read_text()
        )
    ).validate(index)
    assert builder.build_cognitive_index(tmp_path) == index
    result = CognitiveNavigator(index).search(
        "finite domain constraint solver", limit=3, selectable_only=False
    )
    assert any(
        hit.identifier == "finite-domain-constraint-solver" for hit in result.hits
    )
    assert index["kind_counts"]["capability"] >= 228
    assert index["kind_counts"]["script"] >= 61
    assert index["kind_counts"]["formula"] >= 103


@pytest.mark.parametrize("bad", [True, 17, {}, ["wrong"]])
def test_compiler_does_not_coerce_record_identities(tmp_path, bad):
    write_json(
        tmp_path,
        "registry/metacognitive_capabilities.json",
        {"capabilities": [{"id": bad}]},
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_catalog_revocation_cannot_be_overridden_by_semantic_status(tmp_path):
    skill_project(tmp_path)
    catalog = tmp_path / "registry/skill_catalog.toml"
    catalog.write_text(
        catalog.read_text().replace('status="active"', 'status="revoked"')
    )
    write_json(
        tmp_path,
        "registry/semantic_capability_index.json",
        {"records": [{"id": "example", "status": "active", "description": "Example"}]},
    )
    row = builder.build_cognitive_index(tmp_path)["records"][0]
    assert row["status"] == "conflicted"
    assert "status" in row["conflicts"]


def test_duplicate_alias_declarations_are_refused(tmp_path):
    skill_project(tmp_path)
    write_json(
        tmp_path,
        "registry/capability_aliases.json",
        {
            "records": [
                {"alias": "same", "owner": "example"},
                {"alias": "same", "owner": "example"},
            ]
        },
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_invalid_registry_rows_do_not_disappear(tmp_path):
    write_json(
        tmp_path, "registry/metacognitive_capabilities.json", {"capabilities": [42]}
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_prefix_accepts_complete_frontmatter_before_split_utf8_tail(tmp_path):
    skill_project(tmp_path)
    write_json(
        tmp_path,
        "registry/semantic_capability_index.json",
        {"records": [{"id": "example", "description": ""}]},
    )
    body = tmp_path / ".px/skills/example/SKILL.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    front = b"---\ndescription: Safe prefix\n---\n"
    body.write_bytes(front + b"x" * (65535 - len(front)) + "\u20ac".encode("utf-8"))
    assert (
        builder.build_cognitive_index(tmp_path)["records"][0]["summary"]
        == "Safe prefix"
    )


@pytest.mark.parametrize("size", [0, 1, 31, 32, 33, 100])
def test_prefix_has_explicit_truncation_and_preserves_bytes(tmp_path, size):
    from runtime.input_files import (
        contained_file,
        read_file_prefix,
        cooperative_deadline,
    )

    body = tmp_path / "body"
    body.write_bytes(b"x" * size)
    path, info = contained_file(tmp_path, "body")
    raw, truncated = read_file_prefix(
        path, info, limit=32, deadline=cooperative_deadline()
    )
    assert raw == b"x" * min(size, 32)
    assert truncated is (size > 32)


def test_prefix_refuses_changed_opened_source(tmp_path):
    from runtime.input_files import (
        contained_file,
        read_file_prefix,
        cooperative_deadline,
    )

    body = tmp_path / "body"
    body.write_bytes(b"one")
    path, info = contained_file(tmp_path, "body")
    body.write_bytes(b"changed")
    with pytest.raises(ValueError):
        read_file_prefix(path, info, limit=32, deadline=cooperative_deadline())


def test_leaf_revocation_cannot_be_overridden_by_catalog(tmp_path):
    body = leaf_project(tmp_path)
    payload = json.loads(body.read_text())
    payload["status"] = "revoked"
    body.write_text(json.dumps(payload))
    descriptor = tmp_path / ".px/skills/example/references/capability-index.json"
    value = json.loads(descriptor.read_text())
    value["records"][0]["sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
    descriptor.write_text(json.dumps(value))
    row = next(
        row
        for row in builder.build_cognitive_index(tmp_path)["records"]
        if row["id"] == "leaf"
    )
    assert row["status"] == "conflicted"


def test_explicit_capability_revocation_survives_integration_label(tmp_path):
    path = capability_project(tmp_path)
    payload = json.loads(path.read_text())
    payload["capabilities"][0]["status"] = "revoked"
    path.write_text(json.dumps(payload))
    assert builder.build_cognitive_index(tmp_path)["records"][0]["status"] not in {
        "active",
        "admitted",
    }


def test_all_declared_leaf_digests_are_checked(tmp_path):
    leaf_project(tmp_path)
    path = tmp_path / ".px/skills/example/references/capability-index.json"
    payload = json.loads(path.read_text())
    payload["records"][0]["source_sha256"] = "0" * 64
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_ambiguous_normalized_leaf_alias_cannot_choose_last_source(tmp_path):
    skill_project(tmp_path)
    write_json(
        tmp_path,
        "registry/brain_capabilities.json",
        {
            "capabilities": [
                {
                    "id": identifier,
                    "title": "Shared title",
                    "owner": "example",
                    "status": "active",
                    "path": "runtime/example.py",
                }
                for identifier in ("first", "second")
            ]
        },
    )
    write_json(
        tmp_path,
        "registry/capability_aliases.json",
        {"records": [{"alias": "Shared title", "owner": "example"}]},
    )
    results = []
    for _ in range(2):
        index = builder.build_cognitive_index(tmp_path)
        owner = next(row for row in index["records"] if row["key"] == "skill:example")
        assert owner["alias_conflicts"] == [
            {
                "alias": "Shared title",
                "candidates": ["capability:first", "capability:second"],
            }
        ]
        assert "Shared title" in owner["aliases"]
        results.append(index)
        path = tmp_path / "registry/brain_capabilities.json"
        payload = json.loads(path.read_text())
        payload["capabilities"].reverse()
        path.write_text(json.dumps(payload))
    # Source provenance hashes change with source byte order; routing does not.
    assert [r["key"] for r in results[0]["records"]] == [
        r["key"] for r in results[1]["records"]
    ]


def test_aggregate_body_inventory_rejects_before_any_body_open(tmp_path, monkeypatch):
    skill_project(tmp_path)
    rows = []
    bodies = set()
    for i in range(65):
        path = write_json(
            tmp_path,
            ".px/skills/example/references/capabilities/item-" + str(i) + ".json",
            {},
        )
        bodies.add(path)
        rows.append(
            {"id": "item-" + str(i), "path": path.relative_to(tmp_path).as_posix()}
        )
    write_json(
        tmp_path,
        ".px/skills/example/references/capability-index.json",
        {"records": rows},
    )
    original_stat, original_open = Path.stat, Path.open

    def metadata(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path in bodies:
            fields = list(value)
            fields[6] = 1024 * 1024
            return type(value)(fields)
        return value

    def opened(path, *args, **kwargs):
        if path in bodies:
            pytest.fail("body acquired before complete aggregate inventory admission")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", metadata)
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="aggregate"):
        builder.build_cognitive_index(tmp_path)


def test_present_malformed_optional_registry_fails(tmp_path):
    path = tmp_path / "registry/brain_capabilities.json"
    path.parent.mkdir()
    path.write_text('{"capabilities": [], "capabilities": []}')
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_discovery_skips_quarantine_without_descending(tmp_path, monkeypatch):
    import os

    capability_project(tmp_path)
    quarantine = tmp_path / ".px/skills/quarantine"
    quarantine.mkdir(parents=True)
    (quarantine / "unknown").write_text("excluded")
    original = os.scandir

    def scan(path):
        if Path(path) == quarantine:
            pytest.fail("quarantine was traversed")
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert builder.build_cognitive_index(tmp_path)["record_count"] == 1


def test_named_workflow_lineage_is_distinct_from_whole_file_digest(tmp_path):
    skill_project(tmp_path)
    declared = "a" * 64
    source = write_json(
        tmp_path,
        "orchestration/workflows/example.yaml",
        {
            "schema_version": "1.0",
            "workflow_count": 1,
            "workflows": [
                {
                    "name": "named-flow",
                    "source_sha256": declared,
                    "canonical_owner": "example",
                    "inputs": ["declared-input"],
                    "steps": [],
                }
            ],
        },
    )
    write_json(
        tmp_path,
        ".px/skills/example/references/workflow-index.json",
        {
            "records": [
                {
                    "id": "named-flow",
                    "path": source.relative_to(tmp_path).as_posix(),
                    "source_sha256": declared,
                }
            ],
        },
    )
    index = builder.build_cognitive_index(tmp_path)
    row = next(row for row in index["records"] if row["id"] == "named-flow")
    assert row["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert row["source_sha256_kind"] == "measured"
    assert row["declared_lineage_sha256"] == declared
    assert row["lineage_verification"] == "matching_named_source_declaration"
    assert row["authority"] == "not_evaluated"
    assert row["inputs"] == ["declared-input"]
    payload = json.loads(source.read_text())
    payload["workflows"][0]["source_sha256"] = "b" * 64
    source.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="lineage"):
        builder.build_cognitive_index(tmp_path)


def test_workflow_lineage_never_substitutes_for_explicit_byte_hash(tmp_path):
    skill_project(tmp_path)
    source = write_json(
        tmp_path,
        "orchestration/workflows/example.yaml",
        {
            "schema_version": "1.0",
            "workflow_count": 1,
            "workflows": [
                {
                    "name": "named-flow",
                    "source_sha256": "a" * 64,
                    "canonical_owner": "example",
                    "steps": [],
                }
            ],
        },
    )
    write_json(
        tmp_path,
        ".px/skills/example/references/workflow-index.json",
        {
            "records": [
                {
                    "id": "named-flow",
                    "path": source.relative_to(tmp_path).as_posix(),
                    "source_sha256": "a" * 64,
                    "sha256": "a" * 64,
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="digest"):
        builder.build_cognitive_index(tmp_path)


def test_missing_status_cannot_be_promoted_by_integration_metadata(tmp_path):
    path = capability_project(tmp_path)
    payload = json.loads(path.read_text())
    del payload["capabilities"][0]["status"]
    path.write_text(json.dumps(payload))
    assert builder.build_cognitive_index(tmp_path)["records"][0]["status"] not in {
        "active",
        "admitted",
    }


def test_locatorless_metadata_does_not_change_other_leaf_status(tmp_path):
    leaf_project(tmp_path)
    path = tmp_path / ".px/skills/example/references/capability-index.json"
    payload = json.loads(path.read_text())
    payload["records"].insert(0, {"id": "metadata-only"})
    payload["count"] = 2
    path.write_text(json.dumps(payload))
    rows = {
        row["id"]: row for row in builder.build_cognitive_index(tmp_path)["records"]
    }
    assert rows["metadata-only"]["status"] == "candidate"
    assert rows["leaf"]["status"] == "active"


@pytest.mark.parametrize(
    "old,new",
    [
        ('schema_version="1.0"', 'schema_version="99.0"'),
        ("default_active_limit=1", "default_active_limit=true"),
        ('loading_rule="metadata_only_at_startup_body_after_selection"\n', ""),
        ('admission_record="admission:example"\n', ""),
        ('tags=["test"]', 'tags=["test"]\nunknown_field=true'),
    ],
)
def test_compilation_reuses_the_complete_catalog_contract(tmp_path, old, new):
    skill_project(tmp_path)
    path = tmp_path / "registry/skill_catalog.toml"
    path.write_text(path.read_text().replace(old, new))
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_catalog_validation_and_digest_share_one_image(tmp_path, monkeypatch):
    skill_project(tmp_path)
    catalog = tmp_path / "registry/skill_catalog.toml"
    original = Path.open
    opened = []

    def open_file(path, *args, **kwargs):
        if path == catalog:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    index = builder.build_cognitive_index(tmp_path)
    row = index["records"][0]
    assert row["status"] == "active"
    assert opened == [catalog]
    assert any(
        item["path"] == "registry/skill_catalog.toml"
        for item in row["source_provenance"]
    )


def test_non_json_code_source_is_hashed_without_json_parsing(tmp_path):
    skill_project(tmp_path)
    source = tmp_path / "runtime/set_expression.py"
    source.parent.mkdir()
    source.write_text("{1, 2}\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(
        tmp_path,
        ".px/skills/example/references/scripts-index.json",
        {
            "records": [
                {
                    "id": "set-expression",
                    "path": "runtime/set_expression.py",
                    "sha256": digest,
                    "when_to_use": "A declared code source",
                }
            ]
        },
    )
    row = next(
        row
        for row in builder.build_cognitive_index(tmp_path)["records"]
        if row["kind"] == "script"
    )
    assert row["source_sha256"] == digest
    assert row["summary"] == "A declared code source"


@pytest.mark.parametrize(
    "raw", ["not bytes", b"x" * (1024 * 1024 + 1)], ids=["nonbytes", "oversized"]
)
def test_catalog_decoder_rejects_before_toml_parse(raw, monkeypatch):
    import runtime.skill_inputs as inputs

    def forbidden(*args, **kwargs):
        pytest.fail("invalid catalog image reached TOML parser")

    monkeypatch.setattr(inputs.tomllib, "loads", forbidden)
    with pytest.raises(ValueError):
        inputs.parse_catalog_metadata(raw)


def test_catalog_loader_invalid_count_remains_before_file_acquisition(
    tmp_path, monkeypatch
):
    import runtime.skill_inputs as inputs

    def forbidden(*args, **kwargs):
        pytest.fail("invalid catalog count reached file acquisition")

    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(ValueError):
        inputs.load_catalog_metadata(tmp_path, max_records=True)


def test_shared_skill_body_prefix_is_acquired_once_with_explicit_provenance(
    tmp_path, monkeypatch
):
    skill_project(tmp_path)
    catalog = tmp_path / "registry/skill_catalog.toml"
    header, row = catalog.read_text().split("[[skills]]", 1)
    other = row.replace('id="example"', 'id="other"').replace(
        "admission:example", "admission:other"
    )
    catalog.write_text(header + "[[skills]]" + row + "[[skills]]" + other)
    write_json(
        tmp_path,
        "registry/semantic_capability_index.json",
        {
            "records": [
                {"id": "example", "description": ""},
                {"id": "other", "description": ""},
            ]
        },
    )
    body = tmp_path / ".px/skills/example/SKILL.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    raw = b"---\ndescription: Shared bounded prefix\n---\n" + b"x" * (2 * 1024 * 1024)
    body.write_bytes(raw)
    original = Path.open
    opened = []

    def acquire(path, *args, **kwargs):
        if path == body:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", acquire)
    index = builder.build_cognitive_index(tmp_path)
    assert opened == [body]
    expected = {
        "path": body.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(raw[:65536]).hexdigest(),
        "bytes": 65536,
        "truncated": True,
    }
    assert all(row["prefix_provenance"] == [expected] for row in index["records"])


def test_expanded_record_output_is_bounded_before_global_sort(tmp_path, monkeypatch):
    body = leaf_project(tmp_path)
    payload = json.loads(body.read_text())
    payload["summary"] = "z" * 16000
    body.write_text(json.dumps(payload))
    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    rows = [
        {
            "id": "copy-" + str(i),
            "path": body.relative_to(tmp_path).as_posix(),
            "sha256": digest,
        }
        for i in range(500)
    ]
    write_json(
        tmp_path,
        ".px/skills/example/references/capability-index.json",
        {"records": rows},
    )
    original = sorted

    def guarded(values, *args, **kwargs):
        if isinstance(values, type({}.values())) and len(values) > 300:
            pytest.fail("expanded oversized projection reached global sorting")
        return original(values, *args, **kwargs)

    monkeypatch.setattr(builder, "sorted", guarded, raising=False)
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_edge_accumulation_has_a_byte_budget_as_well_as_a_count():
    edges = builder._Edges()
    with pytest.raises(ValueError):
        for i in range(10000):
            edges.add(("s" * 500 + str(i), "t" * 600, "depends_on"))


@pytest.mark.parametrize(
    "injected",
    [{"status_declarations": ["active"]}, {"declared_lineage_sha256": "a" * 64}],
    ids=["status", "lineage"],
)
def test_source_rows_cannot_inject_compiler_provenance_fields(tmp_path, injected):
    write_json(
        tmp_path,
        "registry/brain_capabilities.json",
        {
            "capabilities": [
                {
                    "id": "declared",
                    "owner": "owner",
                    "status": "revoked",
                    "path": "runtime/source.py",
                    **injected,
                }
            ]
        },
    )
    row = builder.build_cognitive_index(tmp_path)["records"][0]
    assert row["scalar_declarations"]["status"] == ["revoked"]
    assert row["declared_lineage_sha256"] == ""
    assert row["lineage_verification"] == "not_evaluated"


@pytest.mark.parametrize(
    "relative,key",
    [
        ("registry/brain_capabilities.json", "capabilities"),
        ("registry/project_stream_capabilities.json", "capabilities"),
        ("registry/agency_agent_registry.json", "agents"),
        ("registry/brain_formulas.json", "formulas"),
        ("registry/skill_orchestrations.json", "orchestrations"),
        ("registry/knowledge_sources.json", "knowledge_sources"),
    ],
    ids=["brain", "target", "agent", "formula", "workflow", "knowledge"],
)
def test_missing_source_identity_cannot_disappear(tmp_path, relative, key):
    write_json(tmp_path, relative, {key: [{}]})
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


@pytest.mark.parametrize(
    "steps", ["not-a-list", [7], [{}]], ids=["scalar", "nonobject", "empty-step"]
)
@pytest.mark.parametrize("nested", [False, True], ids=["registry", "nested"])
def test_malformed_workflow_steps_cannot_disappear(tmp_path, steps, nested):
    if nested:
        write_json(
            tmp_path,
            ".px/skills/example/references/workflow-index.json",
            {"records": [{"id": "workflow", "path": "workflows/example.json"}]},
        )
        write_json(tmp_path, "workflows/example.json", {"steps": steps})
    else:
        write_json(
            tmp_path,
            "registry/skill_orchestrations.json",
            {"orchestrations": [{"id": "workflow", "steps": steps}]},
        )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_duplicate_local_workflow_step_identity_is_refused(tmp_path):
    write_json(
        tmp_path,
        "registry/skill_orchestrations.json",
        {
            "orchestrations": [
                {
                    "id": "workflow",
                    "steps": [
                        {"id": "same", "skill": "one"},
                        {"id": "same", "skill": "two"},
                    ],
                }
            ]
        },
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_local_workflow_steps_do_not_become_global_capability_references(tmp_path):
    write_json(
        tmp_path,
        "registry/skill_orchestrations.json",
        {
            "orchestrations": [
                {
                    "id": "workflow",
                    "steps": [
                        {"id": "load", "requires": []},
                        {"id": "select", "requires": ["load"]},
                    ],
                }
            ]
        },
    )
    result = builder.build_cognitive_index(tmp_path)
    assert result["record_count"] == 1
    assert result["edges"] == []


def test_global_member_edges_preserve_original_workflow_step_position(tmp_path):
    write_json(
        tmp_path,
        "registry/skill_orchestrations.json",
        {
            "orchestrations": [
                {
                    "id": "workflow",
                    "steps": [
                        {"id": "local", "requires": []},
                        {"id": "invoke", "skill": "external-member"},
                    ],
                }
            ]
        },
    )
    result = builder.build_cognitive_index(tmp_path)
    assert result["edges"] == [
        {
            "source": "workflow:workflow",
            "target": "unresolved:external-member",
            "relation": "step:1",
        }
    ]


def test_dependency_resolution_count_is_not_a_boolean(tmp_path):
    write_json(
        tmp_path,
        "registry/cognitive_dependency_resolutions.json",
        {
            "count": True,
            "records": [
                {
                    "identifier": "unused",
                    "target_key": "skill:unused",
                    "status": "reviewed",
                }
            ],
        },
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


def test_workflow_member_aliases_cannot_name_different_targets(tmp_path):
    write_json(
        tmp_path,
        "registry/skill_orchestrations.json",
        {
            "orchestrations": [
                {
                    "id": "workflow",
                    "steps": [
                        {"id": "invoke", "skill": "first", "capability": "second"}
                    ],
                }
            ]
        },
    )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)


@pytest.mark.parametrize("nested", [True, False], ids=["descriptor", "knowledge"])
def test_competing_collection_aliases_cannot_hide_records(tmp_path, nested):
    if nested:
        write_json(
            tmp_path,
            ".px/skills/example/references/capability-index.json",
            {"records": [], "capabilities": [{"id": "hidden"}]},
        )
    else:
        write_json(
            tmp_path,
            "registry/knowledge_sources.json",
            {"knowledge_sources": [], "sources": [{"id": "hidden"}]},
        )
    with pytest.raises(ValueError):
        builder.build_cognitive_index(tmp_path)
