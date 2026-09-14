"""Prepared bounded scheduler counterexamples with fake chunks, not release work."""
from contextlib import redirect_stdout
from io import StringIO
import json
import time
from threading import Event

import pytest

from runtime import cli, test_profiles, test_runner, resource_lifecycle


def run_fake_section(root, monkeypatch, *, chunked=True, resolution_delay=0.0):
    members = [f"tests/test_{index}.py" for index in range(4)]
    chunks = [{"chunk_id": f"chunk-{index + 1:02d}", "input_sha256": str(index + 1) * 64,
               "member_count": 1, "members": [name], "inputs": [name],
               "command": ["python", "-c", "fake-chunk-" + str(index)], "timeout_seconds": 5}
              for index, name in enumerate(members)] if chunked else []
    section = {"schema_version": "px.test-section/1.0", "valid": True, "section": "fixture",
               "description": "owned scheduler algorithm fixture", "dependencies": [],
               "inputs": ["registry/test_profiles.json"], "input_sha256": "f" * 64,
               "command": ["python", "-c", "fake-single"], "cwd": str(root), "cwd_relative": ".",
               "timeout_seconds": 0.01, "chunks": chunks, "max_parallel_chunks": 1, "environment": {}}
    executed = []

    def resolve(*args, **kwargs):
        time.sleep(resolution_delay)
        return section

    def execute(command, **kwargs):
        executed.append(command[-1])
        time.sleep(0.03)
        return {"valid": True, "exit_code": 0, "timed_out": False,
                "duration_seconds": 0.03, "stdout": "fixture completed\n", "stderr": "",
                "process_tree_terminated": True}

    monkeypatch.setattr(cli, "_claim_test_orchestration_single_flight", lambda *a, **k: (None, None))
    monkeypatch.setattr(test_profiles, "resolve_test_section", resolve)
    monkeypatch.setattr(test_profiles, "section_status", lambda *a, **k: {"sections": []})
    monkeypatch.setattr(test_profiles, "require_processing_stage", lambda *a, **k: {"stage_allowed": True})
    monkeypatch.setattr(test_profiles, "read_section_chunk_receipt", lambda *a, **k: {})
    monkeypatch.setattr(test_profiles, "write_section_chunk_receipt", lambda _root, receipt: root / (receipt["chunk_id"] + ".json"))
    monkeypatch.setattr(test_profiles, "write_section_receipt", lambda *a, **k: root / "section.json")
    monkeypatch.setattr(test_runner, "run_test_command", execute)
    monkeypatch.setattr(resource_lifecycle, "ResourceManager", lambda *a, **k: object())
    output = StringIO()
    with redirect_stdout(output):
        code = cli.main(["--root", str(root), "test-section", "run", "fixture"])
    return code, json.loads(output.getvalue()), executed


def test_chunked_section_cannot_pass_after_total_budget_expires(tmp_path, monkeypatch):
    code, result, _ = run_fake_section(tmp_path, monkeypatch)
    assert code != 0 and result["valid"] is False
    assert result["timed_out"] is True


def test_expired_section_does_not_start_all_queued_chunks(tmp_path, monkeypatch):
    _, _, executed = run_fake_section(tmp_path, monkeypatch)
    assert len(executed) <= 1, executed


def test_section_budget_includes_resolution_before_scheduling(tmp_path, monkeypatch):
    code, result, executed = run_fake_section(tmp_path, monkeypatch, resolution_delay=0.03)
    assert code != 0 and result["valid"] is False
    assert not executed


def test_nonchunked_section_also_rejects_late_success(tmp_path, monkeypatch):
    code, result, _ = run_fake_section(tmp_path, monkeypatch, chunked=False)
    assert code != 0 and result["valid"] is False
    assert result["timed_out"] is True


@pytest.mark.parametrize('failure', ['keyboard', 'system-exit', 'publication', 'all-publication', 'wait-interruption', 'malformed-execution'])
def test_interruption_settles_siblings_and_retains_complete_terminal_denominator(tmp_path, monkeypatch, failure):
    from runtime import section_scheduler as scheduler
    chunks = [{'chunk_id': f'chunk-{i}', 'input_sha256': str(i + 1) * 64,
               'members': [f'tests/test_{i}.py'], 'member_count': 1,
               'command': ['python', '-c', str(i)], 'timeout_seconds': 10} for i in range(4)]
    section = {'section': 'fixture', 'input_sha256': 'f' * 64, 'dependencies': [],
               'command': ['python', '-c', 'fixture'], 'cwd': str(tmp_path), 'cwd_relative': '.',
               'timeout_seconds': 10, 'environment': {}, 'max_parallel_chunks': 2, 'chunks': chunks}
    good = {'valid': True, 'exit_code': 0, 'timed_out': False, 'duration_seconds': 0.01,
            'stdout': '', 'stderr': '', 'execution_started': True, 'process_tree_terminated': True}
    reused = test_profiles.section_chunk_receipt(section, chunks[0], good)
    started, closed = Event(), Event()
    executed, published, attempts = [], [], []
    original = (KeyboardInterrupt('injected owner interruption') if failure in {'keyboard', 'wait-interruption'} else
                SystemExit('injected owner exit') if failure == 'system-exit' else OSError('injected publication failure'))

    def execute(command, **kwargs):
        index = int(command[-1])
        executed.append(index)
        if index == 1:
            assert started.wait(2)
            if failure in {'keyboard', 'system-exit'}:
                raise original
            return {**good, 'exit_code': False} if failure == 'malformed-execution' else dict(good)
        assert index == 2, 'cancelled queued chunk was admitted'
        started.set()
        assert kwargs['cancel_event'].wait(2), 'sibling was never cancelled'
        closed.set()
        return {**good, 'valid': False, 'supervision_status': 'cancelled'}

    def write_chunk(_root, receipt):
        attempts.append(receipt['chunk_id'])
        if failure in {'publication', 'all-publication'}:
            raise original
        return tmp_path / (receipt['chunk_id'] + '.json')

    def write_section(_root, receipt):
        if failure == 'all-publication' and published:
            raise original
        published.append(receipt)
        return tmp_path / 'section.json'

    monkeypatch.setattr(test_profiles, 'require_processing_stage', lambda *a, **k: {})
    monkeypatch.setattr(test_profiles, 'read_section_chunk_receipt', lambda _r, _s, c: reused if c == 'chunk-0' else {})
    monkeypatch.setattr(test_profiles, 'write_section_chunk_receipt', write_chunk)
    monkeypatch.setattr(test_profiles, 'write_section_receipt', write_section)
    monkeypatch.setattr(resource_lifecycle, 'ResourceManager', lambda *_: object())
    monkeypatch.setattr(test_runner, 'run_test_command', execute)
    if failure == 'wait-interruption':
        def interrupt_wait(*a, **k):
            raise original
        monkeypatch.setattr(scheduler, 'wait', interrupt_wait)
    with pytest.raises(BaseException) as caught:
        scheduler.run_section(tmp_path, section, 'fixture', time.monotonic())
    if failure == 'malformed-execution':
        assert isinstance(caught.value, ValueError)
    else:
        assert caught.value is original
    assert closed.is_set() and sorted(executed) == [1, 2]
    result = caught.value.section_result
    assert result['valid'] is False
    assert result['timed_out'] is False, 'cancellation before deadline was mislabeled as timeout'
    rows = result['chunk_results']
    assert [r['chunk_id'] for r in rows] == [c['chunk_id'] for c in chunks]
    assert rows[0]['reused'] is True
    assert rows[3]['execution_started'] is False and rows[3]['passed'] is False
    assert len(attempts) == len(set(attempts)), 'publication failure retried'
    if failure == 'all-publication':
        assert result['receipt_published'] is False
    else:
        assert published[-1]['passed'] is False and len(published[-1]['chunks']) == 4
    if failure in {'keyboard', 'system-exit', 'malformed-execution'}:
        assert rows[1]['execution_started'] is None and rows[1]['process_tree_terminated'] is None


def test_malformed_nonchunk_execution_retains_original_error_and_failed_receipt(tmp_path, monkeypatch):
    from runtime import section_scheduler as scheduler
    section = {'section': 'fixture', 'input_sha256': 'f' * 64, 'dependencies': [],
               'command': ['python', '-c', 'fixture'], 'cwd': str(tmp_path), 'cwd_relative': '.',
               'timeout_seconds': 10, 'environment': {}, 'chunks': []}
    published = []
    def publish(_root, receipt):
        published.append(receipt)
        return tmp_path / 'section.json'
    monkeypatch.setattr(test_profiles, 'require_processing_stage', lambda *a, **k: {})
    monkeypatch.setattr(test_profiles, 'write_section_receipt', publish)
    monkeypatch.setattr(resource_lifecycle, 'ResourceManager', lambda *_: object())
    monkeypatch.setattr(test_runner, 'run_test_command', lambda *a, **k: {
        'valid': True, 'exit_code': False, 'timed_out': False, 'duration_seconds': 0.01})
    with pytest.raises(ValueError, match='process exit') as caught:
        scheduler.run_section(tmp_path, section, 'fixture', time.monotonic())
    assert caught.value.section_result['valid'] is False
    assert caught.value.section_result['timed_out'] is False
    assert len(published) == 2 and published[-1]['passed'] is False


@pytest.mark.parametrize('count', [85, 250])
def test_expired_queue_has_complete_aggregate_without_per_chunk_publication(tmp_path, monkeypatch, count):
    from runtime import section_scheduler as scheduler
    chunks = [{'chunk_id': f'chunk-{i:03d}', 'input_sha256': f'{i:064x}',
               'members': [f'tests/test_{i}.py'], 'member_count': 1,
               'command': ['python', '-c', 'never start'], 'timeout_seconds': 10}
              for i in range(count)]
    section = {'section': 'fixture', 'input_sha256': 'f' * 64, 'dependencies': [],
               'command': ['python', '-c', 'fixture'], 'cwd': str(tmp_path), 'cwd_relative': '.',
               'timeout_seconds': 1, 'environment': {}, 'max_parallel_chunks': 1, 'chunks': chunks}
    published_chunks, published_sections = [], []
    monkeypatch.setattr(scheduler, 'monotonic', lambda: 10.0)
    monkeypatch.setattr(test_profiles, 'require_processing_stage', lambda *a, **k: {})
    monkeypatch.setattr(test_profiles, 'read_section_chunk_receipt', lambda *a, **k: {})
    def write_chunk(_root, receipt):
        published_chunks.append(receipt)
        return tmp_path / (receipt['chunk_id'] + '.json')
    def write_section(_root, receipt):
        published_sections.append(receipt)
        return tmp_path / 'section.json'
    monkeypatch.setattr(test_profiles, 'write_section_chunk_receipt', write_chunk)
    monkeypatch.setattr(test_profiles, 'write_section_receipt', write_section)
    monkeypatch.setattr(test_runner, 'run_test_command', lambda *a, **k: pytest.fail('expired work started'))
    result = scheduler.run_section(tmp_path, section, 'fixture', 0.0)
    assert result['valid'] is False and result['timed_out'] is True
    assert result['receipt_published'] is True
    assert published_chunks == [], 'unstarted chunks caused a post-deadline publication backlog'
    assert len(published_sections) == 2
    rows = published_sections[-1]['chunks']
    assert [row['chunk_id'] for row in rows] == [row['chunk_id'] for row in chunks]
    assert all(row['execution_started'] is False and row['passed'] is False
               and row['receipt_published'] is False for row in rows)
