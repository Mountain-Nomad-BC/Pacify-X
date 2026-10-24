"""Derived capability navigation never grants itself registry write authority."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest

from runtime.semantic_index import build_semantic_index
from tests.test_studio_operation_mirror_custody import native


@pytest.mark.parametrize('builder,target', [('build_semantic_capability_index', 'semantic_capability_index'),
                                          ('build_agency_agent_graph', 'agency_agent_graph')])
def test_direct_cli_without_admission_cannot_create_index(tmp_path, builder, target):
    (tmp_path / 'registry').mkdir()
    (tmp_path / 'registry/skill_catalog.toml').write_text('skills = []\n')
    (tmp_path / 'registry/agency_agent_registry.json').write_text(json.dumps({'provider_id': 'agency-agents', 'agent_count': 0, 'agents': []}))
    script = Path(__file__).resolve().parents[1] / ('scripts/' + builder + '.py')
    result = subprocess.run([sys.executable, '-B', str(script), '--root', str(tmp_path)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert not (tmp_path / ('registry/' + target + '.json')).exists()


@pytest.mark.parametrize('builder,target', [('build_semantic_capability_index', 'semantic_capability_index'),
                                          ('build_agency_agent_graph', 'agency_agent_graph')])
def test_native_cli_commits_actual_derived_image(native, builder, target):
    import importlib
    cli = importlib.import_module('scripts.' + builder)
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    root, admission = native
    (root / 'registry/skill_catalog.toml').write_text('skills = []\n')
    (root / 'registry/agency_agent_registry.json').write_text(json.dumps({'provider_id': 'agency-agents', 'agent_count': 0, 'agents': []}))
    assert cli.main(['--root', str(root), '--admission-event-id', admission]) == 0
    image = (root / ('registry/' + target + '.json')).read_bytes()
    from runtime.agent_provider import build_agent_graph
    assert json.loads(image) == (build_semantic_index(root) if builder == 'build_semantic_capability_index'
                                else build_agent_graph(root))
    assert any(row['state'] == 'committed' and row['result_sha256'] == hashlib.sha256(image).hexdigest()
               for row in EffectIntentLedger(root)._load()['intents'])
    assert ScopeLeaseStore(root).active(effect='write') == ()
    if builder == 'build_agency_agent_graph':
        assert cli.main(['--root', str(root), '--check']) == 0


@pytest.mark.parametrize('builder', ['build_semantic_capability_index', 'build_agency_agent_graph'])
@pytest.mark.parametrize('target', ['outside.json', 'registry/../outside.json'])
def test_output_outside_native_registry_cannot_be_published(native, builder, target):
    import importlib
    from runtime.scope_lease import ScopeLeaseStore
    root, admission = native
    (root / 'registry/skill_catalog.toml').write_text('skills = []\n')
    (root / 'registry/agency_agent_registry.json').write_text(json.dumps({'provider_id': 'agency-agents', 'agent_count': 0, 'agents': []}))
    cli = importlib.import_module('scripts.' + builder)
    with pytest.raises(ValueError):
        cli.main(['--root', str(root), '--output', target, '--admission-event-id', admission])
    assert not (root / 'outside.json').exists()
    assert ScopeLeaseStore(root).active(effect='write') == ()
