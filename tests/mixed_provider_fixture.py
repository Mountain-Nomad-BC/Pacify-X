"""Disposable CPU contract fixture and recorded transports, never model measurements."""
import hashlib,io,json
from dataclasses import replace
from pathlib import Path
from tests.test_remote_model_bridge import RecordingTransport
from tests.test_remote_qualified_identity import prepare_qualified_fixture
from tests.test_remote_group_effect_owner import remote_group_fixture
from tests.test_model_group_preparation import prepared,plan_for
from tests.test_provider_gateway_streaming import _QueueOpener,_StreamHttpResponse
from runtime.model_attachment import build_model_attachment
from runtime.model_execution_group import ModelExecutionGroup
from runtime.model_group_preparation import prepare_model_group
from runtime.model_profile import load_runtime_profiles,runtime_profile_from_mapping
from runtime.group_provider_adapters import GroupProviderBinding
from runtime.provider_gateway import LlamaCppStreamingHttpAdapter,build_provider_execution_policy
from runtime.execution_placement import _hash


def mixed_fixture(configured,monkeypatch):
    engine,root,authority,_,_=configured
    artifact=root/'unit-local-contract.data';artifact.write_bytes(b'local transport contract fixture; not model weights')
    local_sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
    data={}
    def prepare(configured):
        first,remote_group,remote_prepared,_=prepare_qualified_fixture(configured,'openai')
        local_group,attachments,retrievals,_=prepared(1,root)
        local_id=local_group.model_ids[0]
        attachments[local_id]=build_model_attachment(root,model_id=local_id,model_revision='unit-local-contract',artifact_sha256=local_sha,runtime='llama.cpp',context_tokens=4096,modalities=('text',),supports_tools=False,privacy='local',authority_class='contained',benchmark_revision=hashlib.sha256(b'unit-only-contract').hexdigest(),hardware_requirements={'memory':'1GiB'})
        for row in remote_prepared.as_dict()['members']:
            from runtime.model_attachment import model_attachment_from_dict
            attachments[row['model_id']]=model_attachment_from_dict(row['attachment'])
            from runtime.semantic_integration_types import FusedQueryResult
            retrievals[row['model_id']]=FusedQueryResult('map source','px',(),{},0,'unit:retrieval','b'*64)
        group=ModelExecutionGroup('mixed','execution','owner',remote_group.branches+local_group.branches)
        preparation=prepare_model_group(group,attachments,retrievals,root=root)
        return first,group,preparation,plan_for(group,preparation)
    def local_for(item,plan,fixture):
        placement={'task_plan_sha256':plan.plan_sha256,'model_id':item.model_id,'model_attachment_sha256':item.attachment_sha256,'context_sha256':next(r['context_sha256'] for r in plan.model_group_preparation.as_dict()['members'] if r['model_id']==item.model_id),'selected_device':'cpu','fallback':{'device':'cpu'},'reason':'disposable bounded CPU contract','reservation_required':True,'required_capacity_bytes':1024**3,'available_capacity_bytes':16*1024**3,'hardware_fingerprint':'unit:cpu-contract-only'}
        placement['placement_sha256']=_hash(placement)
        if fixture is None:return {'placement':placement}
        source=next(p for p in load_runtime_profiles(Path.cwd()) if p.cpu_only)
        profile=runtime_profile_from_mapping({**source.identity_payload(),'model_id':item.model_id,'state':'candidate','benchmark_required':True,'context_tokens':4096,'max_output_tokens':8})
        _,response=RecordingTransport().open(credential='fixture-credential-never-log')
        opener=_QueueOpener([_StreamHttpResponse(lines=response.readlines())])
        adapter=LlamaCppStreamingHttpAdapter('http://127.0.0.1:9999',adapter_id='llama-cpp-stream',session_id='local-model-session-unit',model_sha256=local_sha,opener=opener)
        def current():
            if hashlib.sha256(artifact.read_bytes()).hexdigest()!=local_sha:raise PermissionError('local native artifact drift')
        binding=GroupProviderBinding(item.model_id,local_sha,profile,adapter,adapter.session_id,'local-budget',current)
        grant=next(authority.resolve_grant(g,subject_id='workflow:effect') for g in fixture['task']['effect_grant_ids'] if authority.resolve_grant(g,subject_id='workflow:effect')[0]['scope_roots']==['loopback'])
        policy=build_provider_execution_policy(task_plan_sha256=plan.plan_sha256,model={'provider_id':'llama.cpp','adapter_id':adapter.adapter_id,'model_id':local_sha,'model_revision':item.model_revision,'attachment_sha256':item.attachment_sha256,'privacy':item.privacy,'authority_class':item.authority_class},authority={'revision':grant[1],'provider_effect':True},egress={'mode':'loopback_only','allowed_destinations':['loopback']},cost={'budget_id':'local-budget','max_charge_microunits':0},fallbacks=[],exact_receipt_required=True)
        data.update(local_id=item.model_id,opener=opener,policy=policy,binding=binding)
        return {'placement':placement,'policy':policy,'binding':binding}
    original=RecordingTransport.open
    def recorded(self,**request):
        connection,response=original(self,**request)
        if request.get('adapter_id')=='openai-responses':
            response.close();response=io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"hello"}\n\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":1}}}\n\n')
        return connection,response
    monkeypatch.setattr(RecordingTransport,'open',recorded)
    # Explicit disposable native registry rows, not production admissions.
    for file in ('registry/provider_adapters.json','models/provider-protocols.json'):
        path=engine/file;doc=json.loads(path.read_text());row=doc['adapters'][0]
        if file.startswith('registry'):
            doc['adapters'] += [{**row,'adapter_id':'openai-responses','provider_id':'openai'},{**row,'adapter_id':'llama-cpp-stream','provider_id':'llama.cpp','mode':'local','billing_state':'local_non_billable'}]
        else:doc['adapters'] += [{**row,'adapter_id':'openai-responses','surfaces':['openai_responses']},{**row,'adapter_id':'llama-cpp-stream'}]
        path.write_text(json.dumps(doc))
    path=engine/'registry/provider_budget_policy.json';budget=json.loads(path.read_text());row=budget['budgets'][0];budget['budgets'] += [{**row,'budget_id':'openai-budget','provider_id':'openai'},{**row,'budget_id':'local-budget','provider_id':'llama.cpp'}];path.write_text(json.dumps(budget))
    f=remote_group_fixture(configured,monkeypatch,prepare=prepare,local_for=local_for)
    # The prepared second profile shares declared budget-1; give a provider-specific real policy row.
    budget=json.loads(path.read_text());budget['budgets'][1]['budget_id']='budget-1'
    for row in budget['budgets']:row.update(actor_id=f['spec'].owner,max_input_tokens=20000,max_output_tokens=4096,max_requests=8)
    path.write_text(json.dumps(budget))
    policies={model:(data['policy'] if model==data['local_id'] else binding.policy) for model,binding in f['bindings'].items()}
    carrier=root/'unit-native-provider-policies.json';carrier.write_text(json.dumps(authority.sign_receipt({'schema_version':'px.group-provider-policies/1.0','policies':policies})))
    monkeypatch.setenv('PX_PROVIDER_EXECUTION_POLICY',str(carrier))
    from runtime import workflow_worker
    monkeypatch.setattr(workflow_worker,'_group_adapter_resolver',lambda project:f['bindings'].get)
    return {**f,**data}
