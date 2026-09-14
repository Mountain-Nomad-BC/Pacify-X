"""Independent storage contracts; every database lives in the owned test fixture."""
from dataclasses import asdict, replace
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from runtime.resource_lifecycle import ResourceLedger, ResourceRecord, resource_status
from runtime.resource_storage import IndexedResourceStorage, ResourceStorageError


def record(identity='resource-a', **changes):
    value = ResourceRecord(resource_id=identity, resource_type='path', project_id='fixture',
        run_id='fixture-run', lane_id='fixture-lane', creator=__name__, classification='ephemeral',
        created_at='2026-09-10T00:00:00+00:00', last_activity_at='2026-09-10T00:00:00+00:00',
        expected_cleanup_event='fixture-end', retention_required=True)
    return replace(value, **changes)


def images(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def normalized(rows):
    return json.loads(json.dumps([asdict(row) for row in rows]))


def indexed_ledger(root, records):
    import hashlib
    from runtime.json_io import bounded_canonical_json_bytes
    from runtime.resource_storage import SELECTOR_SCHEMA
    epoch = 'a' * 32
    generation = root / 'ledger-storage' / epoch
    generation.mkdir(parents=True)
    storage = IndexedResourceStorage(generation / 'resources.sqlite', ResourceRecord)
    storage.create(records, epoch=epoch)
    selector = dict(schema_version=SELECTOR_SCHEMA, state='active', epoch=epoch,
                    database=f'ledger-storage/{epoch}/resources.sqlite', legacy_sha256='0' * 64)
    selector['selector_sha256'] = hashlib.sha256(bounded_canonical_json_bytes(selector, max_bytes=4096)).hexdigest()
    ledger = ResourceLedger(root / 'ledger.json')
    ledger.path.write_bytes(bounded_canonical_json_bytes(selector, max_bytes=4096))
    return ledger, storage


def indexed_ledger_v2(root, records):
    import hashlib
    from runtime.json_io import bounded_canonical_json_bytes
    from runtime.resource_storage import SELECTOR_SCHEMA
    epoch = 'b' * 32
    generation = root / 'ledger-storage' / epoch
    generation.mkdir(parents=True)
    storage = IndexedResourceStorage(generation / 'resources.sqlite', ResourceRecord, expected_epoch=epoch)
    connection = sqlite3.connect(storage.path)
    try:
        for sql in storage.legacy_schemas.values():
            connection.execute(sql)
        connection.execute('INSERT INTO metadata VALUES (1,2,?,0,1)', (epoch,))
        for ordinal, item in enumerate(records):
            data = asdict(item)
            data.pop('host_boot_generation')
            size = len(bounded_canonical_json_bytes(data, max_bytes=65_536))
            _new_size, values = storage._encode(item)
            connection.execute('INSERT INTO resources VALUES (' + ','.join('?' for _ in range(len(values) + 1)) + ')',
                               (ordinal, size, *values[:-1]))
        connection.commit()
    finally:
        connection.close()
    selector = dict(schema_version=SELECTOR_SCHEMA, state='active', epoch=epoch,
                    database=f'ledger-storage/{epoch}/resources.sqlite', legacy_sha256='0' * 64)
    selector['selector_sha256'] = hashlib.sha256(bounded_canonical_json_bytes(selector, max_bytes=4096)).hexdigest()
    ledger = ResourceLedger(root / 'ledger.json')
    ledger.path.write_bytes(bounded_canonical_json_bytes(selector, max_bytes=4096))
    return ledger, storage


def test_v2_database_is_readable_but_requires_explicit_migration_for_writes(tmp_path):
    original = [record('old-a'), record('old-b', active=False)]
    ledger, storage = indexed_ledger_v2(tmp_path, original)
    assert storage.database_schema_version() == 2
    assert normalized(ledger.observe()) == normalized(original)
    with pytest.raises(ResourceStorageError, match='explicit v3 migration'):
        ledger.update('old-a', active=False)


def test_v3_migration_retains_v2_generation_and_preserves_every_record(tmp_path):
    import hashlib
    from scripts.migrate_resource_storage_v3 import migrate
    original = [record(f'old-{index:04d}', active=False) for index in range(1000)]
    ledger, old_storage = indexed_ledger_v2(tmp_path, original)
    old_selector = ledger.path.read_bytes()
    old_database = old_storage.path.read_bytes()
    digest = hashlib.sha256(old_selector).hexdigest()
    dry_run = migrate(ledger.path, expected_selector_sha256=digest, dry_run=True)
    assert dry_run['state'] == 'dry_run' and dry_run['record_count'] == len(original)
    result = migrate(ledger.path, expected_selector_sha256=digest)
    assert result['state'] == 'activated' and result['target_schema'] == 3
    assert old_storage.path.read_bytes() == old_database
    assert normalized(ledger.observe()) == normalized(original)
    ledger.update('old-0007', host_boot_generation='windows:test:7')
    assert ledger.get('old-0007').host_boot_generation == 'windows:test:7'
    repeated = migrate(ledger.path, expected_selector_sha256=digest)
    assert repeated['state'] == 'already_active'
    assert ledger.path.parent.joinpath(json.loads(ledger.path.read_bytes())['database']).parent.joinpath('selector-v2.json').read_bytes() == old_selector


def test_facade_point_operations_preserve_selector_and_all_other_records(tmp_path, monkeypatch):
    original = [record('a'), record('b', active=False, cleanup_intent={'phase': 'pending'})]
    ledger, storage = indexed_ledger(tmp_path, original)
    selector = ledger.path.read_bytes()
    before = images(tmp_path)
    assert normalized(ledger.observe()) == normalized(original)
    assert images(tmp_path) == before
    monkeypatch.setattr(IndexedResourceStorage, 'write', lambda *args: pytest.fail('point operation replaced history'))
    ledger.update('a', active=False)
    ledger.upsert(record('c'))
    assert ledger.get('a').active is False
    assert normalized(ledger.load()) == normalized([replace(original[0], active=False), original[1], record('c')])
    assert ledger.path.read_bytes() == selector
    assert resource_status(ledger.path)['cleanup_pending'] == 1


@pytest.mark.parametrize('changes', [dict(state='pending'), dict(epoch='b'*32),
                                   dict(database='../outside.sqlite'), dict(unclassified=True)])
def test_facade_refuses_invalid_selector_without_storage_effects(tmp_path, changes):
    ledger, storage = indexed_ledger(tmp_path, [record()])
    selector = json.loads(ledger.path.read_bytes())
    selector.update(changes)
    ledger.path.write_text(json.dumps(selector), encoding='utf-8')
    before = images(tmp_path)
    with pytest.raises(ValueError):
        ledger.observe()
    assert images(tmp_path) == before


@pytest.mark.parametrize('epoch', ['', 'x'*32, True, 'a'*33])
def test_invalid_epoch_refuses_before_creation(tmp_path, epoch):
    storage = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    with pytest.raises(ValueError, match='epoch'):
        storage.create([record()], epoch=epoch)
    assert list(tmp_path.iterdir()) == []


def test_cohesion_holds_generation_until_capture_scope_closes(tmp_path):
    import scripts.reconcile_cohesion_cards as cohesion
    ledger, storage = indexed_ledger(tmp_path, [record(active=False)])
    captured = cohesion._CapturedInputs(tmp_path)
    token = cohesion._INPUTS.set(captured)
    try:
        assert cohesion._resource_status(ledger.path)['active_paths'] == 0
        captured.revalidate()
        # A competing commit cannot change the read generation underlying the
        # close decision while its captured-input scope remains live.
        connection = sqlite3.connect(storage.path, timeout=0, isolation_level=None)
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('UPDATE resources SET active=1,record_bytes=record_bytes-1')
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                connection.execute('COMMIT')
            connection.execute('ROLLBACK')
        finally:
            connection.close()
    finally:
        captured.resource_locks.close()
        cohesion._INPUTS.reset(token)
    storage.update('resource-a', active=True)
    assert cohesion._resource_status(ledger.path)['active_paths'] == 1


def legacy_ledger(root, records):
    import hashlib
    ledger = ResourceLedger(root / 'ledger.json')
    ledger.write(records)
    raw = ledger.path.read_bytes()
    return ledger, raw, hashlib.sha256(raw).hexdigest()


def test_migration_preserves_all_twenty_thousand_records_and_newer_writes(tmp_path):
    from scripts.migrate_resource_ledger import migrate
    original = [record(f'resource-{i:05d}', active=False, status='reclaimed') for i in range(20_000)]
    original[7] = replace(original[7], status='cleanup_pending', cleanup_intent={'phase': 'effect_pending'})
    ledger, raw, digest = legacy_ledger(tmp_path, original)
    result = migrate(ledger.path, expected_legacy_sha256=digest)
    assert result['state'] == 'activated' and result['record_count'] == len(original)
    assert normalized(ledger.observe()) == normalized(original)
    assert (tmp_path / json.loads(ledger.path.read_bytes())['database']).with_name('legacy.json').read_bytes() == raw
    ledger.update('resource-00007', retained_reason='unresolved after migration')
    original[7] = replace(original[7], retained_reason='unresolved after migration')
    before = images(tmp_path)
    repeated = migrate(ledger.path, expected_legacy_sha256=digest)
    assert repeated['state'] == 'already_active'
    assert repeated['current_generation']['generation'] > result['current_generation']['generation']
    assert normalized(ledger.load()) == normalized(original)
    # FileLock metadata is transient; authority and all generation evidence stay exact.
    assert {k: v for k, v in images(tmp_path).items() if not k.endswith('.lock')} == {k: v for k, v in before.items() if not k.endswith('.lock')}


@pytest.mark.parametrize('boundary', ['intent_written', 'legacy_retained', 'database_created',
                                     'receipt_written', 'before_activation', 'selector:staged',
                                     'selector:published', 'activated'])
def test_migration_child_crash_preserves_authority_and_recovers(tmp_path, boundary):
    import os
    import sys
    from pathlib import Path
    from runtime.resource_lifecycle import ResourceManager
    from runtime.test_runner import run_test_command
    from scripts.migrate_resource_ledger import migrate
    original = [record('a', active=False), record('b', active=False, cleanup_intent={'phase': 'effect_pending'})]
    ledger, raw, digest = legacy_ledger(tmp_path / 'subject', original)
    code = '''import os, sys
from scripts.migrate_resource_ledger import migrate
def crash(label):
    if label == sys.argv[3]:
        os._exit(71)
migrate(sys.argv[1], expected_legacy_sha256=sys.argv[2], fault_injector=crash)
'''
    result = run_test_command([sys.executable, '-c', code, str(ledger.path), digest, boundary],
        cwd=Path(__file__).resolve().parents[1], environment=dict(os.environ), timeout_seconds=20,
        resource_manager=ResourceManager(tmp_path / 'runner' / 'ledger.json'),
        run_id='migration-crash', lane_id='migration-proof', manage_process_temp=True)
    assert result['exit_code'] == 71 and result['process_tree_terminated'] is True
    assert result['test_workspace']['reclaimed'] is True
    assert normalized(ledger.observe()) == normalized(original)
    before_activation = boundary not in ('selector:published', 'activated')
    if before_activation:
        assert ledger.path.read_bytes() == raw
    retained = {str(p): p.read_bytes() for p in ledger.path.parent.glob('ledger-storage/*/legacy.json')}
    recovered = migrate(ledger.path, expected_legacy_sha256=digest)
    assert recovered['valid'] is True
    assert normalized(ledger.load()) == normalized(original)
    assert all(Path(path).read_bytes() == image for path, image in retained.items())


def test_migration_refuses_stale_identity_and_active_processes(tmp_path, monkeypatch):
    from scripts.migrate_resource_ledger import migrate
    monkeypatch.setattr('scripts.migrate_resource_ledger._process_exists', lambda pid: True)
    ledger, raw, digest = legacy_ledger(tmp_path, [record(resource_type='process', pid=123)])
    with pytest.raises(ValueError, match='changed'):
        migrate(ledger.path, expected_legacy_sha256='0'*64)
    with pytest.raises(ValueError, match='quiescent'):
        migrate(ledger.path, expected_legacy_sha256=digest)
    assert ledger.path.read_bytes() == raw
    assert not (tmp_path / 'ledger-storage').exists()


def test_migration_preserves_dead_parent_obligations_and_rechecks_liveness(tmp_path, monkeypatch):
    from scripts.migrate_resource_ledger import migrate
    calls = []
    def liveness(pid):
        calls.append(pid)
        return len(calls) > 1
    monkeypatch.setattr('scripts.migrate_resource_ledger._process_exists', liveness)
    original = record(resource_type='process', pid=123, active=True)
    ledger, raw, digest = legacy_ledger(tmp_path, [original])
    with pytest.raises(ValueError, match='quiescent'):
        migrate(ledger.path, expected_legacy_sha256=digest)
    assert ledger.path.read_bytes() == raw and calls == [123, 123]
    monkeypatch.setattr('scripts.migrate_resource_ledger._process_exists', lambda pid: False)
    migrate(ledger.path, expected_legacy_sha256=digest)
    assert normalized(ledger.observe()) == normalized([original])
    assert ledger.get('resource-a').active is True


@pytest.mark.parametrize('identity,current,accepted', [
    ('process-start:' + 'a'*64, 'b'*64, True),
    ('process-start:' + 'a'*64, 'a'*64, False),
    ('process-start:' + 'a'*64, None, False),
    ('unknown', 'b'*64, False),
])
def test_migration_reused_pid_requires_exact_start_evidence(tmp_path, monkeypatch, identity, current, accepted):
    from scripts.migrate_resource_ledger import migrate
    monkeypatch.setattr('scripts.migrate_resource_ledger._process_exists', lambda pid: True)
    monkeypatch.setattr('scripts.migrate_resource_ledger._process_start_fingerprint', lambda pid: current)
    original = record(resource_type='process', pid=123, process_identity=identity)
    ledger, raw, digest = legacy_ledger(tmp_path, [original])
    if accepted:
        migrate(ledger.path, expected_legacy_sha256=digest)
        assert normalized(ledger.observe()) == normalized([original])
    else:
        with pytest.raises(ValueError, match='quiescent'):
            migrate(ledger.path, expected_legacy_sha256=digest)
        assert ledger.path.read_bytes() == raw


def test_backend_comparison_preserves_complete_identical_workload(tmp_path, capsys):
    from statistics import median
    from time import perf_counter
    original = [record(f'resource-{i:05d}', active=False) for i in range(8000)]
    legacy, _, _ = legacy_ledger(tmp_path / 'legacy', original)
    indexed, _ = indexed_ledger(tmp_path / 'indexed', original)
    timings = {'legacy_json': [], 'indexed': []}
    for attempt in range(3):
        order = [('legacy_json', legacy), ('indexed', indexed)]
        if attempt % 2:
            order.reverse()
        for name, ledger in order:
            started = perf_counter()
            ledger.update('resource-00123', retained_reason=f'comparison-{attempt}')
            timings[name].append(perf_counter() - started)
        assert normalized(legacy.observe()) == normalized(indexed.observe())
    with capsys.disabled():
        print('storage_backend_comparison=' + json.dumps(dict(records=len(original), samples=timings,
            median_seconds={name: median(values) for name, values in timings.items()},
            scope='current production facade point updates; warm fixture; excludes setup and parity reads; no RSS or whole-gate claim')))


def test_indexed_owner_binding_and_cleanup_preserve_unresolved_records(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path
    from runtime.resource_lifecycle import ResourceManager, RunState
    from scripts.migrate_resource_ledger import migrate
    manager = ResourceManager(tmp_path / 'ledger.json')
    (tmp_path / 'workspaces').mkdir()
    workspace = manager.create_workspace(tmp_path / 'workspaces', project_id='fixture',
        run_id='owned-run', lane_id='fixture', creator=__name__)
    target = Path(workspace.path) / 'published.txt'
    child = manager.register_path(target, allowed_cleanup_root=Path(workspace.path),
        project_id='fixture', run_id='owned-run', lane_id='fixture', creator=__name__)
    unresolved = record('retained-obligation', active=False, cleanup_intent={'phase': 'effect_pending'})
    manager.ledger.upsert(unresolved)
    digest = hashlib.sha256(manager.ledger.path.read_bytes()).hexdigest()
    migrate(manager.ledger.path, expected_legacy_sha256=digest)
    monkeypatch.setattr(IndexedResourceStorage, 'write', lambda *args: pytest.fail('cleanup rewrote full history'))
    target.write_bytes(b'exact publication')
    bound = manager.bind_created_path(child.resource_id, b'exact publication')
    assert bound.path_identity is not None
    manager.mark_run_ended('owned-run', RunState.COMPLETED)
    child_receipt = manager.reclaim(child.resource_id, reason='fixture end', apply=True)
    parent_receipt = manager.reclaim(workspace.resource_id, reason='fixture end', apply=True)
    assert child_receipt.resources_reclaimed == parent_receipt.resources_reclaimed == 1
    assert not Path(workspace.path).exists()
    assert normalized([manager.ledger.get(unresolved.resource_id)]) == normalized([unresolved])
    assert resource_status(manager.ledger.path)['cleanup_pending'] == 1


def test_create_read_and_point_mutation_preserve_other_records(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    original = [record('z', cleanup_intent={'phase': 'effect_pending'}), record('a')]
    store.create(original)
    assert normalized(store.load()) == normalized(original)
    store.update('a', active=False)
    assert normalized(store.load()) == normalized([replace(original[1], active=False), original[0]])
    store.upsert(record('m', retention_required=False))
    assert [row.resource_id for row in store.load()] == ['a', 'm', 'z']
    assert store.get('z').cleanup_intent == {'phase': 'effect_pending'}


@pytest.mark.parametrize('text', ['plain', '\"\\\n\t', 'é汉字🧠', '\u2028\u2029', '\x00'])
@pytest.mark.parametrize('number', [0.0, 1.25, 1e-7, 1e20])
def test_sql_accounting_matches_python_wire_values(tmp_path, text, number):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    value = record(creator=text, cleanup_intent={'nested': {'text': text, 'number': number}, 'array': [True, None, 3]})
    store.create([value])
    assert normalized(store.load()) == normalized([value])


def test_observation_is_nonmutating_and_generation_detects_aba(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    store.create([record()])
    before = images(tmp_path)
    rows, first = store.snapshot()
    assert images(tmp_path) == before
    assert store.load() == rows and images(tmp_path) == before
    store.update('resource-a', active=False)
    store.update('resource-a', active=True)
    rows_after, after = store.snapshot()
    assert rows_after == rows
    assert after['epoch'] == first['epoch']
    assert after['generation'] == first['generation'] + 2
    assert after['sha256'] != first['sha256']


def test_missing_reader_does_not_initialize_storage(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'absent.sqlite', ResourceRecord)
    with pytest.raises(ResourceStorageError):
        store.load()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('changes', [{'active': 1}, {'files': True}, {'pid': -1},
                                    {'creator': 12}, {'resource_type': 'unknown'},
                                    {'cleanup_intent': []}, {'promoted_outputs': {}},
                                    {'resource_id': ''}, {'bytes': 2**64}])
def test_invalid_creation_refuses_before_file_effect(tmp_path, changes):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    with pytest.raises(ValueError):
        store.create([record(**changes)])
    assert list(tmp_path.iterdir()) == []


def test_duplicate_and_unbounded_creation_are_rejected_without_effects(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    with pytest.raises(ValueError, match='duplicate'):
        store.create([record(), record()])
    def unbounded():
        pytest.fail('unbounded input was consumed')
        yield record()
    with pytest.raises(ValueError, match='list or tuple'):
        store.create(unbounded())
    assert list(tmp_path.iterdir()) == []


def test_existing_generation_is_never_overwritten_by_create(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    store.create([record()])
    before = images(tmp_path)
    with pytest.raises(FileExistsError):
        store.create([record('different')])
    assert images(tmp_path) == before


def test_point_mutation_rolls_back_after_sql_effect(tmp_path, monkeypatch):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    store.create([record()])
    before = images(tmp_path)
    put = store._put
    def fail_after_write(connection, value):
        put(connection, value)
        raise RuntimeError('after SQL effect')
    monkeypatch.setattr(store, '_put', fail_after_write)
    with pytest.raises(RuntimeError, match='after SQL effect'):
        store.update('resource-a', active=False)
    assert images(tmp_path) == before
    assert store.get('resource-a').active is True


@pytest.mark.parametrize('sql', ['CREATE TABLE hidden(value TEXT)',
                               'CREATE INDEX hidden ON resources(active)',
                               'PRAGMA ignore_check_constraints=ON; UPDATE resources SET record_bytes=1'])
def test_unclassified_schema_and_forged_size_cannot_authorize_updates(tmp_path, sql):
    path = tmp_path / 'records.sqlite'
    store = IndexedResourceStorage(path, ResourceRecord)
    store.create([record()])
    with sqlite3.connect(path) as connection:
        connection.executescript(sql)
    before = images(tmp_path)
    with pytest.raises(ResourceStorageError):
        store.update('resource-a', active=False)
    assert images(tmp_path) == before


def test_two_independent_writers_preserve_both_changes(tmp_path):
    path = tmp_path / 'records.sqlite'
    store = IndexedResourceStorage(path, ResourceRecord)
    store.create([record()])
    def change(values):
        return IndexedResourceStorage(path, ResourceRecord).update('resource-a', **values)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(change, ({'active': False}, {'retention_required': False})))
    result = store.get('resource-a')
    assert result.active is False and result.retention_required is False


def test_twenty_thousand_records_retain_exact_semantics(tmp_path):
    store = IndexedResourceStorage(tmp_path / 'records.sqlite', ResourceRecord)
    original = [record(f'resource-{i:05d}', active=False, status='reclaimed',
                       path_identity=(1, i, 2, 3), promoted_outputs=('evidence',)) for i in range(20_000)]
    original[123] = replace(original[123], status='cleanup_pending', cleanup_intent={'phase': 'effect_pending'})
    store.create(original)
    assert normalized(store.load()) == normalized(original)
    store.update('resource-00123', retained_reason='still unresolved')
    original[123] = replace(original[123], retained_reason='still unresolved')
    assert normalized(store.load()) == normalized(original)
