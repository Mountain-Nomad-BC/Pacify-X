from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_release_successor_configs as owner


def _make_vsix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("extension.vsixmanifest", "<PackageManifest />")
        archive.writestr(
            "extension/package.json",
            json.dumps({"name": "product", "version": "1.0.1"}),
        )
        archive.writestr("extension/extension.js", "module.exports = {};\n")


def test_successor_binds_current_campaign_date_version_and_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    artifact = root / "extension" / "dist" / "product-1.0.1.vsix"
    _make_vsix(artifact)

    installed = root / "installed" / "product-1.0.1"
    installed.mkdir(parents=True)
    (installed / "package.json").write_text(
        json.dumps({"name": "product", "version": "1.0.1"}),
        encoding="utf-8",
    )
    (installed / "extension.js").write_text(
        "module.exports = {};\n",
        encoding="utf-8",
    )
    (installed / ".vsixmanifest").write_text(
        "<PackageManifest />",
        encoding="utf-8",
    )

    code_command = root / "code.cmd"
    code_command.write_text("@echo off\n", encoding="utf-8")

    cohesion_dag = root / "cohesion-dag.json"
    cohesion_dag.write_text("{}\n", encoding="utf-8")

    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()

    artifact_dir = root / "release-artifacts"
    artifact_dir.mkdir()

    signing_key = root / "signing.key"
    signing_key.write_text("test-key\n", encoding="utf-8")

    spec = {
        "schema_version": owner.SPEC_SCHEMA,
        "root": str(root),
        "candidate_id": "candidate-20260919-new",
        "candidate_date": "20260919",
        "predecessor_campaign_id": "candidate-old",
        "repair_campaign_id": "repair-current",
        "evidence_prefix": "final-new",
        "release_version": "1.0.1",
        "artifact": "extension/dist/product-1.0.1.vsix",
        "install": {
            "directory": str(installed),
            "code_command": str(code_command),
        },
        "cohesion_dag": str(cohesion_dag),
        "finalize": {
            "wheelhouse": str(wheelhouse),
            "artifact_dir": str(artifact_dir),
            "signing_key": str(signing_key),
        },
    }

    spec_path = root / "spec.json"
    automation_output = root / "state" / "successor-automation.json"
    stage_output = root / "state" / "successor-stage.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    monkeypatch.setattr(
        owner,
        "_validate_frozen_source",
        lambda candidate_root: ("a" * 40, "origin/main", "a" * 40),
    )
    monkeypatch.setattr(
        owner,
        "_release_version",
        lambda candidate_root, expected: "1.0.1",
    )
    monkeypatch.setattr(
        owner,
        "_git",
        lambda candidate_root, *args: (
            "f" * 40
            if args == ("rev-list", "-n", "1", "v1.0.1")
            else (_ for _ in ()).throw(
                AssertionError(f"unexpected git call: {args!r}")
            )
        ),
    )
    monkeypatch.setattr(
        owner,
        "_timeout_map",
        lambda candidate_root, overrides: {
            step: owner.DEFAULT_TIMEOUTS[step]
            for step in owner.STEP_ORDER
        },
    )

    result = owner.build(
        spec_path,
        automation_output,
        stage_output,
    )

    assert result["valid"] is True

    automation = json.loads(
        automation_output.read_text(encoding="utf-8")
    )
    stage = json.loads(
        stage_output.read_text(encoding="utf-8")
    )

    assert automation["candidate_date"] == "20260919"
    assert automation["repair_campaign_id"] == "repair-current"
    assert automation["candidate_id"] == stage["candidate_id"] == (
        "candidate-20260919-new"
    )
    assert automation["predecessor_campaign_id"] == "candidate-old"

    assert stage["artifact"]["path"] == (
        "extension/dist/product-1.0.1.vsix"
    )
    assert stage["install"]["directory"] == str(installed.resolve())
    assert stage["install"]["version"] == "1.0.1"

    combined = (
        automation_output.read_text(encoding="utf-8")
        + stage_output.read_text(encoding="utf-8")
    )
    for stale in (
        "final-old",
        "product-1.0.0.vsix",
        "repair-old",
    ):
        assert stale not in combined

    # A failed second publication must retain the first image, even if another
    # writer has replaced it; cleanup has no authority over that replacement.
    failed_stage = root / "state" / "failed-stage.json"
    failed_automation = root / "state" / "failed-automation.json"
    original_write = owner._write_new

    def fail_second(path, value):
        if path == failed_automation:
            failed_stage.write_text("replacement evidence", encoding="utf-8")
            raise OSError("second publication failed")
        original_write(path, value)

    monkeypatch.setattr(owner, "_write_new", fail_second)
    with pytest.raises(OSError, match="second publication failed"):
        owner.build(spec_path, failed_automation, failed_stage)
    assert failed_stage.read_text(encoding="utf-8") == "replacement evidence"
    assert not failed_automation.exists()


def test_new_control_file_preserves_concurrent_creation(tmp_path, monkeypatch):
    path = tmp_path / "control.json"
    original_exists = Path.exists

    def concurrent_exists(selected):
        if selected == path and not original_exists(selected):
            selected.write_text("concurrent evidence", encoding="utf-8")
            return False
        return original_exists(selected)

    monkeypatch.setattr(Path, "exists", concurrent_exists)
    with pytest.raises(owner.BuildBlocked, match="overwrite"):
        owner._write_new(path, {"candidate": "new"})
    assert path.read_text(encoding="utf-8") == "concurrent evidence"


def test_control_serialization_fails_before_creating_directories(tmp_path):
    path = tmp_path / "not-created" / "control.json"
    with pytest.raises(TypeError):
        owner._write_new(path, {"invalid": object()})
    assert not path.parent.exists()


def current_build_fixture(tmp_path, monkeypatch):
    from tests.test_release_stage_owner import _current_realization_fixture
    from runtime.release_source_identity import release_configuration_relative, release_private_installation_relative
    from runtime.project_revision_succession import current_campaign_path
    stage, automation, old_path, effects, calls, authority, gap = _current_realization_fixture(tmp_path,monkeypatch)
    root=stage.root
    campaign=current_campaign_path(root);state=json.loads(campaign.read_bytes());state['phase']='repair_frozen'
    campaign.write_text(json.dumps(state),encoding='utf-8')
    candidate='disposable-release-20261114-next'
    control=root/'.agentic_engineering_os_px/runtime-core/current-builder-fixture'
    control.mkdir(parents=True)
    dag=control/'dag.json';dag.write_text('{}',encoding='utf-8')
    private=root/release_private_installation_relative(candidate)
    spec={'schema_version':owner.CURRENT_SPEC_SCHEMA,'root':str(root),'candidate_id':candidate,
          'candidate_date':'20261114','predecessor_campaign_id':stage.candidate_id,
          'repair_campaign_id':state['campaign_id'],'evidence_prefix':'fixture-next',
          'release_version':'0.9.0','artifact':stage.artifact.relative_to(root).as_posix(),
          'source_freeze':stage.source_freeze_reference,
          'install':{'directory':str(private/'extensions/fixture.z-fixture-0.9.0'),'code_command':str(stage.code_command)},
          'cohesion_dag':dag.relative_to(root).as_posix(),
          'finalize':{'wheelhouse':str(control/'wheelhouse'),'artifact_dir':str(control/'final-artifacts'),
                      'signing_key':str(control/'not-a-real-signing-key')}}
    spec_path=control/'build-spec.json';spec_path.write_text(json.dumps(spec),encoding='utf-8')
    def no_git(*args,**kwargs):pytest.fail('current builder must not invoke Git or require committed artifacts')
    monkeypatch.setattr(owner,'_git',no_git);monkeypatch.setattr(owner,'_validate_frozen_source',no_git)
    monkeypatch.setattr(owner,'_timeout_map',lambda *args:{step:7200 for step in owner.STEP_ORDER})
    return spec_path,root/release_configuration_relative(candidate,'automation'),root/release_configuration_relative(candidate,'stage-owner'),stage


def test_current_builder_emits_planned_native_pair_without_git_or_artifact(tmp_path,monkeypatch):
    from scripts.run_release_candidate import Config as AutomationConfig
    from scripts.run_release_stage_owner import Config as StageConfig
    actual_timeout_map=owner._timeout_map
    spec, automation_path, stage_path, fixture = current_build_fixture(tmp_path,monkeypatch)
    # Exercise the actual project envelope through both generated configuration loaders.
    actual_timeouts=actual_timeout_map(Path(__file__).resolve().parents[1],None)
    monkeypatch.setattr(owner,'_timeout_map',lambda *args:dict(actual_timeouts))
    result=owner.build(spec,automation_path,stage_path)
    assert result['valid'] and result['artifact']['state']=='planned'
    assert not fixture.artifact.exists()
    automation=json.loads(automation_path.read_bytes());stage=json.loads(stage_path.read_bytes())
    assert not {'artifact_sha256','artifact_size','artifact_mtime_ns','identity_manifest'} & automation.keys()
    assert stage['install']['state']=='planned' and set(stage['artifact'])=={'state','path','type','build_owner'}
    assert automation['log_root']==stage['log_dir']
    assert len(automation['fresh_paths'])==len(set(automation['fresh_paths']))
    command=automation['owners']['installed_operational']['commands'][0]
    assert '--stage-owner-config' in command and '--artifact-sha256' not in command
    assert owner.OBSERVED_SHA_SLOT in command[command.index('--windows-argv-json')+1]
    assert AutomationConfig.load(automation_path).artifact_state=='planned'
    assert AutomationConfig.load(automation_path).timeouts_seconds==actual_timeouts
    assert StageConfig.load(stage_path).artifact_state=='planned'
    from scripts.run_release_candidate import validate_current_realization_plan, AutomationBlocked
    host_checks=[]
    monkeypatch.setattr('runtime.release_process_custody.require_release_host',lambda root:host_checks.append(root))
    validate_current_realization_plan(AutomationConfig.load(automation_path))
    assert host_checks==[fixture.root]
    from dataclasses import replace
    parsed=AutomationConfig.load(automation_path);owners=dict(parsed.owners)
    owners['package']=((owners['package'][0][0],'-B','unrelated-installer.py'),)
    with pytest.raises(AutomationBlocked,match='argv differs'):
        validate_current_realization_plan(replace(parsed,owners=owners))
    def unavailable(root):raise PermissionError('fixture host unavailable')
    monkeypatch.setattr('runtime.release_process_custody.require_release_host',unavailable)
    with pytest.raises(PermissionError,match='host unavailable'):
        validate_current_realization_plan(parsed)

    first=stage_path.read_bytes()
    with pytest.raises(owner.BuildBlocked,match='overwrite'):
        owner.build(spec,automation_path,stage_path)
    assert stage_path.read_bytes()==first


@pytest.mark.parametrize('mutation',['open_intake','unresolved','wrong_locator','issued_artifact','wrong_install','source_changed','wrong_distro'])
def test_current_builder_refuses_unsafe_plan_before_output(tmp_path,monkeypatch,mutation):
    from runtime.project_revision_succession import current_campaign_path
    spec_path, automation_path, stage_path, fixture=current_build_fixture(tmp_path,monkeypatch)
    spec=json.loads(spec_path.read_bytes())
    if mutation in {'open_intake','unresolved'}:
        p=current_campaign_path(fixture.root);state=json.loads(p.read_bytes())
        state['intake_open']=mutation=='open_intake';state['unresolved']=['fixture-unresolved'] if mutation=='unresolved' else []
        p.write_text(json.dumps(state),encoding='utf-8')
    elif mutation=='wrong_locator':stage_path=stage_path.with_name('wrong.json')
    elif mutation=='issued_artifact':fixture.artifact.parent.mkdir(parents=True,exist_ok=True);fixture.artifact.write_bytes(b'issued; preserve')
    elif mutation=='wrong_install':spec['install']['directory']=str(fixture.root/'wrong-private');spec_path.write_text(json.dumps(spec),encoding='utf-8')
    elif mutation=='wrong_distro':spec['ubuntu_distro']='unbound-distro';spec_path.write_text(json.dumps(spec),encoding='utf-8')
    elif mutation=='source_changed':(fixture.root/'runtime/cli.py').write_text('changed authored bytes',encoding='utf-8')
    with pytest.raises((owner.BuildBlocked,ValueError)):
        owner.build(spec_path,automation_path,stage_path)
    assert not automation_path.exists() and not stage_path.exists()
    if mutation=='issued_artifact':assert fixture.artifact.read_bytes()==b'issued; preserve'


def test_builder_accepts_actual_sequential_section_envelope_without_widening_other_stages():
    from runtime.test_profiles import governed_section_timeout_envelope
    from runtime.certification_contract import STAGE_TIMEOUT_LIMITS
    root=Path(__file__).resolve().parents[1]
    expected=governed_section_timeout_envelope(root)['__sequential_stage__']
    result=owner._timeout_map(root,None)
    assert result['sections']==expected and result['sections']<=STAGE_TIMEOUT_LIMITS['sections']
    assert STAGE_TIMEOUT_LIMITS['package']==14400
    with pytest.raises(owner.BuildBlocked,match='limit'):
        owner._timeout_map(root,{'sections':STAGE_TIMEOUT_LIMITS['sections']+1})
    with pytest.raises(owner.BuildBlocked,match='limit'):
        owner._timeout_map(root,{'package':14401})
    with pytest.raises(owner.BuildBlocked,match='sequential envelope'):
        owner._timeout_map(root,{'sections':expected-1})


@pytest.mark.parametrize('budget', [7200, 4200, 4800, 4919, 4920])
def test_installed_owner_budget_covers_sequential_phases(tmp_path, monkeypatch, budget):
    spec, automation, stage, fixture = current_build_fixture(tmp_path, monkeypatch)
    value = json.loads(spec.read_bytes())
    value['smoke_timeout_seconds'] = 600
    value['exhaustive_timeout_seconds'] = 4200
    spec.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(owner, '_timeout_map', lambda *args: {
        step: budget if step == 'installed_operational' else 7200
        for step in owner.STEP_ORDER
    })
    if budget >= 4920:
        result = owner.build(spec, automation, stage)
        assert result['valid']
        assert json.loads(automation.read_bytes())['timeouts_seconds']['installed_operational'] == budget
    else:
        with pytest.raises(owner.BuildBlocked, match='timeout|budget|sequential'):
            owner.build(spec, automation, stage)

@pytest.mark.parametrize('surface', ['root', 'spec', 'code', 'automation-output', 'stage-output', 'artifact', 'installation', 'python'])
def test_current_builder_rejects_original_path_aliases(tmp_path, monkeypatch, surface):
    spec, automation, stage, fixture = current_build_fixture(tmp_path, monkeypatch)
    value = json.loads(spec.read_bytes())
    root_alias = tmp_path / 'root-alias'
    root_alias.symlink_to(fixture.root, target_is_directory=True)
    if surface == 'root':
        value['root'] = str(root_alias)
    elif surface == 'spec':
        alias = tmp_path / 'spec-alias.json'
        alias.symlink_to(spec)
        spec = alias
    elif surface == 'code':
        alias = tmp_path / 'Code-alias.exe'
        alias.symlink_to(fixture.code_command)
        value['install']['code_command'] = str(alias)
    elif surface == 'python':
        import sys
        alias = tmp_path / 'python-alias.exe'
        alias.symlink_to(Path(sys.executable))
        value['python_command'] = str(alias)
    elif surface == 'automation-output':
        automation = root_alias / automation.relative_to(fixture.root)
    elif surface == 'stage-output':
        stage = root_alias / stage.relative_to(fixture.root)
    elif surface == 'artifact':
        value['artifact'] = str(root_alias / value['artifact'])
    elif surface == 'installation':
        value['install']['directory'] = str(root_alias / Path(value['install']['directory']).relative_to(fixture.root))
    if surface != 'spec':
        spec.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises((owner.BuildBlocked, ValueError), match='link|reparse'):
        owner.build(spec, automation, stage)
    assert not automation.exists() and not stage.exists()


@pytest.mark.parametrize('surface', ['root', 'config', 'code', 'installation'])
def test_stage_config_rejects_original_path_aliases(tmp_path, monkeypatch, surface):
    from scripts.run_release_stage_owner import Config, OwnerBlocked
    spec, automation, stage, fixture = current_build_fixture(tmp_path, monkeypatch)
    owner.build(spec, automation, stage)
    value = json.loads(stage.read_bytes())
    root_alias = tmp_path / 'root-alias'
    root_alias.symlink_to(fixture.root, target_is_directory=True)
    if surface == 'root':
        value['root'] = str(root_alias)
    elif surface == 'config':
        alias = stage.parent / 'stage-alias.json'
        alias.symlink_to(stage)
        stage = alias
    elif surface == 'code':
        alias = tmp_path / 'Code-alias.exe'
        alias.symlink_to(fixture.code_command)
        value['install']['code_command'] = str(alias)
    elif surface == 'installation':
        value['install']['directory'] = str(root_alias / Path(value['install']['directory']).relative_to(fixture.root))
    if surface != 'config':
        stage.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises((OwnerBlocked, ValueError), match='link|reparse'):
        Config.load(stage)
