"""Candidate strict verification receipts and owned atomic publication.

A self digest detects corruption; it does not authenticate an evidence producer.
The caller must still establish current inputs and execution authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from uuid import uuid4

from runtime.archive_io import reject_path_links
from runtime.file_lock import FileLock
from runtime.input_files import contained_file, directory_root, read_file_image, relative_source_path
from runtime.json_io import decode_json_object

LIMIT = 1024 * 1024
SCHEMAS = {
    'section': 'px.test-section-receipt/1.2',
    'chunk': 'px.test-section-chunk-receipt/1.2',
    'group': 'px.test-group-receipt/1.1',
}
COMMON = {'schema_version', 'input_sha256', 'passed', 'execution_valid', 'exit_code',
          'timed_out', 'duration_seconds', 'receipt_sha256'}
EXTRA = {
    'section': {'section', 'dependencies', 'command', 'cwd', 'chunks'},
    'chunk': {'section', 'chunk_id', 'members', 'member_count', 'output_evidence'},
    'group': {'group', 'member_count', 'output_evidence'},
}
CHUNK_SUMMARY = {'chunk_id', 'input_sha256', 'member_count', 'members', 'passed', 'timed_out',
                 'duration_seconds', 'output_evidence', 'receipt_sha256', 'reused',
                 'execution_started', 'process_tree_terminated', 'receipt_published',
                 'execution_valid', 'exit_code'}


def _identity(value):
    if type(value) is not str or not 1 <= len(value) <= 128 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in value):
        raise ValueError('invalid receipt identity')
    return value


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 604800


def _strings(value, *, maximum=20000):
    return type(value) is list and len(value) <= maximum and all(type(v) is str and 0 < len(v) <= 4096 and '\0' not in v for v in value)


def _encode(body):
    # Check the object graph before JSON conversion, then stop encoding at the
    # retained byte ceiling. Never build an oversized whole JSON image first.
    pending = [(body, 0)]
    nodes = 0
    text_bytes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > 100000 or depth > 32:
            raise ValueError('receipt structure exceeds its budget')
        if type(value) is dict:
            if len(value) > 20000 or any(type(key) is not str for key in value):
                raise ValueError('invalid receipt object')
            if len(pending) + 2 * len(value) + nodes > 100000:
                raise ValueError('receipt structure exceeds its budget')
            pending.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif type(value) is list:
            if len(value) > 20000:
                raise ValueError('receipt sequence exceeds its budget')
            if len(pending) + len(value) + nodes > 100000:
                raise ValueError('receipt structure exceeds its budget')
            pending.extend((item, depth + 1) for item in value)
        elif type(value) is str:
            if len(value) > 65536:
                raise ValueError('receipt string exceeds its budget')
            text_bytes += len(value.encode('utf-8'))
            if text_bytes > LIMIT:
                raise ValueError('receipt exceeds byte budget')
        elif value is None or type(value) is bool:
            pass
        elif type(value) is int:
            if value.bit_length() > 64:
                raise ValueError('receipt integer exceeds its budget')
        elif type(value) is float:
            if not math.isfinite(value):
                raise ValueError('receipt number must be finite')
        else:
            raise ValueError('receipt contains an unsupported value')
    result = bytearray()
    for fragment in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(body):
        encoded = fragment.encode('utf-8')
        if len(result) + len(encoded) > LIMIT:
            raise ValueError('receipt exceeds byte budget')
        result.extend(encoded)
    return bytes(result)


def seal(body):
    return {**body, 'receipt_sha256': hashlib.sha256(_encode(body)).hexdigest()}


def execution_fields(execution):
    code = execution.get('exit_code', execution.get('returncode'))
    duration = execution.get('duration_seconds')
    if code is not None and (type(code) is not int or not -(2**31) <= code <= 2**32 - 1):
        raise ValueError('process exit must be a bounded integer')
    # A malformed outcome is a failed attempt, not an implicit successful one.
    typed = (type(code) is int and -(2**31) <= code <= 2**32 - 1
             and type(execution.get('timed_out')) is bool and _finite(duration))
    valid = typed and execution.get('valid') is True
    if ('process_tree_terminated' in execution and execution['process_tree_terminated'] is not True
            or 'execution_started' in execution and execution['execution_started'] is not True
            or 'supervision_status' in execution and execution['supervision_status'] != 'exited'):
        valid = False
    return {
        'execution_valid': valid,
        'passed': valid and code == 0 and execution['timed_out'] is False,
        'exit_code': code if type(code) is int and -(2**31) <= code <= 2**32 - 1 else None,
        'timed_out': execution.get('timed_out') is True,
        'duration_seconds': duration if _finite(duration) else None,
    }


def _valid_chunk_summary(row):
    from runtime.test_profiles import _valid_bounded_output_evidence

    if type(row) is not dict or set(row) != CHUNK_SUMMARY:
        return False
    _identity(row['chunk_id'])
    if not _hash(row['input_sha256']) or not _hash(row['receipt_sha256']):
        return False
    if any(type(row[key]) is not bool for key in ('passed', 'timed_out', 'reused', 'receipt_published', 'execution_valid')):
        return False
    if any(row[key] is not None and type(row[key]) is not bool for key in ('execution_started', 'process_tree_terminated')):
        return False
    count, members = row['member_count'], row['members']
    if type(count) is not int or not 1 <= count <= 20000 or not _strings(members) or len(members) != count or len(set(members)) != count:
        return False
    for member in members:
        relative_source_path(member)
    if not _valid_bounded_output_evidence(row['output_evidence']):
        return False
    code, duration = row['exit_code'], row['duration_seconds']
    if code is not None and (type(code) is not int or not -(2**31) <= code <= 2**32 - 1):
        return False
    if duration is not None and not _finite(duration):
        return False
    if row['execution_valid'] and (code is None or duration is None):
        return False
    expected = row['execution_valid'] and code == 0 and not row['timed_out'] and _finite(duration)
    if row['passed'] is not expected:
        return False
    if row['passed'] and (not row['receipt_published'] or row['process_tree_terminated'] is False
                          or row['execution_started'] is False or _failure_indicators(row['output_evidence'])):
        return False
    if row['passed'] and not row['reused'] and (row['execution_started'] is not True or row['process_tree_terminated'] is not True):
        return False
    return not row['reused'] or row['receipt_published']


def _failure_indicators(evidence):
    return any(node.startswith(('supervision:', 'unattributed-process-exit:')) for node in evidence['failure_nodes'])


def make_receipt(kind, subject, execution, *, section=None):
    from runtime.test_profiles import _bounded_output_evidence

    body = {'schema_version': SCHEMAS[kind], 'input_sha256': subject['input_sha256'],
            **execution_fields(execution)}
    output_execution = {**execution, 'exit_code': body['exit_code']}
    if kind == 'section':
        chunks = execution.get('chunks', [])
        if type(chunks) is not list or len(chunks) > 20000:
            raise ValueError('section chunks must be a bounded actual list')
        body.update(section=subject['section'], dependencies=subject['dependencies'],
                    command=subject['command'], cwd=subject.get('cwd_relative', '.'),
                    chunks=chunks)
    elif kind == 'chunk':
        body.update(section=section['section'], chunk_id=subject['chunk_id'],
                    members=subject['members'], member_count=subject['member_count'],
                    output_evidence=_bounded_output_evidence(output_execution))
    else:
        body.update(group=subject['group'], member_count=subject['member_count'],
                    output_evidence=_bounded_output_evidence(output_execution))
    if subject.get('valid') is False:
        body.update(execution_valid=False, passed=False)
    receipt = seal(body)
    if not validate(receipt, kind):
        raise ValueError('invalid receipt subject or execution structure')
    return receipt


def validate(value, kind, *, name=None, chunk_id=None):
    from runtime.test_profiles import _valid_bounded_output_evidence

    try:
        if type(value) is not dict or set(value) != COMMON | EXTRA[kind] or value['schema_version'] != SCHEMAS[kind]:
            return False
        if not _hash(value['input_sha256']) or not _hash(value['receipt_sha256']):
            return False
        subject = _identity(value['group' if kind == 'group' else 'section'])
        if name is not None and subject != name:
            return False
        if any(type(value[key]) is not bool for key in ('passed', 'execution_valid', 'timed_out')):
            return False
        code = value['exit_code']
        duration = value['duration_seconds']
        if code is not None and (type(code) is not int or not -(2**31) <= code <= 2**32 - 1):
            return False
        if duration is not None and not _finite(duration):
            return False
        expected_pass = (value['execution_valid'] and type(code) is int and code == 0
                         and value['timed_out'] is False and _finite(duration))
        if value['passed'] is not expected_pass or value['execution_valid'] and (code is None or duration is None):
            return False
        if kind == 'section':
            deps = value['dependencies']
            if not _strings(deps, maximum=128) or len(set(deps)) != len(deps):
                return False
            for dep in deps:
                _identity(dep)
            if not _strings(value['command']) or not value['command']:
                return False
            if value['cwd'] != '.':
                relative_source_path(value['cwd'])
            if type(value['chunks']) is not list or len(value['chunks']) > 20000:
                return False
            if value['chunks']:
                seen = set()
                for row in value['chunks']:
                    if not _valid_chunk_summary(row) or row['chunk_id'] in seen:
                        return False
                    seen.add(row['chunk_id'])
                    if not _hash(row.get('input_sha256')) or not _hash(row.get('receipt_sha256')):
                        return False
                    if type(row.get('passed')) is not bool or type(row.get('timed_out')) is not bool:
                        return False
                    if value['passed'] and (row['passed'] is not True or row['timed_out'] is not False):
                        return False
        else:
            count = value['member_count']
            if type(count) is not int or not 1 <= count <= 20000 or not _valid_bounded_output_evidence(value['output_evidence']):
                return False
            if value['passed'] and _failure_indicators(value['output_evidence']):
                return False
            if kind == 'chunk':
                actual_chunk = _identity(value['chunk_id'])
                if chunk_id is not None and actual_chunk != chunk_id:
                    return False
                members = value['members']
                if not _strings(members) or len(members) != count or len(set(members)) != count:
                    return False
                for member in members:
                    relative_source_path(member)
        body = {key: item for key, item in value.items() if key != 'receipt_sha256'}
        return hmac.compare_digest(value['receipt_sha256'], hashlib.sha256(_encode(body)).hexdigest())
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return False


def receipt_path(root, kind, name, chunk_id=None):
    root = directory_root(root)
    name = _identity(name)
    base = root / '.engineering-bootstrap/test-evidence'
    if kind == 'chunk':
        target = base / 'section-chunks' / name / (_identity(chunk_id) + '.json')
    else:
        target = base / ('sections' if kind == 'section' else 'groups') / (name + '.json')
    reject_path_links(target)
    return target


def read(root, kind, name, chunk_id=None):
    try:
        root = directory_root(root)
        target = receipt_path(root, kind, name, chunk_id)
        path, info = contained_file(directory_root(root), target.relative_to(root).as_posix())
        raw = read_file_image(path, info, limit=LIMIT, deadline=time.monotonic() + 10)
        value = decode_json_object(raw, max_bytes=LIMIT, max_depth=32, max_nodes=100000)
        return value if validate(value, kind, name=name, chunk_id=chunk_id) else {}
    except (OSError, TypeError, ValueError):
        return {}


def write(root, kind, receipt):
    from runtime.resource_lifecycle import ResourceManager, RunState

    if not validate(receipt, kind):
        raise ValueError('refusing malformed verification receipt')
    root = directory_root(root)
    target = receipt_path(root, kind, receipt['group' if kind == 'group' else 'section'], receipt.get('chunk_id'))
    payload = _encode(receipt) + b'\n'
    if len(payload) > LIMIT:
        raise ValueError('receipt image exceeds byte budget')
    target.parent.mkdir(parents=True, exist_ok=True)
    reject_path_links(target)
    manager = ResourceManager(root / '.engineering-bootstrap/resource-lifecycle/ledger.json')
    run_id = 'receipt-' + uuid4().hex
    temporary = target.with_name('.' + target.name + '.' + uuid4().hex + '.tmp')
    # Persist the exact owner before creating the prepared image. A failed
    # publication retains it for recovery instead of overwriting another writer.
    record = manager.register_path(temporary, allowed_cleanup_root=target.parent,
                                   project_id='verification', run_id=run_id,
                                   lane_id='verification-receipt', creator=__name__,
                                   retention_required=True)
    published = False
    try:
        with FileLock(target.with_suffix('.json.lock'), timeout_seconds=10):
            reject_path_links(target)
            with temporary.open('xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            reject_path_links(target)
            os.replace(temporary, target)
            published = True
            if os.name != 'nt':
                descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        manager.update(record.resource_id, retention_required=False)
        closed = manager.reclaim_ephemeral_path(record.resource_id, reason='receipt_image_published')
        if closed.resources_reclaimed != 1 or closed.errors:
            raise RuntimeError('receipt published but prepared-image custody did not close')
    except BaseException as error:
        error.add_note('receipt publication completed=' + str(published))
        try:
            manager.mark_run_ended(run_id, RunState.FAILED, retain_reason='receipt_publication_requires_reconciliation')
        except BaseException as secondary:
            error.add_note('receipt owner reconciliation raised ' + type(secondary).__name__)
        raise
    return target
