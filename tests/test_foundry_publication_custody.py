"""Disposable native-ledger candidate publication evidence, never production commissioning."""
import hashlib
from pathlib import Path
import pytest
from runtime.knowledge_foundry import SourceArtifact,compile_foundry_bundle,materialize_candidate_bundle,read_candidate_publication
from runtime.studio_authority import StudioAuthorityStore
from runtime.operational_gap_ledger import append_event
from tests.test_operational_gap_ledger import initialize,card,evidence

@pytest.fixture
def host(tmp_path, monkeypatch):
    root=tmp_path/"project";root.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT",str(tmp_path/"host-keys"))
    authority=StudioAuthorityStore(root)
    from tests.foundry_publication_fixture import admit_publication_fixture
    admission=admit_publication_fixture(root)
    text="# Routing\nValidate routing evidence before promotion."
    bundle=compile_foundry_bundle((SourceArtifact("one","engineering_note","docs/one.md",hashlib.sha256(text.encode()).hexdigest(),text,"internal-reference",citation="docs/one.md"),))
    destination=root/".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates"
    kwargs=dict(project_root=root,project_id=authority.project_identity,run_id="disposable-run",admission_event_id=admission["event_id"])
    return bundle,destination,kwargs

def read(bundle,destination,kwargs):
    return read_candidate_publication(bundle.bundle_id,destination,**{k:v for k,v in kwargs.items() if k!="admission_event_id"})

def test_missing_native_identity_rejects_before_output(tmp_path):
    text="Validate evidence."
    bundle=compile_foundry_bundle((SourceArtifact("one","engineering_note","docs/one.md",hashlib.sha256(text.encode()).hexdigest(),text,"internal-reference",citation="docs/one.md"),))
    with pytest.raises(ValueError,match="explicit native"):
        materialize_candidate_bundle(bundle,tmp_path/"out")
    assert not (tmp_path/"out").exists()

def test_native_publication_and_observational_replay(host):
    bundle,destination,kwargs=host
    receipt=materialize_candidate_bundle(bundle,destination,**kwargs)
    assert receipt==read(bundle,destination,kwargs)
    before={str(p):p.read_bytes() for p in (destination/bundle.bundle_id).rglob("*") if p.is_file()}
    assert materialize_candidate_bundle(bundle,destination,**kwargs)==receipt
    assert before=={str(p):p.read_bytes() for p in (destination/bundle.bundle_id).rglob("*") if p.is_file()}

def test_missing_admission_and_wrong_project_fail_before_mkdir(host):
    bundle,destination,kwargs=host
    with pytest.raises(ValueError,match="explicit current"):
        materialize_candidate_bundle(bundle,destination,**{**kwargs,"admission_event_id":None})
    with pytest.raises(ValueError,match="project identity differs"):
        materialize_candidate_bundle(bundle,destination,**{**kwargs,"project_id":"px-project-foreign"})
    assert not destination.exists()

def test_modified_retained_image_and_extra_inventory_reject(host):
    bundle,destination,kwargs=host
    materialize_candidate_bundle(bundle,destination,**kwargs)
    image=destination/bundle.bundle_id/"bundle.json";raw=image.read_bytes();image.write_bytes(raw+b" ")
    with pytest.raises(ValueError,match="retained image differs"):read(bundle,destination,kwargs)
    image.write_bytes(raw);(image.parent/"unexpected").write_text("extra")
    with pytest.raises(ValueError,match="inventory differs"):read(bundle,destination,kwargs)

def test_partial_write_never_retries_or_becomes_committed(host,monkeypatch):
    bundle,destination,kwargs=host
    original=Path.open;seen=[]
    def broken(path,*a,**k):
        if a and a[0]=="xb" and bundle.bundle_id in path.parts:
            seen.append(path)
            if len(seen)==2:raise OSError("disposable write interruption")
        return original(path,*a,**k)
    monkeypatch.setattr(Path,"open",broken)
    with pytest.raises(OSError,match="interruption"):materialize_candidate_bundle(bundle,destination,**kwargs)
    monkeypatch.setattr(Path,"open",original)
    with pytest.raises(ValueError,match="uncertain"):materialize_candidate_bundle(bundle,destination,**kwargs)
    with pytest.raises((ValueError,FileNotFoundError)):read(bundle,destination,kwargs)

def test_wrong_output_namespace_rejects_before_output(host):
    bundle,destination,kwargs=host
    outside=kwargs["project_root"]/"source-output"
    with pytest.raises(ValueError,match="exact native"):materialize_candidate_bundle(bundle,outside,**kwargs)
    assert not outside.exists()


def test_overlapping_native_lease_blocks_before_bundle_output(host):
    from datetime import datetime,timedelta,timezone
    from runtime.scope_lease import ScopeLeaseStore
    bundle,destination,kwargs=host
    leases=ScopeLeaseStore(kwargs["project_root"])
    leases.acquire(lease_id="other-owner",execution_id="other-run",effect="write",
        scopes=(destination.relative_to(kwargs["project_root"]).as_posix(),),reason="disposable overlap test",
        expires_utc=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
    with pytest.raises(ValueError):materialize_candidate_bundle(bundle,destination,**kwargs)
    assert not (destination/bundle.bundle_id).exists()


def test_changed_bundle_input_same_identity_cannot_replay(host):
    from dataclasses import replace
    bundle,destination,kwargs=host
    materialize_candidate_bundle(bundle,destination,**kwargs)
    changed=replace(bundle,fitness={**bundle.fitness,"disposable_change":0.5})
    with pytest.raises(ValueError,match="replay content differs"):
        materialize_candidate_bundle(changed,destination,**kwargs)


def test_bad_skill_output_path_rejects_before_bundle_mkdir(host):
    from dataclasses import replace
    bundle,destination,kwargs=host
    assert bundle.skills
    broken=replace(bundle,skills=(replace(bundle.skills[0],skill_id="../../escape"),)+bundle.skills[1:])
    with pytest.raises(ValueError,match="output path"):
        materialize_candidate_bundle(broken,destination,**kwargs)
    assert not destination.exists()


def test_orphan_images_are_not_backfilled_as_native_evidence(host):
    bundle,destination,kwargs=host
    orphan=destination/bundle.bundle_id;orphan.mkdir(parents=True)
    (orphan/"receipt.json").write_text('{"bundle_id":"orphan"}')
    with pytest.raises(ValueError,match="orphan"):
        materialize_candidate_bundle(bundle,destination,**kwargs)
    assert not (orphan/"custody.json").exists()


def test_actual_studio_consumer_validates_full_retained_candidate(host):
    from runtime.skill_studio import SkillStudio
    from runtime.foundry_studio_bridge import export_foundry_candidate
    from runtime.json_io import load_json_object
    from runtime.knowledge_foundry import _stable
    bundle,destination,kwargs=host
    materialize_candidate_bundle(bundle,destination,**kwargs)
    authority=StudioAuthorityStore.open_existing(kwargs["project_root"])
    body=authority.verify_receipt(load_json_object(destination/bundle.bundle_id/"custody.json"))
    reference={"bundle_id":bundle.bundle_id,"run_id":kwargs["run_id"],"custody_sha256":_stable(body)}
    candidate=export_foundry_candidate(bundle,bundle.skills[0].skill_id)
    studio=SkillStudio(kwargs["project_root"])
    draft=studio.intake_foundry_candidate(candidate,studio_decision="accept",decided_by="disposable-human",decision_reason="Unit retained candidate check",retained_publication=reference)
    assert draft.canonical_promotion_authorized is False
    assert draft.draft_state=="draft"
    from dataclasses import replace
    altered=replace(bundle,skills=(replace(bundle.skills[0],purpose="Different unretained purpose"),)+bundle.skills[1:])
    valid_unretained=export_foundry_candidate(altered,candidate.skill_id)
    with pytest.raises(ValueError,match="complete retained"):
        studio.intake_foundry_candidate(valid_unretained,studio_decision="accept",decided_by="unit",decision_reason="unit",retained_publication=reference)

    with pytest.raises(ValueError,match="custody reference differs"):
        studio.intake_foundry_candidate(candidate,studio_decision="accept",decided_by="unit",decision_reason="unit",retained_publication={**reference,"custody_sha256":"a"*64})


def test_native_admission_checkpoint_change_fences_remaining_images(host,monkeypatch):
    bundle,destination,kwargs=host
    original=Path.open;changed=[]
    def advance(path,*a,**k):
        if a and a[0]=="xb" and bundle.bundle_id in path.parts and not changed:
            changed.append(True)
            append_event(kwargs["project_root"],"work_checkpoint",{"active_gap_id":"PX-GAP-0001","learned":"Disposable current admission changed.","next_action":card()["next_action"],"unresolved_branch_gap_ids":[],"newly_discovered_gap_ids":[],"evidence":evidence("new unit checkpoint")},actor="disposable-fixture")
        return original(path,*a,**k)
    monkeypatch.setattr(Path,"open",advance)
    with pytest.raises(ValueError):materialize_candidate_bundle(bundle,destination,**kwargs)
    with pytest.raises((ValueError,FileNotFoundError)):read(bundle,destination,kwargs)


def test_actual_signed_studio_dispatch_uses_host_principal_and_single_use(host):
    import json
    from dataclasses import asdict
    from runtime.studio_api import studio_operation
    from runtime.foundry_studio_bridge import export_foundry_candidate
    from runtime.knowledge_foundry import _stable
    from runtime.json_io import load_json_object
    from tests.studio_approval_testkit import authorized_payload
    bundle,destination,kwargs=host
    materialize_candidate_bundle(bundle,destination,**kwargs)
    root=kwargs["project_root"];authority=StudioAuthorityStore.open_existing(root)
    body=authority.verify_receipt(load_json_object(destination/bundle.bundle_id/"custody.json"))
    candidate=export_foundry_candidate(bundle,bundle.skills[0].skill_id)
    payload={"candidate":json.loads(json.dumps(asdict(candidate))),
        "retained_publication":{"bundle_id":bundle.bundle_id,"run_id":kwargs["run_id"],"custody_sha256":_stable(body)},
        "studio_decision":"accept","decision_reason":"Actual signed unit dispatch."}
    request=authorized_payload(root,"skill","intake-foundry-candidate",payload)
    draft=studio_operation(root,"skill","intake-foundry-candidate",request)
    assert draft["decided_by"]=="human:vscode-local-user"
    assert draft["canonical_promotion_authorized"] is False
    assert draft["draft_state"]=="draft"
    with pytest.raises(PermissionError):studio_operation(root,"skill","intake-foundry-candidate",request)
    unsigned={**payload,"approved":True,"decided_by":"caller-forged"}
    with pytest.raises(ValueError,match="exact signed"):
        studio_operation(root,"skill","intake-foundry-candidate",unsigned)
    payload["retained_publication"]["custody_sha256"]="a"*64
    bad=authorized_payload(root,"skill","intake-foundry-candidate",payload)
    with pytest.raises(ValueError,match="custody reference"):
        studio_operation(root,"skill","intake-foundry-candidate",bad)


def test_signed_intake_does_not_commission_missing_host(tmp_path):
    from runtime.studio_api import studio_operation
    with pytest.raises((ValueError,FileNotFoundError,PermissionError)):
        studio_operation(tmp_path,"skill","intake-foundry-candidate",{})
    assert list(tmp_path.iterdir())==[]
