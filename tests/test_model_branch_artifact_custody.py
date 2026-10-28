import json
from pathlib import Path
import pytest
from tests.test_model_group_preparation import prepared, plan_for
from runtime.model_group_preparation import member_attachment, member_execution_input
from runtime.model_branch_artifacts import commit_branch_artifact, read_branch_artifact
from runtime.effect_intent import EffectIntentLedger
from runtime.scope_lease import ScopeLeaseStore


def invocation_fixture(root):
    group, _, _, preparation = prepared(1, root)
    plan = plan_for(group, preparation)
    _, member = member_attachment(plan.as_dict(), group.model_ids[0])
    return plan.as_dict(), member_execution_input(plan.as_dict(), member)


def test_committed_artifact_has_native_intent_and_retained_custody(tmp_path):
    plan, invocation = invocation_fixture(tmp_path)
    artifact = commit_branch_artifact(tmp_path, plan, invocation, {"answer": "exact"}, run_id="run:unit")
    assert json.loads(read_branch_artifact(tmp_path, artifact, invocation, run_id="run:unit")) == {"answer": "exact"}
    intents = EffectIntentLedger(tmp_path)._load()["intents"]
    assert len(intents) == 1
    assert intents[0]["state"] == "committed"
    assert intents[0]["result_sha256"] == artifact["artifact_sha256"]
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()


def test_identical_replay_is_read_only_and_conflicting_output_refused(tmp_path):
    plan, invocation = invocation_fixture(tmp_path)
    artifact = commit_branch_artifact(tmp_path, plan, invocation, {"answer": "first"}, run_id="run:unit")
    import hashlib
    before = {path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in tmp_path.rglob("*") if path.is_file()}
    assert commit_branch_artifact(tmp_path, plan, invocation, {"answer": "first"}, run_id="run:unit") == artifact
    assert {path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in tmp_path.rglob("*") if path.is_file()} == before
    with pytest.raises(ValueError, match="collision"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "changed"}, run_id="run:unit")


def test_partial_write_stays_uncommitted_and_cannot_blindly_retry(tmp_path, monkeypatch):
    import runtime.model_branch_artifacts as owner
    plan, invocation = invocation_fixture(tmp_path)
    def fail(path, raw):
        path.write_bytes(raw[:1])
        raise OSError("controlled partial write")
    monkeypatch.setattr(owner, "_publish_exact", fail)
    with pytest.raises(OSError, match="controlled partial write"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    intents = EffectIntentLedger(tmp_path)._load()["intents"]
    assert len(intents) == 1 and intents[0]["state"] == "failed"
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    with pytest.raises(ValueError, match="reconciliation"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")


def test_read_requires_current_native_commitment_not_manifest_alone(tmp_path, monkeypatch):
    plan, invocation = invocation_fixture(tmp_path)
    artifact = commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    monkeypatch.setattr(EffectIntentLedger, "fence", lambda self, key: {"disposition": "new"})
    with pytest.raises(ValueError, match="native.*commit"):
        read_branch_artifact(tmp_path, artifact, invocation, run_id="run:unit")


def test_post_image_commit_failure_stays_in_flight_and_not_deliverable(tmp_path, monkeypatch):
    plan, invocation = invocation_fixture(tmp_path)
    def fail_commit(self, **kwargs):
        raise OSError("controlled commitment settlement failure")
    monkeypatch.setattr(EffectIntentLedger, "commit", fail_commit)
    with pytest.raises(OSError, match="settlement failure"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    intent = EffectIntentLedger(tmp_path)._load()["intents"][0]
    assert intent["state"] == "in_flight"
    manifests = list(tmp_path.glob(".agentic_engineering_os_px/runtime-core/model-artifacts/**/commitment.json"))
    assert len(manifests) == 1
    artifact = {**json.loads(manifests[0].read_text()),
        "manifest_path": manifests[0].relative_to(tmp_path).as_posix()}
    with pytest.raises(ValueError, match="native.*commit"):
        read_branch_artifact(tmp_path, artifact, invocation, run_id="run:unit")
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()


def test_unfenced_existing_output_is_not_historically_backfilled(tmp_path):
    import runtime.model_branch_artifacts as owner
    plan, invocation = invocation_fixture(tmp_path)
    directory = owner._artifact_directory(tmp_path, invocation, "run:unit")
    directory.mkdir(parents=True)
    (directory / "output.json").write_text('{"answer":"old"}')
    with pytest.raises(ValueError, match="unfenced.*reconciliation"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "old"}, run_id="run:unit")
    assert EffectIntentLedger(tmp_path)._load()["intents"] == []
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()


def test_corrupt_publication_cannot_be_committed_as_success(tmp_path, monkeypatch):
    import runtime.model_branch_artifacts as owner
    plan, invocation = invocation_fixture(tmp_path)
    monkeypatch.setattr(owner, "_publish_exact", lambda path, raw: path.write_bytes(raw[:1]))
    with pytest.raises(ValueError, match="published branch images differ"):
        commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    assert EffectIntentLedger(tmp_path)._load()["intents"][0]["state"] == "failed"


def test_valid_manifest_cannot_be_relocated_outside_its_native_scope(tmp_path):
    plan, invocation = invocation_fixture(tmp_path)
    artifact = commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    alias = tmp_path / "alias.json"
    alias.write_bytes((tmp_path / artifact["manifest_path"]).read_bytes())
    with pytest.raises(ValueError, match="canonical branch custody location"):
        read_branch_artifact(tmp_path, {**artifact, "manifest_path": "alias.json"}, invocation, run_id="run:unit")


def test_retained_resource_custody_is_required_for_peer_delivery(tmp_path, monkeypatch):
    from runtime.resource_lifecycle import ResourceLedger
    plan, invocation = invocation_fixture(tmp_path)
    artifact = commit_branch_artifact(tmp_path, plan, invocation, {"answer": "value"}, run_id="run:unit")
    monkeypatch.setattr(ResourceLedger, "observe", lambda self: ())
    with pytest.raises(ValueError, match="native retained artifact custody"):
        read_branch_artifact(tmp_path, artifact, invocation, run_id="run:unit")
