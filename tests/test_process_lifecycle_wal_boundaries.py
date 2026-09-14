"""Causal counterexamples for coordinated transaction candidates, fixtures only."""
import hashlib
import json
from pathlib import Path

import pytest

from runtime import wal_transaction as wal
from runtime.json_io import bounded_canonical_json_bytes


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('entry', ['commit', 'boundaries'])
def test_artifact_iterator_stops_at_limit_plus_one(tmp_path, monkeypatch, entry):
    monkeypatch.setattr(wal, 'MAX_ARTIFACTS', 2)
    visits = []
    def values():
        for index in range(100):
            visits.append(index)
            if index > 2:
                pytest.fail('artifact iterator consumed beyond oversize probe')
            yield wal.TextArtifact('state', tmp_path / f'{index}.txt', 'value')
    with pytest.raises(ValueError, match='artifacts'):
        if entry == 'commit':
            wal.JsonWal(tmp_path / 'wal', tmp_path).commit(values())
        else:
            wal.planned_write_boundaries(values())
    assert visits == [0, 1, 2]
    assert not (tmp_path / 'wal').exists()


def test_large_json_string_rejected_before_encoder(tmp_path, monkeypatch):
    monkeypatch.setattr(wal, 'MAX_TRANSACTION_BYTES', 16)
    monkeypatch.setattr(json.JSONEncoder, 'iterencode', lambda *a, **k: pytest.fail('oversized input reached encoder'))
    with pytest.raises(ValueError):
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit([wal.JsonArtifact('state', tmp_path / 'x.json', {'x': 'y' * 40})])
    assert not (tmp_path / 'x.json').exists()


def test_before_plus_after_limit_checked_before_target_open(tmp_path, monkeypatch):
    target = tmp_path / 'x.txt'
    target.write_bytes(b'x' * 25)
    monkeypatch.setattr(wal, 'MAX_TRANSACTION_BYTES', 32)
    original = Path.open
    opened = []
    def observe(path, *a, **k):
        if path == target:
            opened.append(path)
        return original(path, *a, **k)
    monkeypatch.setattr(Path, 'open', observe)
    with pytest.raises(wal.WalIntegrityError, match='byte budget'):
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit([wal.TextArtifact('state', target, 'a' * 8)])
    assert not opened
    assert target.read_bytes() == b'x' * 25


def test_exact_raw_before_image_rejects_logically_equal_new_bytes(tmp_path):
    target = tmp_path / 'x.json'
    original = b'{"a":1}'
    target.write_bytes(b'{ "a": 1 }')
    with pytest.raises(wal.WalConflictError) as caught:
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit(
            [wal.JsonArtifact('state', target, {'a': 2})], expected_before={'x.json': digest(original)})
    assert target.read_bytes() == b'{ "a": 1 }'
    assert caught.value.wal_outcome['intent_accepted'] is False


@pytest.mark.parametrize('expectations', [{}, {'other.json': None}])
def test_before_expectations_must_cover_exact_targets(tmp_path, expectations):
    with pytest.raises(ValueError, match='exact target set'):
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit(
            [wal.JsonArtifact('state', tmp_path / 'x.json', {})], expected_before=expectations)
    assert not (tmp_path / 'wal').exists()


def test_absent_target_race_refuses_stale_intent(tmp_path):
    target = tmp_path / 'x.json'
    def race(point):
        if point == 'intent:before_acceptance':
            target.write_bytes(b'{"racer":true}')
    with pytest.raises(wal.WalConflictError):
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit(
            [wal.JsonArtifact('state', target, {})], expected_before={'x.json': None}, fault_injector=race)
    assert target.read_bytes() == b'{"racer":true}'


def test_changed_read_dependency_refuses_new_target(tmp_path):
    dependency = tmp_path / 'evidence.txt'
    dependency.write_bytes(b'old')
    def race(point):
        if point == 'intent:before_acceptance':
            dependency.write_bytes(b'new')
    with pytest.raises(wal.WalConflictError, match='read dependency'):
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit(
            [wal.JsonArtifact('state', tmp_path / 'x.json', {})], expected_before={'x.json': None},
            expected_inputs={'evidence.txt': digest(b'old')}, fault_injector=race)
    assert not (tmp_path / 'x.json').exists()


def test_rejected_new_transaction_still_reports_completed_old_recovery(tmp_path):
    target = tmp_path / 'x.json'
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    def interrupt(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('injected preparation interruption')
    with pytest.raises(RuntimeError):
        owner.commit([wal.JsonArtifact('state', target, {'v': 1})], transaction_id='first', fault_injector=interrupt)
    with pytest.raises(ValueError, match='already been used') as caught:
        owner.commit([wal.JsonArtifact('state', target, {'v': 2})], transaction_id='first')
    assert json.loads(target.read_bytes()) == {'v': 1}
    assert caught.value.wal_outcome['recovery']['completed'] == ['first']
    assert caught.value.wal_outcome['intent_accepted'] is False


def test_inspection_detects_target_change_even_when_journal_is_unchanged(tmp_path, monkeypatch):
    target = tmp_path / 'x.json'
    target.write_bytes(b'{"v":0}')
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    def interrupt(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('prepared')
    with pytest.raises(RuntimeError):
        owner.commit([wal.JsonArtifact('state', target, {'v': 1})], transaction_id='first', fault_injector=interrupt)
    original = owner._inspect_transaction
    def change(transaction):
        result = original(transaction)
        target.write_bytes(b'{"v":1}\n')
        return result
    monkeypatch.setattr(owner, '_inspect_transaction', change)
    with pytest.raises(wal.WalIntegrityError, match='changed during read-only'):
        owner.inspect()


def test_canonical_wire_semantics_and_complete_byte_ceiling():
    value = {'z': ('\u03bb', 2), 'a': {'bool': True}}
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
    assert bounded_canonical_json_bytes(value, max_bytes=len(expected)) == expected
    with pytest.raises(ValueError, match='byte budget'):
        bounded_canonical_json_bytes(value, max_bytes=len(expected) - 1)


def test_unknown_recovery_chronology_preserves_all_pending_authority(tmp_path):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    (tmp_path / 'wal/transactions/a-unprepared').mkdir(parents=True)
    broken = tmp_path / 'wal/transactions/z-corrupt'
    broken.mkdir()
    (broken / 'manifest.json').write_bytes(b'{broken')
    with pytest.raises(wal.WalIntegrityError) as caught:
        owner.commit([wal.JsonArtifact('state', tmp_path / 'new.json', {})])
    recovery = caught.value.wal_outcome['recovery']
    assert recovery['valid'] is False
    assert recovery['rolled_back'] == []
    assert recovery['active_transaction'] is None
    assert recovery['active_phase'] == 'inventory'
    assert (tmp_path / 'wal/transactions/a-unprepared').is_dir()
    assert broken.is_dir()
    assert not (tmp_path / 'new.json').exists()


def test_recovery_target_publication_failure_retains_actual_effects(tmp_path, monkeypatch):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    first, second = tmp_path / 'a.json', tmp_path / 'b.json'
    def prepare(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('prepared')
    with pytest.raises(RuntimeError):
        owner.commit([wal.JsonArtifact('state', first, {'v': 1}),
                      wal.JsonArtifact('state', second, {'v': 2})],
                     transaction_id='partial', fault_injector=prepare)
    apply = owner._apply
    causal = RuntimeError('first target published; second target not started')
    def fail(point):
        if point == 'target:0:published':
            raise causal
    def interrupted(transaction, manifest, fault_injector=None):
        return apply(transaction, manifest, fail)
    monkeypatch.setattr(owner, '_apply', interrupted)
    with pytest.raises(RuntimeError) as caught:
        owner.recover()
    assert caught.value is causal
    assert json.loads(first.read_bytes()) == {'v': 1}
    assert not second.exists()
    assert causal.wal_recovery['active_transaction'] == 'partial'
    assert causal.wal_recovery['active_phase'] == 'applying'
    assert causal.wal_recovery['target_effects_may_have_occurred'] is True
    assert causal.wal_recovery['completed'] == []
    monkeypatch.setattr(owner, '_apply', apply)
    assert owner.recover()['completed'] == ['partial']
    assert json.loads(second.read_bytes()) == {'v': 2}


def test_diagnostic_failures_preserve_original_exception(tmp_path):
    class HostileError(RuntimeError):
        def __setattr__(self, name, value):
            raise RuntimeError('cannot attach attribute')

        def add_note(self, note):
            raise RuntimeError('cannot attach note')
    cause = HostileError('original')
    def reject(point):
        raise cause
    with pytest.raises(HostileError) as caught:
        wal.JsonWal(tmp_path / 'wal', tmp_path).commit(
            [wal.JsonArtifact('state', tmp_path / 'x.json', {})], fault_injector=reject)
    assert caught.value is cause
    assert not (tmp_path / 'x.json').exists()


def test_unknown_recovery_chronology_does_not_publish_an_assumed_predecessor(tmp_path):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    target = tmp_path / 'x.json'
    def prepared(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('prepared')
    with pytest.raises(RuntimeError):
        owner.commit([wal.JsonArtifact('state', target, {'v': 1})],
                     transaction_id='a-first', fault_injector=prepared)
    corrupt = tmp_path / 'wal/transactions/z-corrupt'
    corrupt.mkdir()
    (corrupt / 'manifest.json').write_bytes(b'{bad')
    with pytest.raises(wal.WalIntegrityError) as caught:
        owner.recover()
    assert not target.exists()
    outcome = caught.value.wal_recovery
    assert outcome['completed'] == []
    assert outcome['target_effects_may_have_occurred'] is False
    assert outcome['active_transaction'] is None
    assert outcome['active_phase'] == 'inventory'
    assert corrupt.is_dir()


def test_pending_enumeration_stops_during_scandir(tmp_path, monkeypatch):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    base = tmp_path / 'wal/transactions'
    base.mkdir(parents=True)
    for index in range(5):
        (base / str(index)).mkdir()
    monkeypatch.setattr(wal, 'MAX_PENDING_TRANSACTIONS', 2)
    original = wal.os.scandir
    visits = []
    class BoundedScan:
        def __enter__(self):
            self.scan = original(base)
            def values():
                for entry in self.scan:
                    visits.append(entry.name)
                    if len(visits) > 3:
                        pytest.fail('enumeration continued after overflow witness')
                    yield entry
            return values()

        def __exit__(self, *args):
            self.scan.close()
    monkeypatch.setattr(wal.os, 'scandir', lambda path: BoundedScan())
    with pytest.raises(wal.WalIntegrityError, match='transaction bound'):
        owner._pending_transactions()
    assert len(visits) == 3


@pytest.mark.parametrize('operation', ['recover', 'commit'])
@pytest.mark.parametrize('primary_failure', [False, True])
def test_lock_release_does_not_erase_outcome_or_causal_failure(tmp_path, monkeypatch, operation, primary_failure):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    target = tmp_path / 'x.json'
    artifacts = [wal.JsonArtifact('state', target, {'v': 1})]
    if operation == 'recover':
        def prepared(point):
            if point == 'manifest:prepared:published':
                raise RuntimeError('prepared')
        with pytest.raises(RuntimeError):
            owner.commit(artifacts, transaction_id='existing', fault_injector=prepared)
    cause = RuntimeError('primary publication failure')
    release = OSError('lock release acknowledgement failed')
    original_lock = wal.FileLock
    class ReleaseFailure:
        def __init__(self, *args, **kwargs):
            self.lock = original_lock(*args, **kwargs)

        def __enter__(self):
            return self.lock.__enter__()

        def __exit__(self, *args):
            self.lock.__exit__(*args)
            raise release
    monkeypatch.setattr(wal, 'FileLock', ReleaseFailure)
    if primary_failure:
        original_apply = owner._apply
        def fail(point):
            if point == 'target:0:published':
                raise cause
        def interrupted(transaction, manifest, fault_injector=None):
            return original_apply(transaction, manifest, fail)
        monkeypatch.setattr(owner, '_apply', interrupted)
    with pytest.raises((RuntimeError, OSError)) as caught:
        owner.recover() if operation == 'recover' else owner.commit(artifacts, transaction_id='new')
    assert caught.value is (cause if primary_failure else release)
    assert json.loads(target.read_bytes()) == {'v': 1}
    outcome = getattr(caught.value, 'wal_recovery' if operation == 'recover' else 'wal_outcome')
    assert outcome['acknowledgement'] == 'failed'
    if primary_failure:
        assert outcome['lock_release']['error_type'] == 'OSError'
    elif operation == 'recover':
        assert outcome['completed'] == ['existing']
    else:
        assert outcome['transaction_phase'] == 'committed'
