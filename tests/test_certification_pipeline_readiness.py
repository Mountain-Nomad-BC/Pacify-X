"""Pre-attempt coverage checks must fail before an expensive release is consumed."""
import json
from pathlib import Path

import pytest

from scripts.validate_certification_pipeline import certification_coverage, REQUIRED_LIFECYCLE_TESTS, REQUIRED_NODE_TESTS, ValidationBlocked


def fixture(root):
    (root / 'registry').mkdir()
    for relative in (*REQUIRED_LIFECYCLE_TESTS, *REQUIRED_NODE_TESTS):
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# disposable test', encoding='utf-8')
    value = {'certification': {'required_sections': ['release-lifecycle', 'ui-event-integrity']},
             'sections': {'release-lifecycle': {'command': ['python', '-m', 'pytest', *REQUIRED_LIFECYCLE_TESTS]},
                          'ui-event-integrity': {'cwd': 'extension', 'command': ['node', '--test', *[p.removeprefix('extension/') for p in REQUIRED_NODE_TESTS]]}}}
    path = root / 'registry/test_profiles.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path, value


def test_actual_repository_covers_every_required_lifecycle_suite():
    assert certification_coverage(Path(__file__).resolve().parents[1])['valid'] is True


@pytest.mark.parametrize('failure', ['missing-membership', 'missing-file', 'duplicate'])
def test_incomplete_or_duplicated_coverage_blocks_preflight(tmp_path, failure):
    path, value = fixture(tmp_path)
    members = value['sections']['release-lifecycle']['command']
    if failure == 'missing-membership':
        members.remove(REQUIRED_LIFECYCLE_TESTS[0])
    elif failure == 'missing-file':
        (tmp_path / REQUIRED_LIFECYCLE_TESTS[0]).rename(tmp_path / 'retained-original.py')
    else:
        members.append(REQUIRED_LIFECYCLE_TESTS[0])
    path.write_text(json.dumps(value), encoding='utf-8')
    assert certification_coverage(tmp_path)['valid'] is False


def test_listing_a_suite_while_filtering_away_its_tests_is_not_coverage(tmp_path):
    path, value = fixture(tmp_path)
    value['sections']['release-lifecycle']['command'].extend(['-k', 'nothing_can_match'])
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValidationBlocked, match='unfiltered'):
        certification_coverage(tmp_path)


@pytest.mark.parametrize('arguments', [
    ['--override-ini=addopts=--collect-only'],
    ['-o', 'addopts=--collect-only'],
    ['--collect-only=true'],
    ['-p', 'arbitrary_collection_plugin'],
])
def test_collection_or_plugin_override_cannot_impersonate_execution(tmp_path, arguments):
    path, value = fixture(tmp_path)
    value['sections']['release-lifecycle']['command'].extend(arguments)
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValidationBlocked, match='unfiltered'):
        certification_coverage(tmp_path)


def test_environment_cannot_change_required_collection(tmp_path):
    path, value = fixture(tmp_path)
    value['sections']['release-lifecycle']['environment'] = {'PYTEST_ADDOPTS': '--collect-only'}
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValidationBlocked, match='environment'):
        certification_coverage(tmp_path)


def test_optional_only_lifecycle_section_cannot_satisfy_certification_coverage(tmp_path):
    path, value = fixture(tmp_path)
    value['sections']['unrelated'] = {'command': ['python', '-m', 'pytest', 'tests/unrelated.py']}
    value['certification']['required_sections'] = ['unrelated']
    path.write_text(json.dumps(value), encoding='utf-8')
    assert certification_coverage(tmp_path)['valid'] is False


@pytest.mark.parametrize('flag', ['--test-only', '--test-name-pattern=never', '--test-skip-pattern=.*', '--test-shard=1/2'])
def test_filtered_node_audit_is_not_certification_coverage(tmp_path, flag):
    path, value = fixture(tmp_path)
    value['sections']['ui-event-integrity']['command'].insert(2, flag)
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValidationBlocked, match='unfiltered node'):
        certification_coverage(tmp_path)


@pytest.mark.parametrize('failure', ['missing-file', 'missing-membership', 'duplicate', 'optional-only'])
def test_node_audit_requires_current_file_and_mandatory_unique_membership(tmp_path, failure):
    path, value = fixture(tmp_path)
    command = value['sections']['ui-event-integrity']['command']
    if failure == 'missing-file':
        (tmp_path / REQUIRED_NODE_TESTS[0]).rename(tmp_path / 'retained-node-test.js')
    elif failure == 'missing-membership':
        command.remove('tests/event-integrity-audit.test.js')
    elif failure == 'duplicate':
        command.append('tests/event-integrity-audit.test.js')
    else:
        value['certification']['required_sections'].remove('ui-event-integrity')
    path.write_text(json.dumps(value), encoding='utf-8')
    assert certification_coverage(tmp_path)['valid'] is False


@pytest.mark.parametrize('arguments',[['--import=./exit-before-tests.js'],['--require','./exit-before-tests.js']])
def test_node_startup_injection_cannot_impersonate_required_execution(tmp_path,arguments):
    path,value=fixture(tmp_path)
    value['sections']['ui-event-integrity']['command'][2:2]=arguments
    path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValidationBlocked,match='unfiltered node'):certification_coverage(tmp_path)


@pytest.mark.parametrize('variable',['NODE_OPTIONS','NODE_PATH','PYTHONPATH'])
def test_startup_environment_cannot_override_required_collection(tmp_path,variable):
    path,value=fixture(tmp_path);value['environment']={variable:'unreviewed startup override'}
    path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValidationBlocked,match='environment'):certification_coverage(tmp_path)


@pytest.mark.parametrize('command,variable',[(['node','--test','fixture.test.js'],'NODE_OPTIONS'),(['node','--test','fixture.test.js'],'NODE_PATH'),(['python','-m','pytest','fixture.py'],'PYTEST_ADDOPTS'),(['python','-m','pytest','fixture.py'],'PYTEST_PLUGINS')])
def test_actual_test_owner_denies_override_before_workspace_or_child_creation(tmp_path,monkeypatch,command,variable):
    from runtime.test_runner import run_test_command
    monkeypatch.setattr('runtime.test_runner.ResourceManager',lambda *a,**k:pytest.fail('must refuse before creating resources'))
    with pytest.raises(ValueError,match='environment.*override'):
        run_test_command(command,cwd=tmp_path,environment={variable:'override'},timeout_seconds=5)


def test_actual_owner_denies_foreign_python_search_path_before_child_creation(tmp_path,monkeypatch):
    from runtime.test_runner import run_test_command
    foreign=tmp_path/'foreign';foreign.mkdir()
    monkeypatch.setattr('runtime.test_runner.ResourceManager',lambda *a,**k:pytest.fail('must refuse before creating resources'))
    with pytest.raises(ValueError,match='environment.*override'):
        run_test_command(['python','-m','pytest','fixture.py'],cwd=tmp_path,environment={'PYTHONPATH':str(foreign)},timeout_seconds=5)
