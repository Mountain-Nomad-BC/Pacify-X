"""Native signed profile/catalog boundary, no transport or production authority."""
import json
from pathlib import Path
import pytest


def test_catalog_import_and_empty_profiles_do_not_require_missing_group_runtime(tmp_path):
    from runtime.remote_model_bridge import list_models
    from tests.test_provider_gateway_streaming import _project
    engine=_project(str(tmp_path));project=tmp_path/'project';project.mkdir()
    result=list_models(engine,project)
    assert result['models']==[] and result['authority_granted'] is False


@pytest.fixture
def profile_config(tmp_path,monkeypatch):
    from runtime.remote_provider_profiles import ROOT,CONFIG
    from runtime.studio_authority import StudioAuthorityStore
    monkeypatch.setenv('PX_STUDIO_KEY_ROOT',str(tmp_path/'host-keys'))
    root=tmp_path/'project';root.mkdir();authority=StudioAuthorityStore(root)
    row={'profile_id':'fixture','provider_id':'custom','adapter_id':'custom-openai-chat','model_id':'model',
      'model_revision':'declared-fixture','origin':'https://provider.example','approved_addresses':['8.8.8.8'],
      'credential_reference':'FIXTURE_PROVIDER_KEY','context_tokens':8192,'max_output_tokens':1024,
      'capabilities':{'coding':.5,'planning':.5,'review':.5,'classification':.5,'toolUse':False,'vision':False,'structuredOutput':False},
      'locality':'remote','cost_class':'billable-api','grant_id':'uncommissioned-grant','policy_locator':ROOT+'/policy.json',
      'budget_id':'uncommissioned-budget','authorized_requesters':['fixture-owner'],'revision_evidence':['fixture-declaration']}
    body={'schema_version':'px.remote-provider-profiles/1.0','state':'approved','approved_by':'fixture-owner',
      'evidence_refs':['controlled-fixture'],'expires_utc':'2099-01-01T00:00:00Z','profiles':[row]}
    path=root/CONFIG;path.parent.mkdir(parents=True);path.write_text(json.dumps(authority.sign_receipt(body)),encoding='utf-8')
    return root,authority,row,body,path


def test_signed_config_does_not_grant_model_availability(profile_config,tmp_path):
    from runtime.remote_provider_profiles import load_profiles
    from runtime.remote_model_bridge import list_models
    from tests.test_provider_gateway_streaming import _project
    root,authority,row,body,path=profile_config
    assert load_profiles(root)[1]==[row]
    result=list_models(_project(str(tmp_path)),root)
    assert len(result['models'])==1
    assert result['models'][0]['available'] is False
    assert result['models'][0]['production_host_custody_proved'] is False


def test_tampered_profile_or_unapproved_private_origin_is_rejected(profile_config):
    from runtime.remote_provider_profiles import load_profiles
    root,authority,row,body,path=profile_config
    value=json.loads(path.read_text());value['profiles'][0]['model_id']='rebound';path.write_text(json.dumps(value))
    with pytest.raises((ValueError,PermissionError)):load_profiles(root)
    row['approved_addresses']=['127.0.0.1'];path.write_text(json.dumps(authority.sign_receipt(body)))
    with pytest.raises(ValueError,match='private/non-global'):load_profiles(root)


@pytest.mark.parametrize('installed',[False,True])
def test_schema_resolves_from_current_framework_layout(profile_config,tmp_path,monkeypatch,installed):
    from runtime.remote_provider_profiles import load_profiles
    from runtime import paths
    root,authority,row,body,path=profile_config
    if installed:
        package=tmp_path/'site-packages/runtime';package.mkdir(parents=True)
        monkeypatch.setattr(paths,'__file__',str(package/'paths.py'))
        data=tmp_path/'data';assets=data/'share/engineering-bootstrap';(assets/'bootstrap').mkdir(parents=True)
        (assets/'bootstrap/startup.toml').write_text('# fixture asset marker')
        schema=Path('contracts/operations/remote-provider-profile.schema.json')
        (assets/schema).parent.mkdir(parents=True);(assets/schema).write_bytes(schema.read_bytes())
        monkeypatch.setattr(paths.sysconfig,'get_path',lambda key:str(data))
        assert paths.framework_root()==assets
    assert load_profiles(root)[1]==[row]


def test_protocol_mapping_resource_is_declared_for_actual_installed_package():
    import tomllib
    from runtime.remote_service_protocols import service_protocol
    for adapter,provider in [('custom-openai-chat','custom'),('openai-responses','openai'),('mistral-chat','mistral'),('claude-anthropic-messages','claude')]:
        assert service_protocol(adapter,provider)['provider_id']==provider
    with pytest.raises(PermissionError):service_protocol('openai-responses','custom')
    config=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    assert 'remote_service_protocols.json' in config['tool']['setuptools']['package-data']['engineering_bootstrap']


def test_remote_profile_contract_has_source_authentic_owner_and_real_consumers():
    from scripts.build_contract_ownership_registry import build
    root=Path(__file__).resolve().parents[1]
    record=next(row for row in build(root)['records'] if row['path']=='contracts/operations/remote-provider-profile.schema.json')
    assert record['owner']=='runtime/remote_provider_profiles.py'
    assert 'runtime/remote_model_bridge.py' in record['consumers']
    assert 'tests/test_remote_profile_catalog.py' in record['tests']
    for name in [record['owner'],*record['consumers'],*record['tests']]:assert (root/name).is_file(),name
