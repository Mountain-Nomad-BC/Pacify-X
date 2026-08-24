from __future__ import annotations

import json
import hashlib
import base64
import struct
from dataclasses import replace
from pathlib import Path
import pytest
import runtime.skill_studio as skill_studio_module

from runtime.skill_studio import (
    MAX_SKILL_DIRECTORIES,
    MAX_SKILL_FILE_BYTES,
    SkillStudio,
    _canonical_skill_path,
    _tree_attestation,
)
from runtime.native_skills import build_skill_index
from runtime.studio_models import SkillPackage, StudioVersionConflict, allocate_studio_version


def source(root, name="source", version="1.0.0"):
    path = root / name
    path.mkdir()
    (path / "contracts").mkdir()
    (path / "agents").mkdir()
    (path / "tests").mkdir()
    (path / "resources").mkdir()
    (path / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    native_manifest = {
        "schema_version": "px.native-skill-package/1.0",
        "id": "demo",
        "version": version,
        "domain": "px-standard",
    }
    manifest_text = json.dumps(native_manifest, indent=2) + "\n"
    (path / "capability.json").write_text(manifest_text, encoding="utf-8")
    (path / "skill.yaml").write_text(manifest_text, encoding="utf-8")
    (path / "agents/openai.yaml").write_text(
        'interface:\n  display_name: "Demo"\n  short_description: "Demo skill"\n',
        encoding="utf-8",
    )
    (path / "contracts/manifest.json").write_text(
        json.dumps(
            {"schema_version": "px.skill-contract-links/1.0", "contracts": []}
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "tests/validation.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-test/1.1",
                "cases": [
                    {
                        "name": "required-package-files",
                        "assertion": {
                            "kind": "required-files",
                            "paths": ["SKILL.md", "capability.json", "skill.yaml"],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "resources/index.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-resources/1.0",
                "resources": [
                    "agents/openai.yaml",
                    "capability.json",
                    "contracts/manifest.json",
                    "SKILL.md",
                    "skill.yaml",
                    "tests/validation.json",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def package():
    return SkillPackage(
        "skill:demo",
        "1.0.0",
        "owner",
        ("demo task",),
        ("unrelated task",),
        ("read",),
        ("read",),
        ("resources/index.json",),
        ("contracts/manifest.json",),
        ("tests/validation.json",),
        {"source": "local", "license": "Apache-2.0"},
    )


def projection_scaffold(root) -> None:
    (root / "registry/skill_packages").mkdir(parents=True)
    (root / "registry/admission_ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "allowed_dispositions": ["adopt"],
                "promotion_requirements": [],
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "registry/skill_catalog.toml").write_text(
        'schema_version = "1.0"\n', encoding="utf-8"
    )
    (root / ".px").mkdir(exist_ok=True)
    (root / ".px/skill-index.json").write_text(
        json.dumps(build_skill_index([])), encoding="utf-8"
    )


def materialization_attestation(root) -> tuple[str, int]:
    hasher = hashlib.sha256()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().encode("utf-8"),
    )
    hasher.update(b"px.skill-tree/2\0")
    hasher.update(struct.pack(">Q", len(files)))
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        hasher.update(struct.pack(">Q", len(relative)))
        hasher.update(relative)
        hasher.update(struct.pack(">Q", len(content)))
        hasher.update(content)
    return hasher.hexdigest(), len(files)


def provenance_bound_package(root: Path) -> tuple[SkillPackage, Path, dict[str, object]]:
    preserved_parent = root / ".px/preserved-skills/initial/workspace-original"
    preserved_parent.mkdir(parents=True, exist_ok=True)
    preserved = source(preserved_parent, "demo")
    rows, tree_sha256 = _tree_attestation(preserved)
    body_sha256 = hashlib.sha256((preserved / "SKILL.md").read_bytes()).hexdigest()
    exact = {
        "schema_version": "px.preserved-skill-provenance/1.0",
        "skill_id": "skill:demo",
        "source_version": "1.0.0",
        "origin": "workspace-agents-original",
        "package_relative": preserved.relative_to(root).as_posix(),
        "tree_sha256": tree_sha256,
        "body_sha256": body_sha256,
        "file_count": len(rows),
    }
    bound = replace(
        package(),
        version="1.0.1",
        provenance={
            **package().provenance,
            "preserved_original_schema_version": str(exact["schema_version"]),
            "preserved_original_skill_id": str(exact["skill_id"]),
            "preserved_original_source_version": str(exact["source_version"]),
            "preserved_original_origin": str(exact["origin"]),
            "preserved_original_package_relative": str(exact["package_relative"]),
            "preserved_original_tree_sha256": str(exact["tree_sha256"]),
            "preserved_original_body_sha256": str(exact["body_sha256"]),
            "preserved_original_file_count": str(exact["file_count"]),
        },
    )
    return bound, preserved, exact


def test_preserved_original_provenance_survives_candidate_admission_and_promotion(
    tmp_path,
):
    projection_scaffold(tmp_path)
    bound, preserved, exact = provenance_bound_package(tmp_path)
    studio = SkillStudio(tmp_path)
    candidate = source(tmp_path, "candidate", version="1.0.1")
    token = studio.admit_source(candidate, approved_by="human:owner")

    draft = studio.stage_draft(bound, candidate, source_token=token)
    assert draft["preserved_original"] == exact
    validation = studio.validate(bound)
    assert validation["passed"] is True
    assert validation["preserved_original"] == exact
    admission = studio.admit(bound, approved=True, approver="human:owner")
    assert admission["decision"] == "admitted"
    assert admission["preserved_original"] == exact
    promotion = studio.promote(bound, approved=True)
    assert promotion["preserved_original"] == exact
    assert preserved.is_dir()

    index = json.loads((tmp_path / ".px/skill-index.json").read_text(encoding="utf-8"))
    indexed = next(row for row in index["records"] if row["id"] == "demo")
    assert indexed["backup"] == exact["package_relative"]
    projected = json.loads(
        (tmp_path / "registry/skill_packages/demo.json").read_text(encoding="utf-8")
    )
    assert projected["preserved_original"] == exact


def test_preserved_original_substitution_fails_closed_after_admission(tmp_path):
    bound, preserved, _exact = provenance_bound_package(tmp_path)
    studio = SkillStudio(tmp_path)
    candidate = source(tmp_path, "candidate", version="1.0.1")
    token = studio.admit_source(candidate, approved_by="human:owner")
    studio.stage_draft(bound, candidate, source_token=token)
    assert studio.validate(bound)["passed"] is True
    assert studio.admit(bound, approved=True, approver="human:owner")["decision"] == "admitted"

    (preserved / "SKILL.md").write_text("# Substituted\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="preserved-original package identity changed"):
        studio.promote(bound, approved=True)


def test_originals_are_preserved_and_skill_lifecycle_is_versioned_and_recoverable(
    tmp_path,
):
    studio = SkillStudio(tmp_path)
    original = source(tmp_path, "original")
    manifest = studio.preserve_originals({"user-original": original})
    assert manifest["immutable"] is True and original.is_dir()
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    draft = studio.stage_draft(package(), draft_source, source_token=token)
    assert draft["admission_state"] == "unadmitted"
    assert studio.validate(package())["passed"] is True
    assert (
        studio.admit(package(), approved=True, approver="human:owner")["decision"]
        == "admitted"
    )
    first = studio.promote(package(), approved=True)
    assert first["rollback_available"] is False
    assert original.is_dir() and (tmp_path / first["target_relative"]).is_dir()


def test_skill_stage_preserves_committed_truth_when_post_publish_closure_degrades(
    tmp_path, monkeypatch
):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "post-publish-warning")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    original_mark_run_ended = studio.manager.mark_run_ended

    def degraded_closure(run_id, state, *args, **kwargs):
        if state.value == "completed":
            raise RuntimeError("simulated closure failure")
        return original_mark_run_ended(run_id, state, *args, **kwargs)

    monkeypatch.setattr(studio.manager, "mark_run_ended", degraded_closure)
    receipt = studio.stage_draft(package(), draft_source, source_token=token)

    assert receipt["schema_version"] == "px.skill-draft/1.1"
    assert receipt["created"] is True
    assert receipt["file_count"] == len(receipt["files"])
    assert receipt["manifest"]["skill_id"] == package().skill_id
    assert receipt["cleanup_warnings"] == [
        "run closure degraded: simulated closure failure",
        "owning run is active or recoverable",
        "resource is not marked reclaimable",
    ]
    assert next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/package-record.json"
        )
    ).is_file()


def test_skill_publish_failure_remains_authoritative_when_reconciliation_fails(
    tmp_path, monkeypatch
):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "failed-publication")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    calls = []

    def fail_publication(*_args):
        raise ValueError("authoritative-publication-failure")

    def fail_closure(*_args, **_kwargs):
        calls.append("closure")
        raise RuntimeError("closure-failure")

    def fail_reclaim(*_args, **_kwargs):
        calls.append("reclaim")
        raise RuntimeError("reclaim-failure")

    monkeypatch.setattr("runtime.skill_studio.publish_directory_no_replace", fail_publication)
    monkeypatch.setattr(studio.manager, "mark_run_ended", fail_closure)
    monkeypatch.setattr(studio.manager, "reclaim", fail_reclaim)
    with pytest.raises(ValueError, match="authoritative-publication-failure") as refused:
        studio.stage_draft(package(), draft_source, source_token=token)
    assert calls == ["closure", "reclaim"]
    assert any("closure-failure" in note for note in refused.value.__notes__)
    assert any("reclaim-failure" in note for note in refused.value.__notes__)


def test_skill_stage_revalidates_allocation_and_preserves_existing_revision(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    allocation = allocate_studio_version(
        tmp_path, "skill", package().skill_id, package().version
    )
    source_record = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/package-record.json"
        )
    )
    assert set(allocation) == {
        "schema_version", "kind", "identity", "source_version", "source_scope",
        "source_revision_sha256", "source_content_sha256", "candidate_version",
        "occupied_versions_sha256", "observed_utc",
    }
    assert allocation["kind"] == "skill"
    assert allocation["identity"] == package().skill_id
    assert allocation["source_scope"] == "studio-physical"
    assert allocation["candidate_version"] == "1.0.1"
    assert allocation["source_revision_sha256"] == json.loads(
        source_record.read_text(encoding="utf-8")
    )["manifest_sha256"]
    assert len(allocation["source_content_sha256"]) == 64
    candidate = replace(package(), version="1.0.1")
    studio.stage_draft(
        candidate,
        draft_source,
        source_token=token,
        version_allocation=allocation,
    )
    record_path = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.1/package-record.json"
        )
    )
    original = record_path.read_bytes()
    replay = studio.stage_draft(
        candidate,
        draft_source,
        source_token=token,
        version_allocation=allocation,
    )
    assert replay["created"] is False and replay["idempotent_replay"] is True
    assert record_path.read_bytes() == original


@pytest.mark.parametrize(
    "mutation",
    (
        "payload",
        "undeclared-key",
        "unexpected-entry",
        "manifest-hash",
        "source-tree-hash",
        "source-token",
        "file-count",
        "identity",
        "version",
        "created-state",
    ),
)
def test_skill_exact_replay_rejects_each_corrupted_revision(tmp_path, mutation):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "replay-source")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    record_path = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/package-record.json"
        )
    )
    if mutation == "payload":
        record_path.with_name("payload").joinpath("SKILL.md").write_text(
            "changed\n", encoding="utf-8"
        )
    elif mutation == "unexpected-entry":
        record_path.with_name("unexpected.txt").write_text("x", encoding="utf-8")
    else:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if mutation == "undeclared-key":
            record["undeclared"] = True
        elif mutation == "manifest-hash":
            record["manifest_sha256"] = "f" * 64
        elif mutation == "source-tree-hash":
            record["source_tree_sha256"] = "f" * 64
        elif mutation == "source-token":
            record["source_authority_token"] = "substituted"
        elif mutation == "file-count":
            record["file_count"] += 1
        elif mutation == "identity":
            record["manifest"]["skill_id"] = "skill:substituted"
        elif mutation == "version":
            record["manifest"]["version"] = "9.9.9"
        else:
            record["created"] = False
        record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        studio.stage_draft(package(), draft_source, source_token=token)
    assert refused.value.reason == "immutable-skill-revision-differs"


def test_skill_source_admission_rehashes_exact_external_materialization(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "attested-source")
    tree_sha256, file_count = materialization_attestation(draft_source)
    admission = studio.admit_source(
        draft_source,
        approved_by="human:owner",
        expected_tree_sha256=tree_sha256,
        expected_file_count=file_count,
    )
    assert isinstance(admission, dict)
    assert set(admission) == {
        "schema_version", "source_token", "source_directory",
        "source_tree_sha256", "file_count",
    }
    assert admission["schema_version"] == "px.skill-source-admission/1.0"
    assert admission["source_directory"] == str(draft_source.resolve())
    assert admission["source_tree_sha256"] == tree_sha256
    assert admission["file_count"] == file_count
    staged = studio.stage_draft(
        package(), draft_source, source_token=str(admission["source_token"])
    )
    assert staged["source_tree_sha256"] == tree_sha256

    (draft_source / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="materialization attestation"):
        studio.admit_source(
            draft_source,
            approved_by="human:owner",
            expected_tree_sha256=tree_sha256,
            expected_file_count=file_count,
        )


def test_skill_tree_commitment_is_length_framed_and_cross_runtime_ordered(tmp_path):
    left = source(tmp_path, "left")
    right = source(tmp_path, "right")
    (left / "a").write_bytes(b"x")
    (left / "b").write_bytes(b"y\0bb\0z")
    (right / "a").write_bytes(b"x\0b\0y")
    (right / "bb").write_bytes(b"z")
    left_reference = materialization_attestation(left)
    right_reference = materialization_attestation(right)
    assert left_reference[1] == right_reference[1]
    assert left_reference[0] != right_reference[0]
    assert _tree_attestation(left)[1] == left_reference[0]
    assert _tree_attestation(right)[1] == right_reference[0]


def test_skill_tree_commitment_matches_shared_cross_runtime_vectors(tmp_path):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/studio-skill-tree-vectors.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["schema_version"] == "px.skill-tree-vectors/1.0"
    observed = {}
    for vector in fixture["vectors"]:
        root = tmp_path / vector["id"]
        root.mkdir()
        for file in vector["files"]:
            target = root / Path(file["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(file["content_base64"], validate=True))
        rows, tree_sha256 = _tree_attestation(root)
        assert len(rows) == len(vector["files"])
        assert tree_sha256 == vector["expected_sha256"]
        observed[vector["id"]] = tree_sha256
    assert observed["delimiter-left"] != observed["delimiter-right"]


def test_skill_source_rejects_injected_ignored_control_and_empty_entries(tmp_path):
    for name, mutate in (
        ("cache", lambda root: (root / "__pycache__").mkdir()),
        ("control", lambda root: (root / "package-record.json").write_text("{}", encoding="utf-8")),
        ("empty", lambda root: (root / "resources/empty").mkdir()),
    ):
        root = source(tmp_path, name)
        mutate(root)
        with pytest.raises(ValueError, match="injected|empty|unowned"):
            _tree_attestation(root)


def test_skill_source_rejects_duplicate_canonical_directory_aliases(tmp_path):
    root = source(tmp_path, "aliases")
    upper = root / "Alias"
    lower = root / "alias"
    upper.mkdir()
    try:
        lower.mkdir()
    except FileExistsError:
        pytest.skip("host filesystem does not permit distinct case aliases")
    (upper / "one.txt").write_text("one", encoding="utf-8")
    (lower / "two.txt").write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical path aliases"):
        _tree_attestation(root)


def test_skill_alias_policy_matches_javascript_unicode_lowercase(tmp_path):
    assert _canonical_skill_path("Straße/one.txt") == "straße/one.txt"
    assert _canonical_skill_path("STRASSE/two.txt") == "strasse/two.txt"
    assert _canonical_skill_path("Straße") != _canonical_skill_path("STRASSE")


def test_skill_source_directory_and_entry_traversal_is_bounded(tmp_path):
    root = source(tmp_path, "directory-bound")
    for index in range(MAX_SKILL_DIRECTORIES + 1):
        (root / f"directory-{index}").mkdir()
    with pytest.raises(ValueError, match="directory count|entry count"):
        _tree_attestation(root)


def test_skill_source_uses_the_shared_512_kib_per_file_bound(tmp_path):
    root = source(tmp_path, "file-bound")
    (root / "resources/oversized.bin").write_bytes(
        b"x" * (MAX_SKILL_FILE_BYTES + 1)
    )
    assert MAX_SKILL_FILE_BYTES == 512 * 1024
    with pytest.raises(ValueError, match="oversized file"):
        _tree_attestation(root)


def test_skill_runtime_stages_only_the_normalized_canonical_version(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "normalized-version-source")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    normalized = replace(package(), version=" 1.0.0-RC.1 ")
    assert normalized.version == "1.0.0-rc.1"
    record = studio.stage_draft(normalized, draft_source, source_token=token)
    assert record["manifest"]["version"] == "1.0.0-rc.1"
    revision = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0-rc.1/package-record.json"
        )
    )
    assert revision.is_file()


def test_skill_physical_allocation_rejects_tampered_predecessor_record(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    source_record = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/package-record.json"
        )
    )
    envelope = json.loads(source_record.read_text(encoding="utf-8"))
    envelope["manifest"]["version"] = "9.9.9"
    source_record.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(FileExistsError) as refused:
        allocate_studio_version(
            tmp_path, "skill", package().skill_id, package().version
        )
    assert refused.value.reason == "source-revision-invalid"


def test_skill_allocation_accepts_only_hash_bound_external_authenticated_source(tmp_path):
    allocation = allocate_studio_version(
        tmp_path,
        "skill",
        package().skill_id,
        "4.2.0",
        source_scope="external-authenticated",
        source_revision_sha256="a" * 64,
        source_content_sha256="b" * 64,
    )
    assert allocation["source_scope"] == "external-authenticated"
    assert allocation["candidate_version"] == "4.2.1"
    with pytest.raises(FileExistsError) as refused:
        allocate_studio_version(
            tmp_path,
            "agent",
            "agent:external",
            "1.0.0",
            source_scope="external-authenticated",
            source_revision_sha256="a" * 64,
            source_content_sha256="b" * 64,
        )
    assert refused.value.reason == "external-source-not-allowed"


def test_skill_promotion_fails_without_admission(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    with pytest.raises(PermissionError, match="admission"):
        studio.promote(package(), approved=True)


def test_skill_validation_is_idempotent_and_metadata_is_not_promoted(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    assert studio.validate(package())["passed"] is True
    assert studio.validate(package())["passed"] is True
    studio.admit(package(), approved=True, approver="human:owner")
    promoted = studio.promote(package(), approved=True)
    target = tmp_path / promoted["target_relative"]
    assert (target / "SKILL.md").is_file()
    assert (
        not (target / "package-record.json").exists()
        and not (target / "validation-receipt.json").exists()
    )


def test_skill_validation_rejects_missing_openai_interface(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    (draft_source / "agents/openai.yaml").unlink()
    (draft_source / "agents/README.md").write_text(
        "Interface metadata intentionally omitted for this negative case.\n",
        encoding="utf-8",
    )
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)

    result = studio.validate(package())

    assert result["passed"] is False
    assert result["checks"]["openai_interface_valid"] is False


def test_skill_tamper_after_admission_blocks_promotion(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    studio.validate(package())
    studio.admit(package(), approved=True, approver="human:owner")
    payload = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/payload/SKILL.md"
        )
    )
    payload.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="changed"):
        studio.promote(package(), approved=True)


def test_nested_skill_source_symlink_is_rejected(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")
    try:
        (draft_source / "resources/link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="links|reparse"):
        studio.admit_source(draft_source, approved_by="human:owner")


def test_caller_authored_pass_flag_is_not_executed(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    (draft_source / "tests/validation.json").write_text(
        '{"passed":true}\n', encoding="utf-8"
    )
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    result = studio.validate(package())
    assert result["passed"] is False
    assert result["behavioral_tests"][0]["executed"] is False
    assert result["behavioral_tests"][0]["runner"] == "unsupported_test_contract"


def test_oversized_skill_source_is_rejected_during_admission(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    (draft_source / "resources/large.txt").write_text(
        "x" * (MAX_SKILL_FILE_BYTES + 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="oversized file"):
        studio.admit_source(draft_source, approved_by="human:owner")


def test_secret_and_obfuscated_network_import_are_rejected_by_validation(tmp_path):
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    (draft_source / "resources/secret.txt").write_text(
        "api_key=ABCDEFGHIJKLMNOPQRSTUVWX\n",
        encoding="utf-8",
    )
    (draft_source / "resources/network.py").write_text(
        "module = __import__('urllib' + '.request', fromlist=['urlopen'])\n"
        "getattr(module, 'url' + 'open')('https://example.invalid')\n",
        encoding="utf-8",
    )
    bounded = replace(
        package(),
        resources=(
            "resources/index.json",
            "resources/secret.txt",
            "resources/network.py",
        ),
    )
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(bounded, draft_source, source_token=token)
    result = studio.validate(bounded)
    assert result["passed"] is False
    assert "resources/secret.txt" in result["secret_findings"]
    assert any(
        row["path"] == "resources/network.py"
        and row["effect"] == "network"
        and row["declared"] is False
        for row in result["script_effect_findings"]
    )


def test_skill_projection_updates_use_an_authenticated_recoverable_transaction(
    tmp_path,
):
    projection_scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    studio.validate(package())
    studio.admit(package(), approved=True, approver="human:owner")
    receipt = studio.promote(package(), approved=True)
    assert set(receipt["projection_updates"]) == {
        ".px/skill-index.json",
        "registry/admission_ledger.json",
        "registry/skill_catalog.toml",
        "registry/skill_packages/demo.json",
    }
    projected = json.loads(
        (tmp_path / "registry/skill_packages/demo.json").read_text(encoding="utf-8")
    )
    assert projected["status"] == "active"
    assert projected["body_sha256"] == hashlib.sha256(
        (tmp_path / ".px/skills/demo/SKILL.md").read_bytes()
    ).hexdigest()
    assert projected["clean_room"] is False
    assert projected["validation_freshness"] == "current"
    assert projected["effects"] == ["read"]
    assert projected["tests"] == ".px/skills/demo/tests/validation.json"
    assert projected["provenance"]["type"] == "skill_studio_admitted_source"
    admission = json.loads(
        (tmp_path / "registry/admission_ledger.json").read_text(encoding="utf-8")
    )
    assert admission["records"] == [
        {
            "effects": ["read"],
            "id": "demo",
            "implementation": "skill_studio",
            "notes": "Promoted through the authenticated Pacify-X Skill Studio lifecycle.",
            "source_disposition": "adopt",
            "status": "active",
            "validation": {"failed": 0, "passed": 1},
        }
    ]
    manifest_path = next(
        (
            tmp_path / ".engineering-bootstrap/studios/skills/lifecycle-transactions"
        ).glob("*/manifest.json")
    )
    signed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert studio.authority.verify_receipt(signed)["state"] == "committed"
    assert receipt["lifecycle_transaction_relative"] == manifest_path.parent.relative_to(tmp_path).as_posix()
    assert studio.recover_projection_transactions()["valid"] is True


def test_skill_rollback_restores_package_and_every_projection_before_image(tmp_path):
    projection_scaffold(tmp_path)
    studio = SkillStudio(tmp_path)

    first_source = source(tmp_path, "first")
    first_package = package()
    first_token = studio.admit_source(first_source, approved_by="human:owner")
    studio.stage_draft(first_package, first_source, source_token=first_token)
    assert studio.validate(first_package)["passed"] is True
    assert studio.admit(first_package, approved=True, approver="human:owner")["decision"] == "admitted"
    first_promotion = studio.promote(first_package, approved=True)
    assert first_promotion["rollback_available"] is False

    target = tmp_path / first_promotion["target_relative"]
    first_target_tree = materialization_attestation(target)[0]
    projection_paths = (
        tmp_path / ".px/skill-index.json",
        tmp_path / "registry/admission_ledger.json",
        tmp_path / "registry/skill_catalog.toml",
        tmp_path / "registry/skill_packages/demo.json",
    )
    first_projection_bytes = {path: path.read_bytes() for path in projection_paths}

    second_source = source(tmp_path, "second", version="1.1.0")
    (second_source / "SKILL.md").write_text("# Demo revision two\n", encoding="utf-8")
    second_package = replace(first_package, version="1.1.0")
    second_token = studio.admit_source(second_source, approved_by="human:owner")
    studio.stage_draft(second_package, second_source, source_token=second_token)
    assert studio.validate(second_package)["passed"] is True
    assert studio.admit(second_package, approved=True, approver="human:owner")["decision"] == "admitted"
    second_promotion = studio.promote(second_package, approved=True)
    assert second_promotion["rollback_available"] is True
    assert second_promotion["projection_transaction_relative"]
    assert materialization_attestation(target)[0] != first_target_tree

    promotion_receipt = next(
        (
            tmp_path / ".engineering-bootstrap/studios/skills"
        ).glob("*/revisions/1.1.0/promotion-receipt.json")
    )
    rollback = studio.rollback(
        promotion_receipt, approved=True, approver="human:owner"
    )

    assert rollback["schema_version"] == "px.skill-rollback-receipt/1.2"
    assert rollback["version"] == "1.1.0"
    assert set(rollback["projection_restorations"]) == {
        path.relative_to(tmp_path).as_posix() for path in projection_paths
    }
    assert materialization_attestation(target)[0] == first_target_tree
    assert all(path.read_bytes() == first_projection_bytes[path] for path in projection_paths)


def test_promotion_lifecycle_transaction_recovers_after_canonical_publication(
    tmp_path, monkeypatch
):
    projection_scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "promotion-crash")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    assert studio.validate(package())["passed"] is True
    assert studio.admit(package(), approved=True, approver="human:owner")["decision"] == "admitted"
    original_atomic = skill_studio_module._atomic_bytes
    failed = False

    def fail_first_projection(path, payload):
        nonlocal failed
        if not failed and path == tmp_path / ".px/skill-index.json":
            failed = True
            raise OSError("simulated crash after canonical publication")
        return original_atomic(path, payload)

    monkeypatch.setattr(skill_studio_module, "_atomic_bytes", fail_first_projection)
    with pytest.raises(OSError, match="simulated crash"):
        studio.promote(package(), approved=True)
    assert (tmp_path / ".px/skills/demo").is_dir()
    monkeypatch.setattr(skill_studio_module, "_atomic_bytes", original_atomic)

    restarted = SkillStudio(tmp_path)
    receipt = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.0.0/promotion-receipt.json"
        )
    )
    assert restarted.authority.verify_receipt(
        json.loads(receipt.read_text(encoding="utf-8"))
    )["version"] == "1.0.0"
    assert restarted.recover_lifecycle_transactions()["completed"] == []


def test_rollback_lifecycle_transaction_recovers_after_canonical_publication(
    tmp_path, monkeypatch
):
    projection_scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    first_source = source(tmp_path, "rollback-first")
    first = package()
    token = studio.admit_source(first_source, approved_by="human:owner")
    studio.stage_draft(first, first_source, source_token=token)
    studio.validate(first)
    studio.admit(first, approved=True, approver="human:owner")
    studio.promote(first, approved=True)
    first_tree = _tree_attestation(tmp_path / ".px/skills/demo")[1]
    second_source = source(tmp_path, "rollback-second", version="1.1.0")
    (second_source / "SKILL.md").write_text("# Second\n", encoding="utf-8")
    second = replace(first, version="1.1.0")
    token = studio.admit_source(second_source, approved_by="human:owner")
    studio.stage_draft(second, second_source, source_token=token)
    studio.validate(second)
    studio.admit(second, approved=True, approver="human:owner")
    studio.promote(second, approved=True)
    promotion_receipt = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.1.0/promotion-receipt.json"
        )
    )
    original_atomic = skill_studio_module._atomic_bytes
    failed = False

    def fail_first_projection(path, payload):
        nonlocal failed
        if not failed and path == tmp_path / ".px/skill-index.json":
            failed = True
            raise OSError("simulated rollback crash after canonical publication")
        return original_atomic(path, payload)

    monkeypatch.setattr(skill_studio_module, "_atomic_bytes", fail_first_projection)
    with pytest.raises(OSError, match="simulated rollback crash"):
        studio.rollback(promotion_receipt, approved=True, approver="human:owner")
    monkeypatch.setattr(skill_studio_module, "_atomic_bytes", original_atomic)

    restarted = SkillStudio(tmp_path)
    assert _tree_attestation(tmp_path / ".px/skills/demo")[1] == first_tree
    rollback_receipt = promotion_receipt.with_name("rollback-receipt.json")
    assert restarted.authority.verify_receipt(
        json.loads(rollback_receipt.read_text(encoding="utf-8"))
    )["version"] == "1.1.0"
    assert restarted.recover_lifecycle_transactions()["completed"] == []


def test_lifecycle_recovery_refuses_external_canonical_drift(tmp_path, monkeypatch):
    projection_scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    first_source = source(tmp_path, "drift-first")
    token = studio.admit_source(first_source, approved_by="human:owner")
    studio.stage_draft(package(), first_source, source_token=token)
    studio.validate(package())
    studio.admit(package(), approved=True, approver="human:owner")
    original_roll = studio._roll_lifecycle_transaction_forward
    monkeypatch.setattr(
        studio,
        "_roll_lifecycle_transaction_forward",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("simulated stop before apply")),
    )
    with pytest.raises(OSError, match="simulated stop"):
        studio.promote(package(), approved=True)
    monkeypatch.setattr(studio, "_roll_lifecycle_transaction_forward", original_roll)
    target = tmp_path / ".px/skills/demo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# External drift\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="canonical skill changed outside"):
        SkillStudio(tmp_path)


def test_skill_promotion_refuses_existing_projection_denominator_drift(tmp_path):
    projection_scaffold(tmp_path)
    index_path = tmp_path / ".px/skill-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["counts"]["px-standard"] = 1
    index_path.write_text(json.dumps(index), encoding="utf-8")
    studio = SkillStudio(tmp_path)
    draft_source = source(tmp_path, "draft")
    token = studio.admit_source(draft_source, approved_by="human:owner")
    studio.stage_draft(package(), draft_source, source_token=token)
    studio.validate(package())
    studio.admit(package(), approved=True, approver="human:owner")
    with pytest.raises(ValueError, match="denominator drift"):
        studio.promote(package(), approved=True)
    assert not (tmp_path / ".px/skills/demo").exists()
