"""Cross-owner verification invariants, using owned disposable fixtures only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from runtime import test_profiles as owner
from runtime import verification_inputs as inputs
from runtime import verification_receipts as receipts
from runtime import verification_status as status
from tests.verification_fixtures import fixture


def write_policy(root, policy):
    (root / inputs.POLICY).write_text(json.dumps(policy), encoding='utf-8')


def good_execution():
    return {'valid': True, 'exit_code': 0, 'timed_out': False, 'duration_seconds': 0.1,
            'stdout': '1 passed\n', 'stderr': ''}


def subjects():
    section = {'section': 'fixture', 'input_sha256': 'a' * 64, 'dependencies': [],
               'command': ['python', '-m', 'pytest', 'tests/test_one.py'], 'cwd_relative': '.'}
    chunk = {'chunk_id': 'chunk-01', 'input_sha256': 'b' * 64, 'members': ['tests/test_one.py'], 'member_count': 1}
    group = {'group': 'core', 'input_sha256': 'c' * 64, 'member_count': 1}
    return section, chunk, group


@pytest.mark.parametrize('kind', ['section', 'chunk', 'group'])
@pytest.mark.parametrize('mutation', ['missing-valid', 'boolean-exit', 'missing-timeout', 'nan-duration', 'unclosed-process'])
def test_incomplete_execution_never_implicitly_passes(kind, mutation):
    section, chunk, group = subjects()
    execution = good_execution()
    if mutation == 'missing-valid':
        del execution['valid']
    elif mutation == 'boolean-exit':
        execution['exit_code'] = False
    elif mutation == 'missing-timeout':
        del execution['timed_out']
    elif mutation == 'nan-duration':
        execution['duration_seconds'] = float('nan')
    else:
        execution['process_tree_terminated'] = False
    if mutation == 'boolean-exit':
        with pytest.raises(ValueError, match='process exit'):
            receipts.make_receipt(kind, {'section': section, 'chunk': chunk, 'group': group}[kind], execution, section=section)
        return
    row = receipts.make_receipt(kind, {'section': section, 'chunk': chunk, 'group': group}[kind], execution, section=section)
    assert row['passed'] is False and row['execution_valid'] is False
    assert receipts.validate(row, kind)


@pytest.mark.parametrize('kind', ['section', 'chunk', 'group'])
def test_receipt_validates_exact_schema_identity_and_semantics(kind):
    section, chunk, group = subjects()
    row = receipts.make_receipt(kind, {'section': section, 'chunk': chunk, 'group': group}[kind], good_execution(), section=section)
    assert receipts.validate(row, kind)
    assert not receipts.validate({**row, 'passed': False}, kind)
    assert not receipts.validate({**row, 'extra': True}, kind)
    assert not receipts.validate(row, kind, name='wrong-owner')
    body = {k: v for k, v in row.items() if k != 'receipt_sha256'}
    body.update(execution_valid=False, passed=True)
    assert not receipts.validate(receipts.seal(body), kind)


@pytest.mark.parametrize('name', ['', '../outside', 'a/b', 'a:b'])
def test_invalid_receipt_namespace_rejected_before_creation(tmp_path, name):
    with pytest.raises(ValueError):
        receipts.receipt_path(tmp_path, 'section', name)
    assert not list(tmp_path.iterdir())


def test_concurrent_receipt_publications_keep_exact_complete_image_and_closed_owner(tmp_path):
    section, chunk, _ = subjects()
    rows = [receipts.make_receipt('chunk', {**chunk, 'input_sha256': str(i) * 64}, good_execution(), section=section) for i in (1, 2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        targets = list(pool.map(lambda row: receipts.write(tmp_path, 'chunk', row), rows))
    assert targets[0] == targets[1]
    assert receipts.read(tmp_path, 'chunk', 'fixture', 'chunk-01') in rows
    from runtime.resource_lifecycle import ResourceLedger
    records = ResourceLedger(tmp_path / '.engineering-bootstrap/resource-lifecycle/ledger.json').load()
    assert len(records) == 2
    assert all(row.status == 'reclaimed' and not row.active for row in records)
    assert not list(targets[0].parent.glob('*.tmp'))


def test_failed_publication_retains_exact_owned_image_and_predecessor(tmp_path, monkeypatch):
    section, chunk, _ = subjects()
    row = receipts.make_receipt('chunk', chunk, good_execution(), section=section)
    target = receipts.write(tmp_path, 'chunk', row)
    before = target.read_bytes()
    original = receipts.os.replace

    def refused(source, destination):
        if Path(destination) == target:
            raise OSError('injected publication refusal')
        return original(source, destination)

    monkeypatch.setattr(receipts.os, 'replace', refused)
    with pytest.raises(OSError, match='injected'):
        receipts.write(tmp_path, 'chunk', row)
    assert target.read_bytes() == before
    from runtime.resource_lifecycle import ResourceLedger
    records = ResourceLedger(tmp_path / '.engineering-bootstrap/resource-lifecycle/ledger.json').load()
    retained = [r for r in records if r.status == 'retained']
    assert len(retained) == 1 and retained[0].retention_required
    assert Path(retained[0].path).is_file()


@pytest.mark.parametrize('value', [[], ['unknown'], ['fixture', 'fixture'], 'fixture'])
def test_empty_or_invalid_required_sections_cannot_certify(tmp_path, value):
    policy = fixture(tmp_path)
    policy['certification']['required_sections'] = value
    write_policy(tmp_path, policy)
    with pytest.raises(ValueError):
        status.section_status(tmp_path)


def group_fixture(root):
    policy = fixture(root, count=2)
    policy['groups'] = {'core': {'include_patterns': ['tests/test_*.py'], 'input_patterns': ['assets/*.json'], 'timeout_seconds': 30}}
    policy['certification']['required_groups'] = ['core']
    (root / 'tests/test_fixture_0.py').write_text('from runtime import shared\n', encoding='utf-8')
    (root / 'assets').mkdir()
    (root / 'assets/config.json').write_text('{}', encoding='utf-8')
    write_policy(root, policy)
    return policy


def save_index(root, value):
    (root / status.INDEX).write_text(json.dumps(value), encoding='utf-8')


def reseal_index(value):
    body = {k: v for k, v in value.items() if k != 'index_sha256'}
    return {**body, 'index_sha256': hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


@pytest.mark.parametrize('mutation', ['new-import', 'new-declared-asset', 'reserved-valid', 'parser', 'boolean-counter', 'empty-groups', 'corrupt-digest'])
def test_group_index_cannot_override_live_dependencies_or_validity(tmp_path, mutation):
    group_fixture(tmp_path)
    index = status.build_index(tmp_path)
    save_index(tmp_path, index)
    assert status.resolve_groups(tmp_path)[0]['valid'] is True
    if mutation == 'new-import':
        (tmp_path / 'runtime/shared.py').write_text('from .deep import VALUE\n', encoding='utf-8')
        (tmp_path / 'runtime/deep.py').write_text('VALUE = 1\n', encoding='utf-8')
    elif mutation == 'new-declared-asset':
        (tmp_path / 'assets/new.json').write_text('{}', encoding='utf-8')
    elif mutation == 'reserved-valid':
        index['groups'][0]['valid'] = True
    elif mutation == 'parser':
        index['dependency_parser']['source_sha256'] = '0' * 64
    elif mutation == 'boolean-counter':
        index['verified_file_count'] = True
    elif mutation == 'empty-groups':
        index['groups'] = []
    else:
        index['index_sha256'] = '0' * 64
    if mutation not in {'new-import', 'new-declared-asset'}:
        save_index(tmp_path, index if mutation == 'corrupt-digest' else reseal_index(index))
    if mutation in {'new-import', 'new-declared-asset'}:
        changed = status.resolve_groups(tmp_path)[0]
        assert changed['valid'] is False
        assert ('runtime/deep.py' if mutation == 'new-import' else 'assets/new.json') in changed['inputs']
    else:
        with pytest.raises(ValueError):
            status.resolve_groups(tmp_path)


def test_option_values_do_not_become_chunk_members(tmp_path):
    policy = fixture(tmp_path)
    command = policy['sections']['fixture']['command']
    command[3:3] = ['-q', '-p', 'no:cacheprovider', '-k', 'unit and not integration']
    write_policy(tmp_path, policy)
    section = owner.resolve_test_section(tmp_path, 'fixture')
    assert len(section['chunks']) == 6
    assert section['chunks'][0]['command'][3:9] == command[3:9]


def test_stale_index_fails_before_dependency_inventory(tmp_path, monkeypatch):
    group_fixture(tmp_path)
    save_index(tmp_path, {'schema_version': 'px.test-group-index/1.1'})
    monkeypatch.setattr(status, '_group_rows', lambda *_: pytest.fail('stale metadata triggered inventory'))
    with pytest.raises(ValueError, match='schema'):
        status.resolve_groups(tmp_path)


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '60'])
def test_capture_rejects_invalid_parent_deadline(tmp_path, value):
    with pytest.raises(ValueError):
        inputs.CapturedInputs(tmp_path, deadline=value)


def test_receipt_encoding_stops_at_aggregate_budget(monkeypatch):
    monkeypatch.setattr(receipts, 'LIMIT', 1024)
    with pytest.raises(ValueError, match='byte budget'):
        receipts.seal({'strings': ['x' * 256] * 5})


def test_receipt_chunks_reject_iterables_before_materialization():
    section, _, _ = subjects()
    class UnexpectedIteration:
        def __iter__(self):
            pytest.fail('malformed chunks were materialized')
    with pytest.raises(ValueError, match='actual list'):
        receipts.make_receipt('section', section, {**good_execution(), 'chunks': UnexpectedIteration()})


@pytest.mark.parametrize('kind', ['section', 'chunk', 'group'])
@pytest.mark.parametrize('indicator,value', [('supervision_status', 'cancelled'), ('supervision_status', 'owner_lost'),
    ('supervision_status', 'unknown'), ('supervision_status', None), ('process_tree_terminated', 'true'),
    ('process_tree_terminated', None), ('process_tree_terminated', 1), ('execution_started', False)])
def test_explicit_supervision_or_custody_contradiction_cannot_pass(kind, indicator, value):
    section, chunk, group = subjects()
    row = receipts.make_receipt(kind, {'section': section, 'chunk': chunk, 'group': group}[kind],
                               {**good_execution(), indicator: value}, section=section)
    assert row['passed'] is False and row['execution_valid'] is False
    assert receipts.validate(row, kind)


def chunk_summary():
    section, chunk, _ = subjects()
    row = receipts.make_receipt('chunk', chunk, good_execution(), section=section)
    row.update(reused=False, receipt_published=True, execution_started=True, process_tree_terminated=True)
    return {key: row[key] for key in receipts.CHUNK_SUMMARY}


@pytest.mark.parametrize('mutation', ['raw-stderr', 'unsafe-node', 'closure', 'unknown-closure', 'unknown-start', 'member-count', 'duration', 'exit', 'unpublished', 'supervision'])
def test_nested_chunk_schema_privacy_and_semantics_rejected_by_writer_and_reader(tmp_path, mutation):
    section, _, _ = subjects()
    summary = chunk_summary()
    valid = receipts.make_receipt('section', section, {**good_execution(), 'chunks': [summary]})
    target = receipts.write(tmp_path, 'section', valid)
    predecessor = target.read_bytes()
    if mutation == 'raw-stderr':
        summary['stderr'] = 'synthetic-secret'
    elif mutation == 'unsafe-node':
        summary['output_evidence']['failure_nodes'] = ['synthetic-secret']
    elif mutation == 'closure':
        summary['process_tree_terminated'] = False
    elif mutation == 'unknown-closure':
        summary['process_tree_terminated'] = None
    elif mutation == 'unknown-start':
        summary['execution_started'] = None
    elif mutation == 'member-count':
        summary['member_count'] = True
    elif mutation == 'duration':
        summary['duration_seconds'] = -1
    elif mutation == 'exit':
        summary['exit_code'] = 1
    elif mutation == 'unpublished':
        summary['receipt_published'] = False
    else:
        summary['output_evidence']['failure_nodes'] = ['supervision:cancelled']
    with pytest.raises(ValueError):
        receipts.make_receipt('section', section, {**good_execution(), 'chunks': [summary]})
    corrupted = receipts.seal({**{k: v for k, v in valid.items() if k != 'receipt_sha256'}, 'chunks': [summary]})
    with pytest.raises(ValueError):
        receipts.write(tmp_path, 'section', corrupted)
    assert target.read_bytes() == predecessor
    target.write_text(json.dumps(corrupted), encoding='utf-8')
    assert receipts.read(tmp_path, 'section', section['section']) == {}


@pytest.mark.parametrize('plugin_form', ['tuple', 'string', 'command', 'compact-command', 'runner'])
def test_local_pytest_plugin_mutation_invalidates_section_identity(tmp_path, plugin_form):
    policy = fixture(tmp_path, count=2)
    module = 'tests.pytest_guards' if plugin_form == 'runner' else 'tests.local_plugin'
    plugin = tmp_path / (module.replace('.', '/') + '.py')
    plugin.write_text('VALUE = 1\n', encoding='utf-8')
    if plugin_form in {'tuple', 'string'}:
        declaration = '(' + repr(module) + ',)' if plugin_form == 'tuple' else repr(module)
        (tmp_path / 'conftest.py').write_text('pytest_plugins = ' + declaration + '\n', encoding='utf-8')
    elif plugin_form == 'command':
        policy['sections']['fixture']['command'][3:3] = ['-p', module]
    elif plugin_form == 'compact-command':
        policy['sections']['fixture']['command'][3:3] = ['-p' + module]
    write_policy(tmp_path, policy)
    before = owner.resolve_test_section(tmp_path, 'fixture')
    assert plugin.relative_to(tmp_path).as_posix() in before['inputs']
    plugin.write_text('VALUE = 2\n', encoding='utf-8')
    after = owner.resolve_test_section(tmp_path, 'fixture')
    assert before['input_sha256'] != after['input_sha256']
    assert all(a['input_sha256'] != b['input_sha256'] for a, b in zip(before['chunks'], after['chunks']))


def test_option_value_equal_to_member_is_preserved_in_chunks(tmp_path):
    policy = fixture(tmp_path, count=2)
    policy['sections']['fixture']['command'][3:3] = ['-k', 'tests/test_fixture_0.py']
    write_policy(tmp_path, policy)
    for chunk in owner.resolve_test_section(tmp_path, 'fixture')['chunks']:
        assert chunk['command'][3:5] == ['-k', 'tests/test_fixture_0.py']


@pytest.mark.parametrize('kind', ['sections', 'groups'])
def test_required_denominator_cannot_omit_a_defined_owner(kind):
    with pytest.raises(ValueError, match='exact denominator'):
        status.required({'certification': {'required_' + kind: ['one']}}, kind, {'one': {}, 'two': {}})


def test_reused_summary_does_not_claim_new_execution_custody():
    section, _, _ = subjects()
    summary = {**chunk_summary(), 'reused': True, 'execution_started': None, 'process_tree_terminated': None}
    row = receipts.make_receipt('section', section, {**good_execution(), 'chunks': [summary]})
    assert receipts.validate(row, 'section')
