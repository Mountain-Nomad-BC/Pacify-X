"""Candidate shared input capture for group indexes and receipt currentness."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

from .verification_inputs import (
    CapturedInputs, POLICY, dependencies, description, environment, identity,
    resolve_test_section, strings,
)
from .test_runner import aggregate_test_disk_consumption_limit, validate_timeout
from .verification_receipts import read

INDEX = 'registry/test_group_index.json'
INDEX_SCHEMA = 'px.test-group-index/1.2'
PARSER_VERSION = 'px.static-local-import-closure/2'
STRUCTURAL_CONTROL_OUTPUTS = frozenset({
    '.engineering-bootstrap/test-evidence/.test-orchestration.lock',
})


def required(config, kind, definitions):
    certification = config.get('certification')
    if type(certification) is not dict:
        raise ValueError('certification definition is missing')
    result = strings(certification.get('required_' + kind), 'required ' + kind, maximum=128)
    if not result or len(result) != len(set(result)) or set(result) != set(definitions):
        raise ValueError('certification requires a nonempty unique exact denominator')
    for name in result:
        identity(name, kind)
    return result


def _definitions(config, kind):
    result = config.get(kind)
    if type(result) is not dict or not 1 <= len(result) <= 128:
        raise ValueError(kind + ' must be a nonempty bounded object')
    for name, value in result.items():
        identity(name, kind)
        if type(value) is not dict:
            raise ValueError('invalid ' + kind + ' definition')
    return result


def section_status(root):
    capture = CapturedInputs(root)
    capture.capture(POLICY)
    definitions = _definitions(capture.config, 'sections')
    names = required(capture.config, 'sections', definitions)
    rows = []
    for name in sorted(definitions):
        section = resolve_test_section(root, name, capture=capture)
        receipt = read(capture.root, 'section', name)
        passed = receipt.get('passed') is True
        fresh = (receipt.get('input_sha256') == section['input_sha256']
                 and receipt.get('command') == section['command']
                 and receipt.get('cwd') == section['cwd_relative']
                 and receipt.get('dependencies') == section['dependencies'])
        if section['chunks']:
            expected_chunks = [(c['chunk_id'], c['input_sha256'], c['members'], c['member_count']) for c in section['chunks']]
            actual_chunks = [(c.get('chunk_id'), c.get('input_sha256'), c.get('members'), c.get('member_count')) for c in receipt.get('chunks', [])]
            fresh = fresh and expected_chunks == actual_chunks
        elif receipt.get('chunks'):
            fresh = False
        rows.append({'section': name, 'dependencies': dependencies(definitions[name].get('dependencies', []), definitions, name),
                     'passed': passed, 'fresh': fresh, 'dependencies_current': False,
                     'current': False, 'input_sha256': section['input_sha256'],
                     'receipt': (capture.root / '.engineering-bootstrap/test-evidence/sections' / (name + '.json')).as_posix()})
    capture.verify()
    by_name = {row['section']: row for row in rows}
    pending = set(by_name)
    # Bounded topological evaluation; cycles remain explicitly noncurrent.
    while pending:
        ready = [name for name in pending if not (set(by_name[name]['dependencies']) & pending)]
        if not ready:
            break
        for name in ready:
            row = by_name[name]
            row['dependencies_current'] = all(by_name[d]['current'] for d in row['dependencies'])
            row['current'] = row['passed'] and row['fresh'] and row['dependencies_current']
            pending.remove(name)
    return {'schema_version': 'px.test-section-status/1.0',
            'valid': all(by_name[name]['current'] for name in names),
            'required_sections': names, 'sections': rows,
            'unresolved_dependency_cycle': sorted(pending)}


def structural_scan(capture, max_bytes=1_000_000):
    from .repository_scope import is_external_environment_relative

    excluded = {'.git', '.venv', '.vscode-test', 'python', 'node_modules', 'vendor',
                'dist', 'build', 'quarantine', '__pycache__'}
    pending, found = [''], []
    while pending:
        parent = pending.pop()
        if len(Path(parent).parts) > 128:
            raise ValueError('structural input path depth budget exhausted')
        for name in capture.listing(parent):
            relative = '/'.join(filter(None, [parent, name]))
            path = Path(relative)
            if (relative.casefold() in STRUCTURAL_CONTROL_OUTPUTS
                    or name.casefold() in excluded or name.casefold().startswith('.venv')
                    or is_external_environment_relative(path)
                    or tuple(p.casefold() for p in path.parts[:2]) == ('.px', 'preserved-skills')):
                continue
            info = capture.probe(relative)
            if info and stat.S_ISDIR(info[0]):
                pending.append(relative)
            elif info and path.suffix.casefold() in {'.py', '.js', '.jsx', '.ts', '.tsx'} and info[3] <= max_bytes:
                found.append(relative)
    return sorted(found)


def _group_rows(capture):
    capture.capture(POLICY)
    config = capture.config
    definitions = _definitions(config, 'groups')
    required(config, 'groups', definitions)
    all_tests = capture.match(['tests/test_*.py'])
    if not all_tests:
        raise ValueError('test group denominator is empty')
    assigned, groups = set(), []
    for name, definition in definitions.items():
        matches = set(capture.match(definition.get('include_patterns', [])))
        members = sorted(set(all_tests) & matches - assigned)
        if not members:
            raise ValueError('test group has no exclusively assigned members: ' + name)
        assigned.update(members)
        declared = capture.match(definition.get('input_patterns', []))
        base_inputs = capture.closure(sorted({POLICY, *members, *declared, *capture._module('tests.pytest_guards')}))
        scan_inputs = structural_scan(capture) if name == 'structural-adversarial' else []
        inputs = sorted({*base_inputs, *scan_inputs})
        for relative in inputs:
            capture.capture(relative)
        work = definition.get('disk_work_units', 1)
        groups.append({'group': name, 'description': description(definition.get('description', '')),
                       'members': members, 'member_count': len(members),
                       'inputs': inputs, 'base_inputs': base_inputs, 'scan_inputs': scan_inputs,
                       'input_sha256': capture.fingerprint(inputs),
                       'parallel_safe': definition.get('parallel_safe') is True,
                       'timeout_seconds': validate_timeout(definition.get('timeout_seconds')),
                       'disk_work_units': work, 'disk_consumption_limit_bytes': aggregate_test_disk_consumption_limit(work)})
    if set(all_tests) != assigned:
        raise ValueError('test groups leave current files unassigned')
    return groups, all_tests


def _topology(config):
    value = {'groups': config.get('groups', {}),
             'required_groups': config.get('certification', {}).get('required_groups', [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _parser_identity():
    # Parser implementation and Python AST version are identity-bearing inputs.
    from . import verification_inputs as source
    from .input_files import contained_file, read_file_image
    import time
    path = Path(source.__file__)
    path, info = contained_file(path.parent, path.name)
    payload = read_file_image(path, info, limit=1024**2, deadline=time.monotonic() + 10)
    return {'version': PARSER_VERSION, 'source_sha256': hashlib.sha256(payload).hexdigest(),
            'python': '.'.join(map(str, sys.version_info[:3]))}


def build_index(root):
    capture = CapturedInputs(root)
    groups, tests = _group_rows(capture)
    records = {path: {'sha256': capture.digests[path].hex(),
                      'dependencies': sorted(capture.edges[path]), 'index_state': 'verified'}
               for path in sorted(capture.digests) if path.endswith('.py')}
    capture.verify()
    body = {'schema_version': INDEX_SCHEMA, 'topology_sha256': _topology(capture.config),
            'dependency_parser': _parser_identity(), 'test_file_count': len(tests),
            'tracked_python_file_count': len(records), 'verified_file_count': len(records),
            'files': records, 'groups': groups}
    return {**body, 'index_sha256': hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def resolve_groups(root, *, capture=None, historical_index=False):
    from .input_files import contained_file, read_file_image
    from .json_io import decode_json_object

    owned = capture is None
    capture = capture if capture is not None else CapturedInputs(root)
    capture.capture(POLICY)
    definitions = _definitions(capture.config, 'groups')
    required(capture.config, 'groups', definitions)
    capture.capture(INDEX)
    path, info = contained_file(capture.root, INDEX)
    raw = read_file_image(path, info, limit=8 * 1024**2, deadline=capture.deadline)
    if hashlib.sha256(raw).digest() != capture.digests[INDEX]:
        raise ValueError('test group index changed during resolution')
    index = decode_json_object(raw, max_bytes=8 * 1024**2, max_depth=32, max_nodes=300000)
    expected = {'schema_version', 'topology_sha256', 'dependency_parser', 'test_file_count',
                'tracked_python_file_count', 'verified_file_count', 'files', 'groups', 'index_sha256'}
    if set(index) != expected or index['schema_version'] != INDEX_SCHEMA:
        raise ValueError('test group index schema is stale or malformed; explicit reconciliation required')
    supplied = index['index_sha256']
    body = {k: v for k, v in index.items() if k != 'index_sha256'}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    parser_current = index['dependency_parser'] == _parser_identity()
    if type(supplied) is not str or supplied != digest or (not parser_current and not historical_index):
        raise ValueError('test group index content or parser identity is invalid')
    topology_current = index['topology_sha256'] == _topology(capture.config)
    if not topology_current and not historical_index:
        raise ValueError('test group topology is stale; explicit reconciliation required')
    if type(index['groups']) is not list or len(index['groups']) != len(definitions):
        raise ValueError('test group index denominator is invalid')
    groups, tests = _group_rows(capture)
    membership_current = type(index['test_file_count']) is int and index['test_file_count'] == len(tests)
    if type(index['test_file_count']) is not int or (not membership_current and not historical_index):
        raise ValueError('test group membership is stale; explicit reconciliation required')
    if type(index['files']) is not dict or len(index['files']) > 20000:
        raise ValueError('test group index file records are invalid')
    for count in ('tracked_python_file_count', 'verified_file_count'):
        if type(index[count]) is not int or index[count] != len(index['files']):
            raise ValueError('test group index counters are invalid')
    current_files = {relative: {'sha256': capture.digests[relative].hex(),
                                'dependencies': sorted(capture.edges[relative]), 'index_state': 'verified'}
                     for relative in capture.digests if relative.endswith('.py')}
    for relative, record in index['files'].items():
        from .input_files import relative_source_path
        relative_source_path(relative)
        if type(record) is not dict or set(record) != {'sha256', 'dependencies', 'index_state'}:
            raise ValueError('test group index file record is malformed')
        if type(record['sha256']) is not str or len(record['sha256']) != 64 or any(c not in '0123456789abcdef' for c in record['sha256']):
            raise ValueError('test group index file digest is malformed')
        if record['index_state'] != 'verified':
            raise ValueError('test group index file is unverified')
        for dependency in strings(record['dependencies'], 'stored dependencies'):
            relative_source_path(dependency)
    file_metadata_current = current_files == index['files']
    result = []
    for current, stored in zip(groups, index['groups'], strict=True):
        if type(stored) is not dict or set(stored) != set(current):
            raise ValueError('test group index contains missing or reserved fields')
        if stored['group'] != current['group'] or (stored['members'] != current['members'] and not historical_index):
            raise ValueError('test group membership is stale; explicit reconciliation required')
        fresh = stored == current and file_metadata_current and parser_current and topology_current and membership_current
        # Build execution metadata solely from the freshly resolved definition.
        result.append({**current, 'schema_version': 'px.test-group/1.0', 'valid': fresh,
                       'index_current': fresh, 'scan_inventory_current': stored['scan_inputs'] == current['scan_inputs'],
                       'indexed_input_sha256': stored['input_sha256'],
                       'environment': environment(capture.config.get('environment', {})),
                       'command': [sys.executable, '-m', 'pytest', '-q', '--durations=20', '-p', 'no:cacheprovider', *current['members']]})
    if owned:
        capture.verify()
    return result


def group_status(root, *, historical_index=False):
    capture = CapturedInputs(root)
    groups = resolve_groups(root, capture=capture, historical_index=historical_index)
    names = required(capture.config, 'groups', capture.config['groups'])
    rows = []
    for group in groups:
        name = group['group']
        receipt = read(root, 'group', name)
        passed = receipt.get('passed') is True
        fresh = receipt.get('input_sha256') == group['input_sha256'] and receipt.get('member_count') == group['member_count']
        rows.append({'group': name, 'member_count': group['member_count'], 'parallel_safe': group['parallel_safe'],
                     'passed': passed, 'fresh': fresh, 'current': passed and fresh and group['index_current'],
                     'input_sha256': group['input_sha256'],
                     'receipt': (Path(root) / '.engineering-bootstrap/test-evidence/groups' / (name + '.json')).as_posix()})
    capture.verify()
    by_name = {row['group']: row for row in rows}
    return {'schema_version': 'px.test-group-status/1.0', 'valid': all(by_name[name]['current'] for name in names),
            'required_groups': names, 'groups': rows,
            'member_count': sum(row['member_count'] for row in rows)}
