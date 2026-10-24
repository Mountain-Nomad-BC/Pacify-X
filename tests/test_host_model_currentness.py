from dataclasses import replace,asdict
import json
import pytest
from tests.test_agent_runtime import fixtures
from runtime.agent_runtime import AgentRuntimeController


def host_fixture(root):
    body='Native host currentness fixture.\n'
    spec,binding,grant=fixtures(body)
    spec=replace(spec,harness_id='harness:vscode-lm',model={'provider':'vscode-lm','vendor':'copilot','model_id':'fixture-model','family':'fixture-family','version':'fixture-revision','max_output_tokens':256,'temperature':0})
    controller=AgentRuntimeController(root)
    controller.create_candidate(spec,body);controller.test_candidate(spec)
    controller.register_authority([binding],[grant]);controller.admit(spec)
    task={'objective':'bounded fixture'}
    prepared=controller.prepare_host_run(spec,task=task,approval=True)
    return controller,spec,grant,task,prepared


def images(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_native_signed_host_gate_observes_without_writing(tmp_path):
    controller,spec,grant,task,prepared=host_fixture(tmp_path)
    before=images(tmp_path)
    proof=AgentRuntimeController.assert_host_run_current(tmp_path,spec,run_id=prepared['run_id'],task=task)
    assert proof['control_sequence']==prepared['control_sequence']
    assert proof['authority_granted'] is False
    assert images(tmp_path)==before


@pytest.mark.parametrize('failure',['cancel','grant','task','model','prepared'])
def test_native_host_gate_rejects_actual_authority_or_control_drift(tmp_path,failure):
    controller,spec,grant,task,prepared=host_fixture(tmp_path)
    if failure=='cancel': controller.request_lifecycle(prepared['run_id'],'cancel',approved=True,approved_by='human:owner')
    if failure=='grant': controller.authority.admit_grant(replace(grant,scope_roots=('different-scope',)))
    if failure=='task': task={'objective':'changed'}
    if failure=='model': spec=replace(spec,model={**spec.model,'model_id':'unapproved-model'})
    if failure=='prepared':
        record=controller._existing_record_path(spec)
        path=record.parent/'runs'/f"{prepared['run_id']}-prepared.json"
        payload=json.loads(path.read_text());payload['task_sha256']='0'*64;path.write_text(json.dumps(payload))
    with pytest.raises((PermissionError,ValueError)):
        AgentRuntimeController.assert_host_run_current(tmp_path,spec,run_id=prepared['run_id'],task=task)


def test_missing_host_authority_does_not_initialize_keys_or_state(tmp_path):
    spec,_,_=fixtures('unused')
    with pytest.raises(FileNotFoundError):
        AgentRuntimeController.assert_host_run_current(tmp_path,spec,run_id='run-fixture',task={})
    assert list(tmp_path.iterdir())==[]


def test_normal_studio_read_operation_reaches_native_gate(tmp_path):
    from runtime.studio_api import studio_operation
    controller,spec,_,task,prepared=host_fixture(tmp_path)
    # Use the exact saved definition and instruction body, not caller authority.
    record=controller._existing_record_path(spec)
    payload={**json.loads(json.dumps(asdict(spec))),'instructions':record.with_name('instructions.md').read_text(),'run_id':prepared['run_id'],'task':task}
    result=studio_operation(tmp_path,'agent','check-host-run',payload)
    assert result['run_id']==prepared['run_id']
