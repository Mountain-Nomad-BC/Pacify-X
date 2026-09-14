"""Bounded section scheduling using the existing process and receipt owners."""
from collections import deque
import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
from pathlib import Path
import sys
from threading import Event
from time import monotonic
from uuid import uuid4


def run_section(root, section, name, started):
    from runtime.resource_lifecycle import ResourceManager
    from runtime.test_profiles import (
        read_section_chunk_receipt, require_processing_stage, section_chunk_receipt,
        section_receipt, section_status, write_section_chunk_receipt, write_section_receipt,
    )
    from runtime.test_runner import run_test_command, validate_timeout

    deadline = started + validate_timeout(section['timeout_seconds'])
    cancel = Event()
    require_processing_stage(root, 'governed_section')
    if section['dependencies']:
        status = section_status(root)
        by_name = {row['section']: row for row in status['sections']}
        if any(by_name.get(dependency, {}).get('current') is not True for dependency in section['dependencies']):
            raise ValueError('test section dependencies are not current')
    write_section_receipt(root, section_receipt(section, {
        'valid': False, 'exit_code': 1, 'timed_out': monotonic() >= deadline,
        'duration_seconds': monotonic() - started,
    }))
    environment = {**os.environ, **section['environment']}

    def expired():
        if monotonic() >= deadline:
            cancel.set()
        return cancel.is_set()

    def refused(reason='section deadline exhausted before child admission'):
        return {'valid': False, 'exit_code': 1, 'timed_out': monotonic() >= deadline,
                'duration_seconds': 0.0, 'stdout': '', 'stderr': reason,
                'process_tree_terminated': True, 'execution_started': False,
                'supervision_status': 'not_started', 'errors': [reason]}

    def execute(command, timeout, chunk_id=''):
        if expired():
            return refused()
        result = run_test_command(
            [sys.executable if value == 'python' else value for value in command],
            cwd=Path(section['cwd']), environment=environment,
            timeout_seconds=min(validate_timeout(timeout), deadline - monotonic()),
            deadline=deadline, cancel_event=cancel,
            resource_manager=ResourceManager(root / '.engineering-bootstrap/resource-lifecycle/ledger.json'),
            run_id=f'test-section-{name}-{chunk_id}-{uuid4().hex}',
            lane_id=f'section:{name}' + (':' + chunk_id if chunk_id else ''), manage_process_temp=True,
        )
        if expired():
            result = {**result, 'valid': False, 'timed_out': result.get('timed_out') is True or monotonic() >= deadline,
                      'exit_code': result.get('exit_code') if result.get('exit_code') else 1}
        return result

    original_error = None
    secondary_errors = []

    def failed(error):
        nonlocal original_error
        cancel.set()
        if original_error is None:
            original_error = error
        else:
            secondary_errors.append(type(error).__name__)

    def unknown(reason):
        return {'valid': False, 'exit_code': 1, 'timed_out': monotonic() >= deadline,
                'duration_seconds': 0.0, 'stdout': '', 'stderr': reason,
                'execution_started': None, 'process_tree_terminated': None}

    chunks = list(section.get('chunks', ()))
    ordered = []
    if chunks:
        rows = {}
        pending = deque()
        for chunk in chunks:
            previous = read_section_chunk_receipt(root, name, chunk['chunk_id'])
            if previous.get('passed') is True and previous.get('section') == name and previous.get('chunk_id') == chunk['chunk_id'] and previous.get('input_sha256') == chunk['input_sha256']:
                rows[chunk['chunk_id']] = {**previous, 'reused': True}
            else:
                pending.append(chunk)

        def retain(chunk, execution):
            if execution.get('execution_started') is not True or execution.get('process_tree_terminated') is not True:
                execution = {**execution, 'valid': False}
            receipt = None
            path = None
            try:
                receipt = section_chunk_receipt(section, chunk, execution)
                # Unstarted work remains in the complete section denominator.
                # Publishing one resource-owned receipt per refused chunk can
                # otherwise turn deadline settlement into an unbounded backlog.
                if execution.get('execution_started') is not False:
                    path = write_section_chunk_receipt(root, receipt)
            except BaseException as error:
                failed(error)
                # The original writer owns any prepared image. Do not retry the
                # failing publication or report its in-memory image as durable.
                if receipt is None:
                    execution = unknown('invalid chunk execution: ' + type(error).__name__)
                receipt = section_chunk_receipt(section, chunk, {**execution, 'valid': False})
            return {**receipt, 'reused': False, 'receipt_published': path is not None,
                    'receipt_path': path.as_posix() if path is not None else None,
                    'stdout': str(execution.get('stdout') or '')[-8000:],
                    'stderr': str(execution.get('stderr') or '')[-8000:],
                    'execution_started': execution.get('execution_started'),
                    'process_tree_terminated': execution.get('process_tree_terminated')}

        def settle(future, chunk):
            try:
                execution = future.result()
            except BaseException as error:
                failed(error)
                execution = unknown('chunk owner raised ' + type(error).__name__)
            rows[chunk['chunk_id']] = retain(chunk, execution)

        workers = section['max_parallel_chunks']
        if type(workers) is not int or not 1 <= workers <= 8:
            raise ValueError('invalid section worker bound')
        if pending:
            running = {}
            pool = None
            try:
                pool = ThreadPoolExecutor(max_workers=min(workers, len(pending)), thread_name_prefix='px-section-' + name)
                while pending or running:
                    while pending and len(running) < workers and not expired():
                        chunk = pending[0]
                        future = pool.submit(execute, chunk['command'], chunk['timeout_seconds'], chunk['chunk_id'])
                        pending.popleft()
                        running[future] = chunk
                    if not running:
                        break
                    done, _ = wait(running, timeout=None if expired() else max(0, deadline - monotonic()), return_when=FIRST_COMPLETED)
                    for future in done:
                        chunk = running.pop(future)
                        settle(future, chunk)
            except BaseException as error:
                failed(error)
            finally:
                # A worker interruption or failed publication closes admission.
                # Drain every submitted owner; cancellation is cooperative and
                # no background thread is abandoned as a completed owner.
                for future, chunk in list(running.items()):
                    settle(future, chunk)
                if pool is not None:
                    pool.shutdown(wait=True)
                while pending:
                    chunk = pending.popleft()
                    rows[chunk['chunk_id']] = retain(chunk, refused(
                        'section cancelled before child admission' if original_error is not None else
                        'section deadline exhausted before child admission'))
        # Reused receipts attest an earlier execution, not a new child owner.
        for row in rows.values():
            if row.get('reused'):
                row.update(receipt_published=True, execution_started=None, process_tree_terminated=None)
        ordered = [rows[chunk['chunk_id']] for chunk in chunks]
        timed_out = monotonic() >= deadline or any(row.get('timed_out') is True for row in ordered)
        passed = original_error is None and not timed_out and bool(ordered) and all(row.get('passed') is True for row in ordered)
        execution = {'valid': passed, 'exit_code': 0 if passed else 1, 'timed_out': timed_out,
                     'duration_seconds': round(monotonic() - started, 6),
                     'chunks': [{key: row.get(key) for key in (
                         'chunk_id', 'input_sha256', 'member_count', 'members', 'passed', 'timed_out',
                         'duration_seconds', 'output_evidence', 'receipt_sha256', 'reused',
                         'execution_started', 'process_tree_terminated', 'receipt_published',
                         'execution_valid', 'exit_code')} for row in ordered]}
    else:
        try:
            execution = execute(section['command'], section['timeout_seconds'])
        except BaseException as error:
            failed(error)
            execution = unknown('section owner raised ' + type(error).__name__)
        execution['duration_seconds'] = round(monotonic() - started, 6)
    # Receipt publication/closure is included in the observed result. If the
    # first final publication crosses the deadline, replace it with failure.
    if expired():
        execution.update(valid=False, exit_code=1, timed_out=execution.get('timed_out') is True or monotonic() >= deadline)
    try:
        receipt = section_receipt(section, execution)
    except BaseException as error:
        failed(error)
        execution = unknown('invalid section execution: ' + type(error).__name__)
        execution['duration_seconds'] = round(monotonic() - started, 6)
        receipt = section_receipt(section, execution)
    receipt_path = None
    try:
        receipt_path = write_section_receipt(root, receipt)
        if expired() and execution.get('valid') is True:
            execution.update(valid=False, exit_code=1, timed_out=True)
            receipt = section_receipt(section, execution)
            receipt_path = None
            receipt_path = write_section_receipt(root, receipt)
    except BaseException as error:
        failed(error)
        execution.update(valid=False, exit_code=1)
    execution['duration_seconds'] = round(monotonic() - started, 6)
    result = {**section, **execution, **({'chunk_results': ordered} if chunks else {}),
              'section_receipt': receipt, 'receipt_path': receipt_path.as_posix() if receipt_path else None,
              'receipt_published': receipt_path is not None, 'secondary_errors': secondary_errors,
              'deadline_exceeded_seconds': max(0, monotonic() - deadline),
              'deadline_scope': 'section resolution, admission, scheduling, execution and observed closure; OS calls and cleanup remain cooperative'}
    if original_error is not None:
        # Preserve the exact interruption/error while making settled outcomes
        # available to the caller even when durable publication is unavailable.
        original_error.section_result = result
        original_error.add_note('section terminal outcome: ' + json.dumps({
            'section': name, 'receipt_path': result['receipt_path'],
            'chunks': [{key: row.get(key) for key in ('chunk_id', 'passed', 'receipt_published', 'execution_started', 'process_tree_terminated')} for row in ordered],
            'secondary_errors': secondary_errors}, sort_keys=True))
        raise original_error
    return result
