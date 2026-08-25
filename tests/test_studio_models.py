from __future__ import annotations

import json

import pytest
import runtime.studio_models as studio_models

from runtime.studio_models import (
    AgentSpec,
    CapabilityBinding,
    EffectGrant,
    LifecycleDimensions,
    MAX_REVISION_TREE_ENTRIES,
    MAX_REVISION_TREE_FILE_BYTES,
    SkillPackage,
    STUDIO_VERSION_CONFLICT_REASONS,
    StudioVersionConflict,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    allocate_studio_version,
    revalidate_studio_version_allocation,
    studio_revision_root,
    valid_canonical_utc,
    write_versioned_record,
)
from runtime.studio_filesystem import publish_directory_no_replace


def test_lifecycle_dimensions_require_evidence_and_do_not_conflate_registration_with_runtime() -> (
    None
):
    with pytest.raises(ValueError, match="lacks evidence"):
        LifecycleDimensions(installed=True)
    state = LifecycleDimensions(
        packaged=True,
        admitted=True,
        evidence={"packaged": "sha256:x", "admitted": "receipt:y"},
    )
    assert state.operational is False
    assert state.process_ready is False


def test_binding_and_effect_grant_require_scope_policy_and_evidence() -> None:
    grant = EffectGrant(
        "grant:read",
        "agent:one",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:one",),
    )
    binding = CapabilityBinding(
        "binding:one",
        "agent",
        "agent:one",
        "capability:search",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:two",),
    )
    assert binding.state == "admitted"


def test_workflow_definition_rejects_port_mismatch_and_cycles() -> None:
    one = WorkflowNode(
        "node:one",
        "binding:one",
        (WorkflowPort("start", "json"),),
        (WorkflowPort("out", "json"),),
        ("grant:one",),
        "fail-closed",
        10,
    )
    two = WorkflowNode(
        "node:two",
        "binding:two",
        (WorkflowPort("in", "json"),),
        (WorkflowPort("out", "json"),),
        ("grant:two",),
        "fail-closed",
        10,
    )
    valid = WorkflowDefinition(
        "workflow:demo",
        "1.0.0",
        "owner",
        (one, two),
        (WorkflowEdge("node:one", "out", "node:two", "in"),),
    )
    assert len(valid.nodes) == 2
    with pytest.raises(ValueError, match="cycle"):
        WorkflowDefinition(
            "workflow:cycle",
            "1.0.0",
            "owner",
            (one, two),
            (
                WorkflowEdge("node:one", "out", "node:two", "in"),
                WorkflowEdge("node:two", "out", "node:one", "start"),
            ),
        )


def test_workflow_node_config_is_closed_and_validation_requires_checks() -> None:
    common = (
        "node:typed",
        "binding:typed",
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("value", "integer"),),
        ("grant:typed",),
        "fail-closed",
        5,
    )
    with pytest.raises(ValueError, match="must be empty"):
        WorkflowNode(*common, kind="task", config={"decorative": True})
    with pytest.raises(ValueError, match="checks array"):
        WorkflowNode(*common, kind="validation", config={})
    with pytest.raises(ValueError, match="fail closed"):
        WorkflowNode(
            *common[:5],
            "continue",
            common[6],
            kind="validation",
            config={
                "checks": [
                    {
                        "id": "check:value",
                        "source": "outputs",
                        "port": "value",
                        "operator": "exists",
                    }
                ]
            },
        )


def test_agent_and_skill_revisions_are_immutable(tmp_path) -> None:
    agent = AgentSpec(
        "agent:demo",
        "1.0.0",
        "project:demo",
        "owner",
        "harness:px",
        "a" * 64,
        ("binding:one",),
        ("grant:one",),
        ("identity", "sandbox"),
    )
    target = write_versioned_record(
        tmp_path, "agents", agent.agent_id, agent.version, agent
    )
    assert (
        json.loads(target.read_text(encoding="utf-8"))["record"]["lifecycle"] == "draft"
    )
    assert (
        write_versioned_record(tmp_path, "agents", agent.agent_id, agent.version, agent)
        == target
    )
    skill = SkillPackage(
        "skill:demo",
        "1.0.0",
        "owner",
        ("when demo",),
        ("not otherwise",),
        ("read",),
        ("read",),
        ("SKILL.md",),
        ("contracts/manifest.json",),
        ("tests/validation.json",),
        {"source": "local", "license": "Apache-2.0"},
    )
    assert skill.lifecycle == "draft"


def test_version_allocation_uses_physical_occupancy_and_skips_stable_revisions(tmp_path) -> None:
    identity = "agent:versioned"
    source = AgentSpec(
        identity,
        "2.4.8-rc.1",
        "project:demo",
        "owner",
        "harness:px",
        "a" * 64,
        ("binding:one",),
        ("grant:one",),
        ("identity",),
    )
    source_record = write_versioned_record(
        tmp_path, "agent", identity, source.version, source
    )
    revision_root = studio_revision_root(tmp_path, "agent", identity)
    (revision_root / " 2.4.8").write_text("noncanonical control", encoding="utf-8")
    (revision_root / "2.4.7-RC.1").write_text(
        "noncanonical control", encoding="utf-8"
    )
    assert "2.4.7-rc.1" not in studio_models._occupied_versions(
        tmp_path, "agent", identity
    )
    first = allocate_studio_version(tmp_path, "agent", identity, "2.4.8-rc.1")
    assert first["candidate_version"] == "2.4.8"
    assert first["source_scope"] == "studio-physical"
    assert first["source_revision_sha256"] == __import__("hashlib").sha256(
        source_record.read_bytes()
    ).hexdigest()
    assert len(first["source_content_sha256"]) == 64
    run_status = source_record.parent / "runs" / "run-one" / "status.json"
    run_status.parent.mkdir(parents=True)
    run_status.write_text('{"state":"running"}\n', encoding="utf-8")
    while_running = allocate_studio_version(
        tmp_path, "agent", identity, "2.4.8-rc.1"
    )
    run_status.write_text('{"state":"succeeded"}\n', encoding="utf-8")
    after_completion = allocate_studio_version(
        tmp_path, "agent", identity, "2.4.8-rc.1"
    )
    assert while_running["source_content_sha256"] == first["source_content_sha256"]
    assert after_completion["source_content_sha256"] == first["source_content_sha256"]
    (revision_root / "2.4.8").write_text("physically occupied", encoding="utf-8")
    (revision_root / "2.4.9").mkdir()
    skipped = allocate_studio_version(tmp_path, "agent", identity, "2.4.8-rc.1")
    assert skipped["candidate_version"] == "2.4.10"
    assert skipped["occupied_versions_sha256"] != first["occupied_versions_sha256"]


def test_version_allocation_requires_exact_source_and_rejects_link_occupancy(tmp_path) -> None:
    with pytest.raises(StudioVersionConflict) as missing:
        allocate_studio_version(tmp_path, "workflow", "workflow:missing", "1.0.0")
    assert missing.value.reason == "source-revision-missing"

    source = AgentSpec(
        "agent:links", "1.0.0", "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(tmp_path, "agent", source.agent_id, source.version, source)
    revisions = studio_revision_root(tmp_path, "agent", source.agent_id)
    outside = tmp_path / "missing-outside-revision"
    try:
        (revisions / "not-a-version").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(StudioVersionConflict) as refused:
        allocate_studio_version(tmp_path, "agent", source.agent_id, source.version)
    assert refused.value.reason == "source-revision-invalid"


def test_identity_absence_rejects_dangling_revision_root_link(tmp_path) -> None:
    revisions = studio_revision_root(tmp_path, "agent", "agent:dangling-root")
    revisions.parent.mkdir(parents=True, exist_ok=True)
    try:
        revisions.symlink_to(
            tmp_path / "missing-revision-root", target_is_directory=True
        )
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(StudioVersionConflict) as absence:
        studio_models.studio_identity_absence(
            tmp_path, "agent", "agent:dangling-root"
        )
    assert absence.value.reason == "source-revision-invalid"

    with pytest.raises(StudioVersionConflict) as initial:
        studio_models.require_initial_studio_identity(
            tmp_path, "agent", "agent:dangling-root", "1.0.0"
        )
    assert initial.value.reason == "source-revision-invalid"


def test_version_occupancy_race_is_a_typed_conflict(tmp_path, monkeypatch) -> None:
    source = AgentSpec(
        "agent:occupancy-race", "1.0.0", "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(
        tmp_path, "agent", source.agent_id, source.version, source
    )
    revisions = studio_revision_root(tmp_path, "agent", source.agent_id)
    (revisions / "1.0.1").write_text("racing entry", encoding="utf-8")
    original = studio_models._is_link_or_reparse

    def fail_closed_on_candidate(path):
        if path.name == "1.0.1":
            raise FileNotFoundError("entry changed during occupancy inspection")
        return original(path)

    monkeypatch.setattr(studio_models, "_is_link_or_reparse", fail_closed_on_candidate)
    with pytest.raises(StudioVersionConflict) as refused:
        allocate_studio_version(tmp_path, "agent", source.agent_id, source.version)
    assert refused.value.reason == "source-revision-invalid"


def test_revision_tree_enforces_file_and_streamed_entry_bounds(tmp_path) -> None:
    source = AgentSpec(
        "agent:bounded-tree", "1.0.0", "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    record_path = write_versioned_record(
        tmp_path, "agent", source.agent_id, source.version, source
    )
    (record_path.parent / "oversized.bin").write_bytes(
        b"x" * (MAX_REVISION_TREE_FILE_BYTES + 1)
    )
    with pytest.raises(StudioVersionConflict) as oversized:
        allocate_studio_version(tmp_path, "agent", source.agent_id, source.version)
    assert oversized.value.reason == "source-content-bound-exceeded"
    (record_path.parent / "oversized.bin").unlink()
    for index in range(MAX_REVISION_TREE_ENTRIES):
        (record_path.parent / f"entry-{index:04d}").mkdir()
    with pytest.raises(StudioVersionConflict) as entries:
        allocate_studio_version(tmp_path, "agent", source.agent_id, source.version)
    assert entries.value.reason == "source-content-bound-exceeded"


def test_version_occupancy_enumeration_stops_at_its_bound(tmp_path, monkeypatch) -> None:
    source = AgentSpec(
        "agent:bounded-occupancy", "1.0.0", "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(tmp_path, "agent", source.agent_id, source.version, source)
    revisions = studio_revision_root(tmp_path, "agent", source.agent_id)
    (revisions / "1.0.1").mkdir()
    (revisions / "1.0.2").mkdir()
    monkeypatch.setattr(studio_models, "MAX_VERSION_OCCUPANCY_ENTRIES", 2)
    with pytest.raises(StudioVersionConflict) as refused:
        allocate_studio_version(tmp_path, "agent", source.agent_id, source.version)
    assert refused.value.reason == "occupancy-bound-exceeded"


def test_directory_publication_never_replaces_an_occupied_target(tmp_path) -> None:
    source = tmp_path / "prepared"
    destination = tmp_path / "occupied"
    source.mkdir()
    destination.mkdir()
    (source / "record.json").write_text("source", encoding="utf-8")
    with pytest.raises(OSError):
        publish_directory_no_replace(source, destination)
    assert source.is_dir() and destination.is_dir()
    assert (source / "record.json").read_text(encoding="utf-8") == "source"


@pytest.mark.parametrize(
    "version",
    (
        "01.0.0", "1.00.0", "1.0.00", "1.0", "1.0.0-01",
        "1.0.0--candidate", "1.0.0-candidate-", "1.0.0-a..b",
        "1.0.0-a.", f"1.0.0-{'a' * 65}", "2147483648.0.0",
    ),
)
def test_every_studio_model_uses_the_bounded_canonical_version_parser(version) -> None:
    with pytest.raises(ValueError, match="version"):
        AgentSpec(
            "agent:invalid-version", version, "project:demo", "owner", "harness:px",
            "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
        )
    with pytest.raises(ValueError, match="version"):
        WorkflowDefinition("workflow:invalid-version", version, "owner", (), ())
    with pytest.raises(ValueError, match="version"):
        SkillPackage(
            "skill:invalid-version", version, "owner", (), (), (), (), (), (), (), {}
        )
    with pytest.raises(ValueError, match="version"):
        CapabilityBinding(
            "binding:invalid-version", "agent", "agent:invalid-version",
            "capability:demo", version, ("grant:demo",), None,
            "non-billable", "deny", "admitted", ("receipt:test",),
        )


def test_studio_identities_are_canonicalized_in_frozen_records() -> None:
    grant = EffectGrant(
        " Grant:Read ",
        " Agent:One ",
        ("read",),
        ("workspace:demo",),
        "owner",
        ("receipt:one",),
    )
    assert grant.grant_id == "grant:read" and grant.subject_id == "agent:one"
    agent = AgentSpec(
        " Agent:Demo ",
        " 1.0.0 ",
        " Project:Demo ",
        "owner",
        " Harness:PX ",
        "a" * 64,
        ("binding:one",),
        ("grant:one",),
        ("identity",),
    )
    assert (
        agent.agent_id == "agent:demo"
        and agent.project_id == "project:demo"
        and agent.harness_id == "harness:px"
    )


def test_every_studio_model_canonicalizes_version_case_and_whitespace() -> None:
    version = " 2.4.8-RC.1 "
    agent = AgentSpec(
        "agent:normalized-version", version, "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    node = WorkflowNode(
        "node:normalized-version", "binding:one",
        (WorkflowPort("input", "json"),),
        (WorkflowPort("output", "json"),),
        ("grant:one",),
        "fail-closed", 1,
    )
    workflow = WorkflowDefinition(
        "workflow:normalized-version", version, "owner", (node,), ()
    )
    skill = SkillPackage(
        "skill:normalized-version", version, "owner", ("matching task",),
        ("unrelated task",), ("read",), ("read",), ("SKILL.md",),
        ("contracts/input.json",), ("tests/contract.json",), {"source": "test"},
    )
    binding = CapabilityBinding(
        "binding:normalized-version", "agent", "agent:normalized-version",
        "capability:demo", version, ("grant:demo",), None,
        "non-billable", "deny", "admitted", ("receipt:test",),
    )
    assert {agent.version, workflow.version, skill.version, binding.capability_version} == {
        "2.4.8-rc.1"
    }
    bounded = AgentSpec(
        "agent:max-version-suffix", f"1.0.0-{'a' * 64}", "project:demo", "owner",
        "harness:px", "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    assert bounded.version == f"1.0.0-{'a' * 64}"


def test_allocation_revalidation_requires_a_real_canonical_utc_observation(tmp_path) -> None:
    source = AgentSpec(
        "agent:allocation-time", "1.0.0", "project:demo", "owner", "harness:px",
        "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(tmp_path, "agent", source.agent_id, source.version, source)
    allocation = allocate_studio_version(
        tmp_path, "agent", source.agent_id, source.version
    )
    revalidate_studio_version_allocation(
        tmp_path,
        "agent",
        source.agent_id,
        allocation["candidate_version"],
        {**allocation, "observed_utc": "2026-08-16T00:00:00Z"},
    )
    for invalid in (
        "not-a-time", "2026-02-31T00:00:00Z", "2026-08-16T00:00:00+00:00",
        "2026-08-16T00:00:00.12Z", "2026-08-16T00:00:00.1234Z",
    ):
        malformed = {**allocation, "observed_utc": invalid}
        with pytest.raises(StudioVersionConflict) as refused:
            revalidate_studio_version_allocation(
                tmp_path, "agent", source.agent_id, allocation["candidate_version"], malformed
            )
        assert refused.value.reason == "allocation-binding-mismatch"


def test_canonical_utc_validator_has_strict_calendar_and_precision_parity() -> None:
    assert valid_canonical_utc("2026-08-16T00:00:00Z")
    assert valid_canonical_utc("2026-08-16T00:00:00.123Z")
    assert not valid_canonical_utc("0000-01-01T00:00:00Z")
    assert not valid_canonical_utc("2026-02-31T00:00:00Z")
    assert not valid_canonical_utc("2026-08-16T00:00:00.12Z")


@pytest.mark.parametrize(
    "hash_field",
    ("source_revision_sha256", "source_content_sha256", "occupied_versions_sha256"),
)
@pytest.mark.parametrize("tampered_hash", ("f" * 63, "F" * 64, 7, None))
def test_allocation_revalidation_rejects_every_invalid_hash_field(
    tmp_path, hash_field, tampered_hash
) -> None:
    source = AgentSpec(
        "agent:allocation-occupancy", "1.0.0", "project:demo", "owner",
        "harness:px", "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(tmp_path, "agent", source.agent_id, source.version, source)
    allocation = allocate_studio_version(
        tmp_path, "agent", source.agent_id, source.version
    )
    with pytest.raises(StudioVersionConflict) as refused:
        revalidate_studio_version_allocation(
            tmp_path,
            "agent",
            source.agent_id,
            allocation["candidate_version"],
            {**allocation, hash_field: tampered_hash},
        )
    assert refused.value.reason == "allocation-binding-mismatch"


def test_allocation_revalidation_exactly_binds_canonical_source_version(tmp_path) -> None:
    source = AgentSpec(
        "agent:allocation-source-version", "1.0.0", "project:demo", "owner",
        "harness:px", "a" * 64, ("binding:one",), ("grant:one",), ("identity",),
    )
    write_versioned_record(tmp_path, "agent", source.agent_id, source.version, source)
    allocation = allocate_studio_version(
        tmp_path, "agent", source.agent_id, source.version
    )
    for tampered in (" 1.0.0 ", "1.0.0-RC.1"):
        with pytest.raises(StudioVersionConflict) as refused:
            revalidate_studio_version_allocation(
                tmp_path,
                "agent",
                source.agent_id,
                allocation["candidate_version"],
                {**allocation, "source_version": tampered},
            )
        assert refused.value.reason == "allocation-binding-mismatch"


def test_studio_version_conflict_reason_owner_is_the_exported_closed_set() -> None:
    assert StudioVersionConflict.REASONS is STUDIO_VERSION_CONFLICT_REASONS
    assert "allocation-source-invalid" in STUDIO_VERSION_CONFLICT_REASONS


def test_versioned_record_rejects_intermediate_symlink_escape(tmp_path) -> None:
    outside = tmp_path / "physical-outside"
    outside.mkdir()
    try:
        (tmp_path / ".engineering-bootstrap").symlink_to(
            outside, target_is_directory=True
        )
    except OSError:
        pytest.skip("symlink creation is unavailable")
    agent = AgentSpec(
        "agent:demo",
        "1.0.0",
        "project:demo",
        "owner",
        "harness:px",
        "a" * 64,
        ("binding:one",),
        ("grant:one",),
        ("identity",),
    )
    with pytest.raises(ValueError, match="link|reparse"):
        write_versioned_record(tmp_path, "agents", agent.agent_id, agent.version, agent)
    assert not any(outside.rglob("record.json"))
