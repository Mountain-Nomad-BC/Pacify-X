from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import pytest

from runtime.studio_api import (
    _skill_promotion_receipt_path,
    admit_skill_source,
    create_draft,
    main,
    studio_operation,
)
from runtime.skill_studio import _component
from runtime.studio_authority import (
    StudioAuthorityStore,
    studio_authority_locator_environment,
)
from runtime.studio_models import StudioVersionConflict
from tests.studio_approval_testkit import approval_proof, authorized_payload


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
ALLOCATION_FIELDS = {
    "schema_version", "kind", "identity", "source_version", "source_scope",
    "source_revision_sha256", "source_content_sha256", "candidate_version",
    "occupied_versions_sha256", "observed_utc",
}


def _authorized(root, kind, operation, payload):
    return authorized_payload(root, kind, operation, payload)


def _editor_tree_sha256(root: Path) -> tuple[str, int]:
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


def test_skill_promotion_api_returns_the_physical_component_receipt_path(tmp_path) -> None:
    skill_id = "skill:rollback-path"
    expected = (
        tmp_path
        / ".engineering-bootstrap/studios/skills"
        / _component(skill_id)
        / "revisions/1.2.3/promotion-receipt.json"
    )
    assert _skill_promotion_receipt_path(tmp_path, skill_id, "1.2.3") == expected


def test_worker_authority_environment_forwards_only_key_locators() -> None:
    key_root = (ROOT / ".test-host-keys").resolve(strict=False)
    assert studio_authority_locator_environment(
        {
            "PX_STUDIO_KEY_ROOT": str(key_root),
            "XDG_STATE_HOME": "/host/state",
            "LOCALAPPDATA": "C:/host/state",
            "PX_STUDIO_APPROVAL_BROKER_SECRET": "must-not-cross",
            "OPENAI_API_KEY": "must-not-cross",
        }
    ) == {
        "PX_STUDIO_KEY_ROOT": str(key_root),
        "XDG_STATE_HOME": "/host/state",
        "LOCALAPPDATA": "C:/host/state",
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX HOME fallback semantics")
def test_worker_authority_environment_freezes_parent_home_key_root(tmp_path) -> None:
    home = tmp_path / "custom-home"
    locators = studio_authority_locator_environment({"HOME": str(home)})
    assert locators == {
        "PX_STUDIO_KEY_ROOT": str(
            (home / ".local/state/pacify-x/authority-keys").resolve()
        )
    }


def test_agent_and_workflow_drafts_are_real_immutable_revisions(tmp_path) -> None:
    agent = {
        "agent_id": "agent:ui-demo",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Stay bounded.\n",
        "capability_binding_ids": ["binding:demo"],
        "effect_grant_ids": ["grant:demo"],
        "required_tests": ["identity"],
    }
    created = create_draft(tmp_path, "agent", agent)
    assert created["created"] is True and created["admission_state"] == "unadmitted"
    assert created["authority_state"] == "defined"
    assert (tmp_path / created["authority_definition_path"]).is_file()
    assert created["builder_graph_state"] == "content-bound"
    assert (tmp_path / created["builder_graph_path"]).is_file()
    assert (tmp_path / created["editor_layout_path"]).is_file()
    assert (tmp_path / created["builder_compiler_receipt_path"]).is_file()
    workflow = {
        "workflow_id": "workflow:ui-demo",
        "version": "1.0.0",
        "owner": "human:owner",
        "nodes": [
            {
                "node_id": "step:one",
                "executor_binding_id": "binding:demo",
                "inputs": [{"name": "request", "data_type": "string"}],
                "outputs": [{"name": "result", "data_type": "string"}],
                "effect_grant_ids": ["grant:demo"],
                "failure_policy": "fail_closed",
                "timeout_seconds": 30,
            }
        ],
        "edges": [],
        "editor_layout": {"step:one": {"x": 0, "y": 240}},
    }
    saved = create_draft(tmp_path, "workflow", workflow)
    assert (
        saved["definition_state"] == "saved"
        and saved["runnable_state"] == "unvalidated"
    )
    assert saved["created"] is True and saved["authority_state"] == "defined"
    assert (tmp_path / saved["authority_definition_path"]).is_file()
    assert saved["schema_version"] == "px.workflow-revision-receipt/1.2"
    assert saved["editor_layout_state"] == "content-bound"
    assert (tmp_path / saved["editor_layout_path"]).is_file()
    record = json.loads((tmp_path / saved["path"]).read_text(encoding="utf-8"))
    assert record["record"]["nodes"][0]["node_id"] == "step:one"


def test_identity_absence_uses_physical_revisions_and_initial_create_cannot_skip_lineage(tmp_path) -> None:
    identity = "agent:physical-absence"
    before = studio_operation(tmp_path, "agent", "identity-absence", {"identity": identity})
    assert before == {
        "schema_version": "px.studio-identity-absence/1.0",
        "kind": "agent",
        "identity": identity,
        "absent": True,
        "observed_utc": before["observed_utc"],
    }
    value = {
        "agent_id": identity, "version": "1.0.0", "project_id": "project:demo",
        "owner": "human:owner", "harness_id": "harness:px", "instructions": "Stay bounded.\n",
        "capability_binding_ids": ["binding:demo"], "effect_grant_ids": ["grant:demo"], "required_tests": ["identity"],
    }
    created = create_draft(tmp_path, "agent", value)
    assert created["created"] is True
    after = studio_operation(tmp_path, "agent", "identity-absence", {"identity": identity})
    assert after["absent"] is False
    replay = create_draft(tmp_path, "agent", value)
    assert replay["created"] is False and replay["idempotent_replay"] is True
    with pytest.raises(StudioVersionConflict, match=r"^studio-version-conflict:initial-version-invalid"):
        create_draft(tmp_path, "agent", {**value, "version": "1.0.1"})


def test_next_version_is_read_only_prerelease_aware_and_create_revalidates_it(tmp_path) -> None:
    value = {
        "agent_id": "agent:allocated",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Bounded.\n",
        "capability_binding_ids": ["binding:demo"],
        "effect_grant_ids": ["grant:demo"],
        "required_tests": ["identity"],
    }
    initial = studio_operation(
        tmp_path,
        "agent",
        "create",
        _authorized(tmp_path, "agent", "create", value),
    )
    allocation = studio_operation(
        tmp_path,
        "agent",
        "next-version",
        {"identity": value["agent_id"], "source_version": value["version"]},
    )
    allocated = {**value, "version": "1.0.1", "version_allocation": allocation}
    assert set(allocation) == ALLOCATION_FIELDS
    source_record = (tmp_path / str(initial["builder_graph_path"])).with_name("record.json")
    assert allocation["source_scope"] == "studio-physical"
    assert allocation["source_revision_sha256"] == hashlib.sha256(source_record.read_bytes()).hexdigest()
    assert len(allocation["source_content_sha256"]) == 64
    created = studio_operation(
        tmp_path,
        "agent",
        "create",
        _authorized(tmp_path, "agent", "create", allocated),
    )
    original = (tmp_path / str(created["builder_graph_path"])).with_name("record.json").read_bytes()
    replay = studio_operation(
        tmp_path,
        "agent",
        "create",
        _authorized(tmp_path, "agent", "create", allocated),
    )
    assert replay["created"] is False and replay["idempotent_replay"] is True
    replay_without_stale_allocation = studio_operation(
        tmp_path,
        "agent",
        "create",
        _authorized(
            tmp_path,
            "agent",
            "create",
            {key: item for key, item in allocated.items() if key != "version_allocation"},
        ),
    )
    assert replay_without_stale_allocation["created"] is False
    assert replay_without_stale_allocation["idempotent_replay"] is True
    assert (tmp_path / str(created["builder_graph_path"])).with_name("record.json").read_bytes() == original


def test_workflow_next_version_authenticates_physical_predecessor_and_revalidates_conflict(
    tmp_path,
) -> None:
    value = _workflow_layout_value()
    initial = studio_operation(
        tmp_path,
        "workflow",
        "create",
        _authorized(tmp_path, "workflow", "create", value),
    )
    allocation = studio_operation(
        tmp_path,
        "workflow",
        "next-version",
        {"identity": value["workflow_id"], "source_version": value["version"]},
    )
    source_record = tmp_path / str(initial["path"])
    assert set(allocation) == ALLOCATION_FIELDS
    assert allocation["kind"] == "workflow"
    assert allocation["identity"] == value["workflow_id"]
    assert allocation["source_scope"] == "studio-physical"
    assert allocation["candidate_version"] == "1.0.1"
    assert allocation["source_revision_sha256"] == hashlib.sha256(
        source_record.read_bytes()
    ).hexdigest()

    candidate = {
        **value,
        "version": allocation["candidate_version"],
        "version_allocation": allocation,
    }
    created = studio_operation(
        tmp_path,
        "workflow",
        "create",
        _authorized(tmp_path, "workflow", "create", candidate),
    )
    created_record = tmp_path / str(created["path"])
    preserved = created_record.read_bytes()
    replay = studio_operation(
        tmp_path,
        "workflow",
        "create",
        _authorized(tmp_path, "workflow", "create", candidate),
    )
    assert replay["created"] is False and replay["idempotent_replay"] is True
    replay_without_stale_allocation = studio_operation(
        tmp_path,
        "workflow",
        "create",
        _authorized(
            tmp_path,
            "workflow",
            "create",
            {key: item for key, item in candidate.items() if key != "version_allocation"},
        ),
    )
    assert replay_without_stale_allocation["created"] is False
    assert replay_without_stale_allocation["idempotent_replay"] is True
    assert created_record.read_bytes() == preserved


def test_allocation_revalidation_detects_source_tree_change_before_publication(tmp_path) -> None:
    value = {
        "agent_id": "agent:source-change",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Original.\n",
        "capability_binding_ids": ["binding:demo"],
        "effect_grant_ids": ["grant:demo"],
        "required_tests": ["identity"],
    }
    created = studio_operation(
        tmp_path, "agent", "create", _authorized(tmp_path, "agent", "create", value)
    )
    allocation = studio_operation(
        tmp_path,
        "agent",
        "next-version",
        {"identity": value["agent_id"], "source_version": "1.0.0"},
    )
    source_instructions = (
        tmp_path / str(created["builder_graph_path"])
    ).with_name("instructions.md")
    source_instructions.write_text("Changed after allocation.\n", encoding="utf-8")
    candidate = {**value, "version": "1.0.1", "version_allocation": allocation}
    with pytest.raises(StudioVersionConflict, match=r"^studio-version-conflict:allocation-stale"):
        studio_operation(
            tmp_path,
            "agent",
            "create",
            _authorized(tmp_path, "agent", "create", candidate),
        )
    assert not next(
        (tmp_path / ".engineering-bootstrap/studios/agents").glob(
            "*/revisions/1.0.1"
        ),
        None,
    )


def test_main_serializes_version_conflict_as_exact_compact_json(tmp_path, capsys) -> None:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"identity": "agent:missing", "source_version": "1.0.0"}
        ).encode("utf-8")
    ).decode("ascii")
    result = main(
        [
            "--root", str(tmp_path),
            "--kind", "agent",
            "--operation", "next-version",
            "--payload-base64", payload,
        ]
    )
    captured = capsys.readouterr()
    assert result == 2 and captured.out == ""
    assert captured.err == (
        '{"code":"STUDIO_VERSION_CONFLICT","reason":"source-revision-missing",'
        '"schema_version":"px.studio-operation-error/1.0"}\n'
    )


@pytest.mark.parametrize(
    ("payload_value", "reason"),
    (
        ({"identity": "agent:invalid", "source_version": "01.0.0"}, "allocation-source-invalid"),
        ({"identity": "agent:invalid", "source_version": "1.0.0", "extra": True}, "allocation-envelope-invalid"),
        (
            {
                "identity": "skill:invalid",
                "source_version": "1.0.0",
                "source_scope": "",
                "source_revision_sha256": "a" * 64,
                "source_content_sha256": "b" * 64,
            },
            "external-source-invalid",
        ),
    ),
)
def test_main_structures_invalid_next_version_requests(
    tmp_path, capsys, payload_value, reason
) -> None:
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_value).encode("utf-8")
    ).decode("ascii")
    result = main(
        [
            "--root", str(tmp_path), "--kind", "agent", "--operation",
            "next-version", "--payload-base64", payload,
        ]
    )
    captured = capsys.readouterr()
    assert result == 2 and captured.out == ""
    assert json.loads(captured.err) == {
        "schema_version": "px.studio-operation-error/1.0",
        "code": "STUDIO_VERSION_CONFLICT",
        "reason": reason,
    }


def test_skill_source_admission_binds_host_materialization_and_rejects_tamper(
    tmp_path,
) -> None:
    source = tmp_path / "materialized-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Bound skill\n", encoding="utf-8")
    (source / "capability.json").write_text("{}\n", encoding="utf-8")
    (source / "skill.yaml").write_text("id: bound-skill\n", encoding="utf-8")
    tree_sha256, file_count = _editor_tree_sha256(source)
    payload = {
        "source_directory": str(source),
        "expected_tree_sha256": tree_sha256,
        "expected_file_count": file_count,
    }
    receipt = studio_operation(
        tmp_path,
        "skill",
        "admit-source",
        _authorized(tmp_path, "skill", "admit-source", payload),
    )
    assert set(receipt) == {
        "schema_version", "source_token", "source_directory",
        "source_tree_sha256", "file_count",
    }
    assert receipt["source_tree_sha256"] == tree_sha256
    assert receipt["file_count"] == file_count

    (source / "SKILL.md").write_text("# Tampered after selection\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="materialization attestation"):
        studio_operation(
            tmp_path,
            "skill",
            "admit-source",
            _authorized(tmp_path, "skill", "admit-source", payload),
        )


def test_skill_source_admission_returns_the_path_from_the_admission_receipt(
    tmp_path, monkeypatch
) -> None:
    admitted_path = tmp_path / "physical-at-admission"

    class FakeStudio:
        def __init__(self, _root):
            pass

        def admit_source(self, _source, **_kwargs):
            return {
                "source_token": "source-token",
                "source_directory": str(admitted_path),
                "source_tree_sha256": "a" * 64,
                "file_count": 3,
            }

    monkeypatch.setattr("runtime.studio_api.SkillStudio", FakeStudio)
    receipt = admit_skill_source(
        tmp_path,
        {
            "source_directory": str(tmp_path / "caller-path-now-missing"),
            "expected_tree_sha256": "a" * 64,
            "expected_file_count": 3,
            "approved": True,
            "approved_by": "human:test",
        },
    )
    assert receipt["source_directory"] == str(admitted_path)


def _workflow_layout_value() -> dict[str, object]:
    return {
        "workflow_id": "workflow:layout-contract",
        "version": "1.0.0",
        "owner": "human:owner",
        "nodes": [
            {
                "node_id": "node:first",
                "executor_binding_id": "binding:first",
                "inputs": [{"name": "value", "data_type": "string"}],
                "outputs": [{"name": "value", "data_type": "string"}],
                "effect_grant_ids": ["grant:first"],
                "failure_policy": "fail-closed",
                "timeout_seconds": 5,
            },
            {
                "node_id": "node:second",
                "executor_binding_id": "binding:second",
                "inputs": [{"name": "value", "data_type": "string"}],
                "outputs": [{"name": "value", "data_type": "string"}],
                "effect_grant_ids": ["grant:second"],
                "failure_policy": "fail-closed",
                "timeout_seconds": 5,
            },
        ],
        "edges": [
            {
                "source_node": "node:first",
                "source_port": "value",
                "target_node": "node:second",
                "target_port": "value",
                "condition": "always",
            }
        ],
        "editor_layout": {
            "node:first": {"x": 0, "y": -125.5},
            "node:second": {"x": 420.25, "y": 0},
        },
    }


def test_workflow_layout_is_content_bound_and_exactly_idempotent(tmp_path) -> None:
    value = _workflow_layout_value()
    created = create_draft(tmp_path, "workflow", value)
    record_path = tmp_path / str(created["path"])
    layout_path = tmp_path / str(created["editor_layout_path"])
    receipt_path = record_path.with_name("creation-receipt.json")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert created["schema_version"] == "px.workflow-revision-receipt/1.2"
    assert created["revision_sha256"] == hashlib.sha256(record_path.read_bytes()).hexdigest()
    assert layout["schema_version"] == "px.workflow-editor-layout/1.0"
    assert layout["revision_sha256"] == created["revision_sha256"]
    assert layout["layout"] == value["editor_layout"]
    assert receipt["editor_layout_sha256"] == layout["layout_sha256"]

    replay = create_draft(tmp_path, "workflow", value)
    assert replay["created"] is False
    assert replay["idempotent_replay"] is True
    assert replay["revision_sha256"] == created["revision_sha256"]

    moved = {
        **value,
        "editor_layout": {
            **value["editor_layout"],
            "node:first": {"x": 1, "y": -125.5},
        },
    }
    with pytest.raises(FileExistsError, match="immutable workflow revision"):
        create_draft(tmp_path, "workflow", moved)
    assert json.loads(layout_path.read_text(encoding="utf-8")) == layout


@pytest.mark.parametrize(
    "layout",
    [
        {"node:first": {"x": 0, "y": 0}},
        {
            "node:first": {"x": 0, "y": 0},
            "node:second": {"x": 20_001, "y": 0},
        },
        {
            "node:first": {"x": True, "y": 0},
            "node:second": {"x": 1, "y": 0},
        },
        {
            "node:first": {"x": float("nan"), "y": 0},
            "node:second": {"x": 1, "y": 0},
        },
    ],
)
def test_workflow_layout_rejects_incomplete_or_unsafe_geometry(
    tmp_path, layout
) -> None:
    with pytest.raises(ValueError, match="workflow editor_layout"):
        create_draft(
            tmp_path,
            "workflow",
            {**_workflow_layout_value(), "editor_layout": layout},
        )


def test_agent_draft_rejects_builder_graph_that_differs_from_direct_spec(
    tmp_path,
) -> None:
    value = {
        "agent_id": "agent:graph-mismatch",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Stay bounded.\n",
        "capability_binding_ids": ["binding:demo"],
        "effect_grant_ids": ["grant:demo"],
        "required_tests": ["identity"],
    }
    created = create_draft(tmp_path, "agent", value)
    graph_envelope = json.loads(
        (tmp_path / created["builder_graph_path"]).read_text(encoding="utf-8")
    )
    graph = graph_envelope["record"]
    candidate = next(
        node for node in graph["nodes"] if node["kind"] == "candidate"
    )
    candidate["config"]["lifecycle"] = "candidate"
    with pytest.raises(ValueError, match="does not compile"):
        create_draft(tmp_path, "agent", {**value, "builder_graph": graph})


def test_standard_agent_studio_rejects_enterprise_namespace_bleed(tmp_path) -> None:
    value = {
        "agent_id": "agent:domain-test",
        "version": "1.0.0",
        "project_id": "project:test",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Stay bounded.\n",
        "capability_binding_ids": ["binding:domain-test"],
        "effect_grant_ids": ["grant:domain-test"],
        "required_tests": ["identity"],
        "builder_domain": "px-standard",
        "bindings": [
            {
                "binding_id": "binding:domain-test",
                "subject_kind": "agent",
                "subject_id": "agent:domain-test",
                "capability_id": "enterprise:restricted-worker",
                "capability_version": "1.0.0",
                "effect_grant_ids": ["grant:domain-test"],
                "credential_namespace": None,
                "cost_policy": "non-billable",
                "egress_policy": "deny",
                "state": "candidate",
                "evidence_refs": ["receipt:human-approval"],
            }
        ],
    }
    with pytest.raises(PermissionError, match="enterprise-restricted"):
        create_draft(tmp_path, "agent", value)


def test_studio_mutations_reject_boolean_wrong_payload_and_replayed_approval(tmp_path) -> None:
    payload = {
        "agent_id": "agent:approval-demo", "version": "1.0.0", "project_id": "project:demo",
        "owner": "human:owner", "harness_id": "harness:px", "instructions": "Bounded.\n",
        "capability_binding_ids": ["binding:demo"], "effect_grant_ids": ["grant:demo"],
        "required_tests": ["identity"],
    }
    with pytest.raises(PermissionError, match="booleans are not authority"):
        studio_operation(tmp_path, "agent", "create", {**payload, "approved": True})
    token = approval_proof(tmp_path, "agent", "create", payload)
    with pytest.raises(PermissionError, match="exact payload"):
        studio_operation(tmp_path, "agent", "create", {**payload, "instructions": "Changed.\n", "approval_capability": token})
    # A mismatched attempt does not consume the exact capability.
    studio_operation(tmp_path, "agent", "create", {**payload, "approval_capability": token})
    with pytest.raises(PermissionError, match="replay denied"):
        studio_operation(tmp_path, "agent", "create", {**payload, "approval_capability": token})


def test_studio_receipts_are_project_move_portable_with_host_only_key(tmp_path, monkeypatch) -> None:
    host_keys = tmp_path.parent / f"{tmp_path.name}-host-keys"
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(host_keys))
    original = tmp_path / "original"
    original.mkdir()
    authority = StudioAuthorityStore(original)
    receipt = authority.sign_receipt({"schema_version": "px.test/1.0", "value": 7})
    moved = tmp_path / "moved"
    shutil.copytree(original, moved)
    assert StudioAuthorityStore(moved).verify_receipt(receipt)["value"] == 7
    assert not (original / ".engineering-bootstrap/studios/authority/.receipt-key").exists()


def test_legacy_project_key_is_backed_up_migrated_and_removed(tmp_path, monkeypatch) -> None:
    host_keys = tmp_path.parent / f"{tmp_path.name}-host-keys"
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(host_keys))
    project = tmp_path / "project"
    authority_root = project / ".engineering-bootstrap/studios/authority"
    authority_root.mkdir(parents=True)
    (authority_root / "project-identity.json").write_text(
        json.dumps({"schema_version": "px.studio-project-identity/1.0", "project_identity": "px-project-testlegacy"}),
        encoding="utf-8",
    )
    legacy = b"L" * 32
    (authority_root / ".receipt-key").write_bytes(legacy)
    authority = StudioAuthorityStore(project)
    assert authority.key_path.read_bytes() == legacy
    assert not (authority_root / ".receipt-key").exists()
    assert list((host_keys / "backups/px-project-testlegacy").glob("legacy-*.key"))
    migration = json.loads((authority_root / "key-migration-receipt.json").read_text(encoding="utf-8"))
    assert authority.verify_receipt(migration)["legacy_key_removed_from_project"] is True


def test_project_python_cannot_issue_studio_approval(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    host_keys = tmp_path / "host-keys"
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PX_STUDIO_KEY_ROOT": str(host_keys),
    }
    untrusted = subprocess.run(
        [
            sys.executable, "-m", "runtime.studio_approval", "--root", str(project),
            "--kind", "agent", "--operation", "create", "--approved-by",
            "human:caller-controlled", "--payload-stdin",
        ],
        cwd=ROOT, env=environment, input="{}", text=True,
        capture_output=True, timeout=10,
    )
    assert untrusted.returncode != 0
    assert "unrecognized arguments:" in untrusted.stderr
    assert "--approved-by" in untrusted.stderr

    direct = subprocess.run(
        [sys.executable, "-c", "from runtime.studio_api import issue_studio_operation_approval"],
        cwd=ROOT, env=environment, text=True, capture_output=True, timeout=10,
    )
    assert direct.returncode != 0
    assert "cannot import name 'issue_studio_operation_approval'" in direct.stderr

    described = subprocess.run(
        [sys.executable, "-m", "runtime.studio_approval", "--root", str(project), "--describe-verifier"],
        cwd=ROOT, env=environment, text=True, capture_output=True, timeout=10,
    )
    assert described.returncode == 0, described.stderr
    descriptor = json.loads(described.stdout)
    assert descriptor["record_path"].endswith(".json")
    assert "approval-verifiers" in descriptor["record_path"]


def test_studio_authority_rejects_relative_and_project_contained_key_roots(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", "relative-host-keys")
    with pytest.raises(ValueError, match="absolute path"):
        StudioAuthorityStore(project)
    with pytest.raises(ValueError, match="absolute path"):
        studio_authority_locator_environment({"PX_STUDIO_KEY_ROOT": "relative-host-keys"})
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(project / "..broker"))
    with pytest.raises(ValueError, match="outside the project"):
        StudioAuthorityStore(project)


def test_studio_host_signature_is_required_and_tampering_is_rejected(tmp_path) -> None:
    payload = {
        "agent_id": "agent:signature-test", "version": "1.0.0",
        "project_id": "project:test", "owner": "human:owner",
        "harness_id": "harness:px", "instructions": "Bounded.\n",
        "capability_binding_ids": ["binding:test"],
        "effect_grant_ids": ["grant:test"], "required_tests": ["identity"],
    }
    proof = approval_proof(tmp_path, "agent", "create", payload)
    proof["signature"] = "A" * len(str(proof["signature"]))
    with pytest.raises(PermissionError, match="signature is invalid"):
        studio_operation(tmp_path, "agent", "create", {**payload, "approval_capability": proof})


def test_agent_lifecycle_is_available_through_the_bounded_adapter(tmp_path) -> None:
    value = {
        "agent_id": "agent:api-demo",
        "version": "1.0.0",
        "project_id": "project:demo",
        "owner": "human:owner",
        "harness_id": "harness:px",
        "instructions": "Stay bounded.\n",
        "capability_binding_ids": ["binding:api-demo"],
        "effect_grant_ids": ["grant:api-demo"],
        "required_tests": ["identity", "sandbox"],
        "grants": [
            {
                "grant_id": "grant:api-demo",
                "subject_id": "agent:api-demo",
                "effects": ["read"],
                "scope_roots": ["workspace:demo"],
                "approved_by": "human:owner",
                "evidence_refs": ["receipt:grant"],
                "state": "admitted",
            }
        ],
        "bindings": [
            {
                "binding_id": "binding:api-demo",
                "subject_kind": "agent",
                "subject_id": "agent:api-demo",
                "capability_id": "capability:search",
                "capability_version": "1.0.0",
                "effect_grant_ids": ["grant:api-demo"],
                "cost_policy": "non-billable",
                "egress_policy": "deny",
                "state": "admitted",
                "evidence_refs": ["receipt:binding"],
            }
        ],
    }
    studio_operation(tmp_path, "agent", "create", _authorized(tmp_path, "agent", "create", value))
    assert studio_operation(tmp_path, "agent", "test", _authorized(tmp_path, "agent", "test", value))["passed"] is True
    studio_operation(tmp_path, "agent", "register-authority", _authorized(tmp_path, "agent", "register-authority", value))
    assert studio_operation(tmp_path, "agent", "admit", _authorized(tmp_path, "agent", "admit", value))["decision"] == "admitted"
    run_payload = {**value, "task": {"objective": "verify adapter"}}
    result = studio_operation(
        tmp_path,
        "agent",
        "run",
        _authorized(tmp_path, "agent", "run", run_payload),
    )
    assert result["run_outcome"] == "succeeded"
    status = studio_operation(
        tmp_path, "agent", "status", {"run_id": result["run_id"]}
    )
    assert status["state"] == "succeeded"
    with __import__("pytest").raises(ValueError, match="illegal durable run transition"):
        studio_operation(
            tmp_path,
            "agent",
            "pause",
            _authorized(tmp_path, "agent", "pause", {
                "run_id": result["run_id"],
            }),
        )


def test_workflow_lifecycle_is_available_through_the_bounded_adapter(tmp_path) -> None:
    value = {
        "workflow_id": "workflow:api-demo",
        "version": "1.0.0",
        "owner": "human:owner",
        "nodes": [
            {
                "node_id": "node:identity",
                "executor_binding_id": "binding:workflow-api",
                "inputs": [{"name": "value", "data_type": "string"}],
                "outputs": [{"name": "value", "data_type": "string"}],
                "effect_grant_ids": ["grant:workflow-api"],
                "failure_policy": "fail-closed",
                "timeout_seconds": 5,
            }
        ],
        "edges": [],
        "grants": [
            {
                "grant_id": "grant:workflow-api",
                "subject_id": "workflow:api-demo",
                "effects": ["read"],
                "scope_roots": ["workspace:demo"],
                "approved_by": "human:owner",
                "evidence_refs": ["receipt:grant"],
                "state": "admitted",
            }
        ],
        "bindings": [
            {
                "binding_id": "binding:workflow-api",
                "subject_kind": "workflow",
                "subject_id": "workflow:api-demo",
                "capability_id": "capability:identity",
                "capability_version": "1.0.0",
                "effect_grant_ids": ["grant:workflow-api"],
                "cost_policy": "non-billable",
                "egress_policy": "deny",
                "state": "admitted",
                "evidence_refs": ["receipt:binding"],
            }
        ],
        "executor_adapters": {"binding:workflow-api": "identity"},
    }
    studio_operation(tmp_path, "workflow", "create", _authorized(tmp_path, "workflow", "create", value))
    studio_operation(tmp_path, "workflow", "register-authority", _authorized(tmp_path, "workflow", "register-authority", value))
    assert (
        studio_operation(tmp_path, "workflow", "validate", _authorized(tmp_path, "workflow", "validate", value))["decision"]
        == "admitted"
    )
    assert (
        studio_operation(tmp_path, "workflow", "dry-run", value)["effects_executed"]
        is False
    )
    run_payload = {**value, "run_inputs": {"node:identity.value": "bounded"}}
    result = studio_operation(
        tmp_path,
        "workflow",
        "run",
        _authorized(tmp_path, "workflow", "run", run_payload),
    )
    assert result["run_state"] == "succeeded"
    status = studio_operation(
        tmp_path, "workflow", "status", {"run_id": result["run_id"]}
    )
    assert status["state"] == "succeeded"
