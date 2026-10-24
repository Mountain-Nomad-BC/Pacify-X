"""Disposable source-owner semantics only; never campaign freeze/certification/Git operations."""
import json
import hashlib
import pytest
from runtime import release_source_identity as owner
from runtime.release_repository_context import verify_source_anchor
from runtime.release_campaign import clear_release_identity,apply_release_identity,REPAIR_CAMPAIGN_PATH
from runtime.source_freeze import freeze_source
from tests.release_preflight_testkit import minimal_product


def isolated_source(tmp_path):
    root=minimal_product(tmp_path)
    (root/"extension").mkdir();(root/"extension/package.json").write_text(json.dumps({"version":"0.9.0"}))
    (root/"pyproject.toml").write_text('[project]\nname="disposable-source-owner-fixture"\nversion="0.9.0"\n')
    policy={"schema_version":"px.validation-basis/1.0","basis":"current_implementation",
        "authority":"OWNER-FRESH-VALIDATION-001","campaign_id":"disposable-unit-source-campaign"}
    (root/"policies/rev1xx-validation.json").write_text(json.dumps(policy))
    from runtime.release_campaign import release_state_relative
    artifact_policy=root/"policies/release-artifact-policy.json"
    declared=json.loads(artifact_policy.read_text())
    declared["product_roots"].append("extension");declared["product_root_files"]=["pyproject.toml"]
    declared["control_output_paths"]=[REPAIR_CAMPAIGN_PATH.as_posix(),release_state_relative(root).as_posix()]
    artifact_policy.write_text(json.dumps(declared))
    # Simulated pre-stage control for source owner tests, not accepted operational or release evidence.
    control=root/REPAIR_CAMPAIGN_PATH;control.parent.mkdir(parents=True)
    control.write_text(json.dumps({"campaign_id":policy["campaign_id"],"phase":"repair_frozen","intake_open":False,"unresolved":[]}))
    clear_release_identity(root,campaign_id="disposable-unit-release")
    captured=freeze_source(root,freeze_id="disposable-unit-byte-preservation",current_campaign=True)
    path=captured.receipt["receipt_path"]
    ref={"path":path,"sha256":hashlib.sha256((root/path).read_bytes()).hexdigest()}
    control.write_text(json.dumps({"campaign_id":policy["campaign_id"],"phase":"revision_reconciled","intake_open":False,"unresolved":[]}))
    return root,ref


def test_current_source_identity_uses_actual_retained_bytes_and_no_git(tmp_path,monkeypatch):
    root,ref=isolated_source(tmp_path)
    monkeypatch.setattr(owner,"capture_git_identity",lambda *a,**k:pytest.fail("Git must not run for current source"))
    apply_release_identity(root,source_freeze_reference=ref)
    identity=owner.capture_release_source_identity(root,version="0.9.0")
    assert identity["valid"],identity
    assert identity["schema_version"]==owner.SCHEMA and identity["source_freeze"]==ref
    assert identity["git_acceptance"]=={"state":"deferred_by_owner","satisfied":False}
    assert not {"commit_sha","tree_sha","tag"}&identity.keys()
    assert owner.verify_release_source_identity(root,identity)["valid"]
    material,invocation=owner.provenance_source(identity,identity["source_product_digest"])
    assert "gitCommit" not in material["digest"] and "gitTree" not in material["digest"]
    assert invocation==identity["campaign_id"]
    (root/"runtime/owner.py").write_text("value = 2\n")
    assert not owner.verify_release_source_identity(root,identity)["valid"]


def test_missing_or_stale_final_anchor_never_applies_current_identity(tmp_path):
    root,ref=isolated_source(tmp_path)
    with pytest.raises(ValueError,match="source-freeze reference"):
        apply_release_identity(root)
    (root/"runtime/owner.py").write_text("value = 2\n")
    with pytest.raises(ValueError,match="differs from its retained freeze"):
        apply_release_identity(root,source_freeze_reference=ref)


def test_retained_archive_corruption_is_not_final_source_proof(tmp_path):
    root,ref=isolated_source(tmp_path)
    receipt=verify_source_anchor(root,ref,require_live=True)["receipt"]
    (root/receipt["archive"]["path"]).write_bytes(b"corrupt actual retained archive")
    with pytest.raises(ValueError,match="archive hash differs"):
        apply_release_identity(root,source_freeze_reference=ref)


def test_invalid_fresh_authority_never_falls_back_to_git(tmp_path,monkeypatch):
    (tmp_path/"policies").mkdir();(tmp_path/"policies/rev1xx-validation.json").write_text('{"basis":"current_implementation"}')
    monkeypatch.setattr(owner,"capture_git_identity",lambda *a,**k:pytest.fail("invalid authority must fail closed"))
    assert not owner.capture_release_source_identity(tmp_path,version="0.9.0")["valid"]


def test_legacy_source_identity_keeps_exact_native_git_dispatch(tmp_path,monkeypatch):
    calls=[];legacy={"valid":False,"errors":["fixture no Git admission"]}
    monkeypatch.setattr(owner,"capture_git_identity",lambda *a,**k:calls.append((a,k)) or legacy)
    assert owner.capture_release_source_identity(tmp_path,version="0.9.0") is legacy
    assert len(calls)==1 and calls[0][1]=={"version":"0.9.0"}


def planned_stage_config(tmp_path):
    from scripts.run_release_stage_owner import Config, CURRENT_SCHEMA
    root,ref=isolated_source(tmp_path)
    raw={"schema_version":CURRENT_SCHEMA,"root":str(root),"candidate_id":"disposable-unit-release","predecessor_id":"disposable-previous",
         "artifact":{"state":"planned","path":"extension/dist/unit.vsix","type":"vsix","build_owner":"extension/scripts/package-vsix.js"},
         "identity":{"identity_kind":"standalone_current_campaign","source_freeze":ref},
         "install":{"state":"planned","directory":str(tmp_path/"installed"),"code_command":str(tmp_path/"code")},
         "evidence_dir":".agentic_engineering_os_px/unit-release-evidence","log_dir":".agentic_engineering_os_px/unit-release-logs"}
    from runtime.release_source_identity import release_configuration_relative
    path=root/release_configuration_relative(raw["candidate_id"],"stage-owner");path.parent.mkdir(parents=True);path.write_text(json.dumps(raw))
    return Config.load(path),raw,path


def test_current_early_stage_requires_no_invented_artifact_or_install_evidence(tmp_path):
    config,raw,path=planned_stage_config(tmp_path)
    assert config.artifact_state==config.install_state=="planned"
    assert not config.artifact.exists()
    assert config.artifact_sha256==config.installed_tree_digest==""
    assert config.artifact_size==config.artifact_mtime_ns==0
    assert config.commit_message==config.release_tag==config.prior_tag_target==""
    from scripts.run_release_stage_owner import check
    early=check(config,"reconcile")
    assert not any("artifact" in error for error in early["errors"]),early
    late=check(config,"package")
    assert any("planned artifact cannot satisfy" in error for error in late["errors"]),late


@pytest.mark.parametrize("object_name,field,value",[("artifact","sha256","a"*64),("artifact","state","committed"),("install","tree_digest","a"*64)])
def test_current_planned_contract_rejects_invented_observations(tmp_path,object_name,field,value):
    from scripts.run_release_stage_owner import Config,OwnerBlocked
    config,raw,path=planned_stage_config(tmp_path)
    raw[object_name][field]=value;path.write_text(json.dumps(raw))
    with pytest.raises(OwnerBlocked):Config.load(path)


def test_current_automation_consumes_retained_source_input_without_git_or_rewrite(tmp_path,monkeypatch):
    from dataclasses import replace
    from tests.test_release_candidate_driver import config as legacy_fixture
    from scripts import run_release_candidate as automation
    source_root=tmp_path/"source-fixture";source_root.mkdir()
    root,ref=isolated_source(source_root)
    original=(root/ref["path"]).read_bytes()
    fixture_root=tmp_path/"automation-fixture";fixture_root.mkdir()
    config=replace(legacy_fixture(fixture_root),root=root,identity_kind="standalone_current_campaign",
                   source_freeze_reference=ref,identity_path_manifest=root/ref["path"],artifact_state="planned")
    monkeypatch.setattr(automation,"_git_output",lambda *a,**k:pytest.fail("current automation must not inspect Git"))
    monkeypatch.setattr(automation,"_validate_empty_git_index",lambda *a,**k:pytest.fail("current automation must not stage Git"))
    result=automation._prepare_identity_manifest(config)
    assert result["source_freeze"]==ref and result["git_acceptance"]["satisfied"] is False
    automation._validate_git_convergence(config)
    assert (root/ref["path"]).read_bytes()==original
    (root/"extension/package.json").write_text('{"version":"changed"}')
    with pytest.raises(ValueError,match="final authored source differs from its retained freeze"):
        automation._prepare_identity_manifest(config)


def test_current_pipeline_snapshot_observes_native_source_and_mutable_control_bytes(tmp_path):
    from types import SimpleNamespace
    from scripts.validate_certification_pipeline import _current_source_snapshot
    config,raw,path=planned_stage_config(tmp_path)
    # Config is an authored input: refreeze only this disposable unit root after adding it.
    result=freeze_source(config.root,freeze_id="disposable-unit-config-image",current_campaign=True)
    relative=result.receipt["receipt_path"]
    ref={"path":relative,"sha256":hashlib.sha256((config.root/relative).read_bytes()).hexdigest()}
    automation=SimpleNamespace(root=config.root,source_freeze_reference=ref)
    first=_current_source_snapshot(automation,config,path,path)
    assert first["source_tree"]==result.receipt["tree_sha256"]
    control=config.root/REPAIR_CAMPAIGN_PATH
    body=json.loads(control.read_text());body["phase"]="simulated-unit-transition";control.write_text(json.dumps(body))
    second=_current_source_snapshot(automation,config,path,path)
    assert first!=second and first["source_tree"]==second["source_tree"]


def test_pre_cert_step_order_is_the_existing_canonical_owner():
    from px.py_cert.runtime.pre_cert_contract import CERTIFICATION_STEP_ORDER
    from runtime.certification_contract import STEP_ORDER
    assert CERTIFICATION_STEP_ORDER is STEP_ORDER


def test_readiness_accepted_ids_require_native_evaluator_current_proof(tmp_path):
    from tests.test_plan_status_authority import fixture,authority
    from runtime.plan_registry import readiness_report,LEDGER_RELATIVE
    base,overlay,path,evidence=fixture(tmp_path)
    ledger=tmp_path/LEDGER_RELATIVE;ledger.parent.mkdir(parents=True);ledger.write_text(json.dumps(base))
    (tmp_path/"registry/punch_card_status.json").write_bytes(path.read_bytes())
    report=readiness_report(tmp_path,authority=authority(tmp_path))
    assert report["valid"] and report["accepted_card_ids"]==["BASE-001"]
    evidence.write_text('{"verified":false}')
    changed=readiness_report(tmp_path,authority=authority(tmp_path))
    assert changed["valid"] is False


def test_current_trace_assignments_do_not_satisfy_certification_denominator(tmp_path):
    from tests.test_plan_registry import _current_requirement_fixture
    from runtime.plan_registry import admit_current_requirement_trace,requirement_report
    from runtime.release_current_acceptance import current_certification_acceptance
    root,args=_current_requirement_fixture(tmp_path)
    trace=admit_current_requirement_trace(root,**args)
    path=root/"policies/rev1xx-validation.json";policy=json.loads(path.read_text())
    policy["requirement_trace"]={"path":trace["path"],"sha256":trace["sha256"]}
    policy.pop("foundation_status_authority",None);path.write_text(json.dumps(policy))
    assert requirement_report(root)["valid"]
    result=current_certification_acceptance(root)
    assert result["valid"] is False and result["requirement_count"]==118
    assert not result["accepted_card_ids"] and result["git_acceptance_satisfied"] is False
    assert all(not row["campaign_conformant"] for row in result["requirements"])
    assert result["circular_finalizer_exemptions"]==[]
    from runtime.release_certification import _eligible_ledger,_certificate_ledger_errors
    assert _eligible_ledger(root)==result["errors"]
    assert _certificate_ledger_errors(root)==result["errors"]
    assert not (root/"registry/corrective_release_ledger.json").exists()


def test_current_config_has_no_authored_freeze_self_reference(tmp_path):
    from runtime.release_source_identity import release_configuration_relative
    from scripts.run_release_stage_owner import Config,OwnerBlocked
    from runtime.release_repository_context import verify_source_anchor
    config,raw,path=planned_stage_config(tmp_path)
    assert verify_source_anchor(config.root,config.source_freeze_reference,require_live=True)
    wrong=config.root/"authored-stage-config.json";wrong.write_text(json.dumps(raw))
    with pytest.raises(OwnerBlocked,match="closed native derived-control locator"):
        Config.load(wrong)
    assert release_configuration_relative(raw["candidate_id"],"stage-owner")!=release_configuration_relative(raw["candidate_id"],"automation")
