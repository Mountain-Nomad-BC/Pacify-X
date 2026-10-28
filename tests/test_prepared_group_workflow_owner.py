from dataclasses import replace
import json
import pytest
from runtime.workflow_studio import WorkflowStudio, _definition_from_record
from runtime.task_execution_plan import persist_task_execution_plan
from runtime.studio_models import canonical_bytes, record
from tests.test_model_group_preparation import prepared, plan_for
from tests.test_workflow_studio import fixture


@pytest.fixture
def owner_case(tmp_path, monkeypatch):
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    root = tmp_path / "project"
    root.mkdir()
    group, _, _, preparation = prepared(1, root)
    plan = plan_for(group, preparation)
    persist_task_execution_plan(root, plan)
    reference = {"schema_version": "px.prepared-group-reference/1.0", "plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256}
    definition, bindings, grants = fixture()
    node = replace(definition.nodes[0], approval_required=True, config={"execution_mode": "prepared-model-group", "prepared_group_reference": reference})
    definition = replace(definition, nodes=(node,), edges=())
    studio = WorkflowStudio(root)
    studio.save_revision(definition)
    studio.register_authority(bindings[:1], grants, {bindings[0].binding_id: "increment"})
    studio.validate_and_admit(definition)
    path = next(studio.state_root.glob("*/revisions/*/record.json"))
    return studio, definition, reference, path


def test_revision_decoder_roundtrip(owner_case):
    _, definition, _, _ = owner_case
    assert canonical_bytes(record(_definition_from_record(json.loads(canonical_bytes(record(definition)))["record"]))) == canonical_bytes(record(definition))


def test_unintegrated_group_is_not_admitted(owner_case):
    studio, _, reference, _ = owner_case
    with pytest.raises(PermissionError, match="current runnable workflow admission"):
        studio.resolve_prepared_group_owner(reference)


@pytest.mark.parametrize("mutation", ["missing-owner", "stale-plan", "altered-revision", "missing-admission", "ambiguous-owner"])
def test_real_persisted_owner_failures(owner_case, mutation):
    studio, definition, reference, path = owner_case
    if mutation == "missing-owner":
        reference = {**reference}
        # Preserve a valid plan but remove its reference from this immutable record.
        value = json.loads(path.read_text(encoding="utf-8"))
        value["record"]["nodes"][0]["config"] = {}
        from runtime.studio_models import digest
        value["sha256"] = digest(value["record"])
        path.write_text(json.dumps(value), encoding="utf-8")
    elif mutation == "stale-plan":
        reference = {**reference, "plan_sha256": "0" * 64}
    elif mutation == "altered-revision":
        value = json.loads(path.read_text(encoding="utf-8"))
        value["record"]["owner"] = "tampered"
        path.write_text(json.dumps(value), encoding="utf-8")
    elif mutation == "missing-admission":
        path.with_name("admission-receipt.json").rename(path.with_name("retained-admission.json"))
    else:
        studio.save_revision(replace(definition, version="1.0.1"))
    with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
        studio.resolve_prepared_group_owner(reference)


def test_owner_directory_scan_is_bounded(owner_case):
    studio, _, reference, _ = owner_case
    for number in range(513):
        (studio.state_root / f"unrelated-{number}").mkdir()
    with pytest.raises(PermissionError, match="exceeded bound"):
        studio.resolve_prepared_group_owner(reference)


@pytest.mark.parametrize("mutation", ["extra", "no-approval", "bad-digest"])
def test_group_declaration_is_closed_and_requires_approval(owner_case, mutation):
    _, definition, _, _ = owner_case
    node = definition.nodes[0]
    config = {**node.config}
    kwargs = {}
    if mutation == "extra":
        config["approved_by"] = "human:vscode-local-user"
    elif mutation == "no-approval":
        kwargs["approval_required"] = False
    else:
        config["prepared_group_reference"] = {**config["prepared_group_reference"], "plan_sha256": "bad"}
    with pytest.raises(ValueError):
        replace(node, config=config, **kwargs)


def test_hardlinked_revision_is_refused(owner_case):
    import os
    studio, _, reference, path = owner_case
    os.link(path, path.with_name("retained-alias.json"))
    with pytest.raises(PermissionError, match="aliased workflow revision"):
        studio.resolve_prepared_group_owner(reference)


def test_linked_revision_directory_is_refused(owner_case):
    import os
    studio, _, reference, path = owner_case
    alias = studio.state_root / "alias"
    try:
        os.symlink(path.parent.parent.parent, alias, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"native symlink privilege unavailable: {error.winerror}")
    with pytest.raises(ValueError, match="linked"):
        studio.resolve_prepared_group_owner(reference)
