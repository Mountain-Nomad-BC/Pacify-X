"""Mock host transport around real prepared/group/artifact owners; no process/network launch."""
import pytest
from types import SimpleNamespace
from tests.test_remote_model_bridge import configured
from tests.test_remote_group_effect_owner import remote_group_fixture
from tests.studio_approval_testkit import approval_proof
from runtime.remote_model_bridge import chat
from runtime.remote_provider_profiles import digest
from runtime.studio_models import digest as receipt_digest
from runtime.task_execution_plan import persist_task_execution_plan


@pytest.mark.parametrize("corrupt", [False,True])
def test_bridge_reads_real_committed_member_and_never_replays(configured,monkeypatch,corrupt):
    from runtime import workflow_studio
    f=remote_group_fixture(configured,monkeypatch)
    engine,root,authority,profile,_=configured
    persist_task_execution_plan(root,f["plan"])
    calls=[]
    owner={"node_id":"node:group","workflow_id":"workflow:effect","version":"1.0.0"}
    snapshot={}
    class MockHostTransport:
        def __init__(self,project): self.run_control=SimpleNamespace(read_snapshot=lambda run:snapshot)
        def resolve_prepared_group_owner(self,reference): return owner
        def execute_prepared_group_node(self,reference,*,approved_by):
            calls.append(approved_by)
            result=f["controller"].execute_governed_group(f["spec"],task_plan=f["plan"].as_dict(),placements=f["placements"],approval=True,member_executor=f["executor"],generation_observer=lambda:f["plan"].context_generation,evidence_resolver=f["resolver"],accepted_producers={"unit:producer"},attestation_provider=None,workflow_effect_receipt=f["signed"])
            assert result["control_state"]=="succeeded",result["member_failures"]
            committed=[{**row,"result_sha256":f["ledger"].fence(row["idempotency_key"])["result_sha256"]} for row in result["workflow_effect_bindings"]]
            results={"node:group":{"control_state":"succeeded","group_run_sha256":result["group_run_sha256"]}}
            snapshot.update(state="succeeded",subject_id=owner["workflow_id"],version=owner["version"],checkpoint={"results":results,"node_receipts":[{"node_id":"node:group","attempts":[{"execution_context":result["workflow_execution_context"],"committed_effect_intents":committed}]}]})
            if corrupt: committed[0]["result_sha256"]="f"*64
            return authority.sign_receipt({"run_id":f["run_id"],"workflow_id":owner["workflow_id"],"version":owner["version"],"status":"succeeded","output_sha256":receipt_digest(results)})
    monkeypatch.setattr(workflow_studio,"WorkflowStudio",MockHostTransport)
    selected={"prepared_group_reference":{"schema_version":"px.prepared-group-reference/1.0","plan_id":f["plan"].plan_id,"plan_sha256":f["plan"].plan_sha256},"profile_id":profile["profile_id"],"profile_sha256":digest(profile),"provider_id":profile["provider_id"]}
    request={**selected,"approval_capability":approval_proof(root,"remote-model","chat",selected)}
    if corrupt:
        with pytest.raises(PermissionError,match="settlement changed"): chat(engine,root,request)
    else:
        output=chat(engine,root,request)
        assert output["provider_model_id"]==profile["model_id"] and output["model_id"]!=profile["model_id"]
        assert output["value"]=="hello" and output["branch_artifact"]
    assert calls==["human:vscode-local-user"] and len(f["transport"].calls)==1
    with pytest.raises(PermissionError): chat(engine,root,request)
    assert len(calls)==1 and len(f["transport"].calls)==1
