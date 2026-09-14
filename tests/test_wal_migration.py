from __future__ import annotations

import hashlib
import json

import pytest

from runtime.wal_generation import WalGeneration
from runtime.wal_migration import migrate_legacy_wals
from runtime.wal_transaction import JsonArtifact, JsonWal, WalIntegrityError


def _legacy(root, names=('wal',)):
    owners = []
    for name in names:
        wal = JsonWal(root / name, root)
        wal.commit([JsonArtifact('state', root / (name + '.json'), {'before': True})])
        owners.append(dict(journal=name, domains=[dict(path=name + '.json', kind='exact')]))
    return owners


def _files(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file() and p.name != '.wal.lock'
            and '.lock-recovery-receipts' not in p.parts}


def test_legacy_activation_preserves_history_and_subsequent_writes(tmp_path):
    owners = _legacy(tmp_path)
    before = _files(tmp_path / 'wal' / 'committed')
    raw = (tmp_path / 'wal.json').read_bytes()
    first = migrate_legacy_wals(tmp_path, owners)
    assert first['valid'] and first['historical_payloads_verified'] is False
    assert _files(tmp_path / 'wal' / 'committed') == before
    assert (tmp_path / 'wal.json').read_bytes() == raw
    wal = JsonWal(tmp_path / 'wal', tmp_path)
    token = wal.capture_generation()
    wal.commit([JsonArtifact('state', tmp_path / 'wal.json', {'after': True})], expected_generation=token)
    head = WalGeneration(tmp_path / 'wal').read()
    second = migrate_legacy_wals(tmp_path, owners)
    assert second['generations']['wal'] == head
    assert head['sequence'] == 1 and head['sha256'] != token
    assert json.loads((tmp_path / 'wal.json').read_bytes()) == {'after': True}


@pytest.mark.parametrize('boundary', [
    'intent:published', 'catalog:published', 'catalog:acknowledged',
    'wal:marker.json:staged', 'wal:head.json:staged', 'wal:migration.json:staged',
    'wal:publication:prepared',
    'wal:generation:published', 'other:generation:published', 'acknowledged',
])
def test_interrupted_multi_journal_migration_resumes_exactly(tmp_path, boundary):
    owners = _legacy(tmp_path, ('wal', 'other'))
    def stop(label):
        if label == 'migration:' + boundary:
            raise RuntimeError('interrupted migration')
    with pytest.raises(RuntimeError, match='interrupted'):
        migrate_legacy_wals(tmp_path, owners, fault_injector=stop)
    if boundary != 'intent:published':
        for name in ('wal', 'other'):
            if not (tmp_path / name / 'generation').exists():
                with pytest.raises(WalIntegrityError):
                    JsonWal(tmp_path / name, tmp_path).capture_generation()
    result = migrate_legacy_wals(tmp_path, owners)
    assert set(result['generations']) == {'wal', 'other'}
    assert all(h['sequence'] == 0 for h in result['generations'].values())


def test_changed_input_after_intent_refuses_without_catalog(tmp_path):
    owners = _legacy(tmp_path)
    def stop(label):
        if label == 'migration:intent:published':
            raise RuntimeError('stop')
    with pytest.raises(RuntimeError):
        migrate_legacy_wals(tmp_path, owners, fault_injector=stop)
    (tmp_path / 'wal.json').write_text('{}')
    with pytest.raises(WalIntegrityError, match='changed'):
        migrate_legacy_wals(tmp_path, owners)
    assert not (tmp_path / '.engineering-bootstrap/wal-ownership.json').exists()


def test_current_generation_requires_compact_migration_evidence(tmp_path):
    owners = _legacy(tmp_path)
    migrate_legacy_wals(tmp_path, owners)
    evidence = tmp_path / 'wal/generation/migration.json'
    evidence.rename(evidence.with_suffix('.retained'))
    with pytest.raises(WalIntegrityError, match='missing or invalid'):
        JsonWal(tmp_path / 'wal', tmp_path).capture_generation()


def test_activation_does_not_read_historical_payload_bodies(tmp_path, monkeypatch):
    owners = _legacy(tmp_path)
    from runtime import wal_migration
    read = wal_migration._bounded_image
    def checked(path, **kwargs):
        assert 'before' not in path.parts and 'after' not in path.parts
        return read(path, **kwargs)
    monkeypatch.setattr(wal_migration, '_bounded_image', checked)
    assert migrate_legacy_wals(tmp_path, owners)['valid']


@pytest.mark.parametrize('aborted', [False, True])
def test_lost_published_generation_cannot_be_reinitialized(tmp_path, aborted):
    owners = _legacy(tmp_path)
    migrate_legacy_wals(tmp_path, owners)
    if aborted:
        wal = JsonWal(tmp_path / 'wal', tmp_path)
        def stop(label):
            if label == 'generation:allocated:published':
                raise RuntimeError('stop after allocation')
        with pytest.raises(RuntimeError):
            wal.commit([JsonArtifact('state', tmp_path / 'wal.json', {})], fault_injector=stop)
        wal.recover()
        assert WalGeneration(tmp_path / 'wal').read()['sequence'] == 1
    generation = tmp_path / 'wal/generation'
    generation.rename(tmp_path / 'retained-generation')
    with pytest.raises(WalIntegrityError, match='published|publication'):
        migrate_legacy_wals(tmp_path, owners)
    assert not generation.exists()


def test_pending_legacy_wal_refuses_migration(tmp_path):
    wal = JsonWal(tmp_path / 'wal', tmp_path)
    def stop(label):
        if label == 'manifest:prepared:published':
            raise RuntimeError('pending')
    with pytest.raises(RuntimeError):
        wal.commit([JsonArtifact('state', tmp_path / 'wal.json', {})], fault_injector=stop)
    owners = [dict(journal='wal', domains=[dict(path='wal.json', kind='exact')])]
    with pytest.raises(WalIntegrityError, match='pending'):
        migrate_legacy_wals(tmp_path, owners)
    assert not (tmp_path / '.engineering-bootstrap/wal-ownership.json').exists()


def test_generation_reads_do_not_read_complete_migration_inventory(tmp_path, monkeypatch):
    owners = _legacy(tmp_path)
    migrate_legacy_wals(tmp_path, owners)
    from runtime import wal_transaction
    original = wal_transaction._bounded_image
    def checked(path, **kwargs):
        assert path.name != 'wal-migration-intent.json'
        assert 'committed' not in path.parts
        return original(path, **kwargs)
    monkeypatch.setattr(wal_transaction, '_bounded_image', checked)
    assert JsonWal(tmp_path / 'wal', tmp_path).capture_generation()


def test_migration_entrypoint_binds_declared_image_before_effect(tmp_path, capsys):
    from scripts.migrate_wal_generation import main
    owners = _legacy(tmp_path)
    declaration = tmp_path / 'owners.json'
    raw = json.dumps(dict(schema_version='px.wal-migration-declaration/1.0', owners=owners)).encode()
    declaration.write_bytes(raw)
    args = ['--root', str(tmp_path), '--declaration', str(declaration), '--expected-declaration-sha256']
    with pytest.raises(ValueError, match='changed'):
        main([*args, '0' * 64])
    assert not (tmp_path / '.engineering-bootstrap/wal-ownership.json').exists()
    assert main([*args, hashlib.sha256(raw).hexdigest()]) == 0
    assert json.loads(capsys.readouterr().out)['valid'] is True


@pytest.mark.parametrize('epoch', ['invalid-epoch', '../outside', '', None, [], 'g' * 32])
def test_resealed_invalid_epoch_refuses_before_catalog_publication(tmp_path, epoch):
    from runtime.wal_migration import _seal
    owners = _legacy(tmp_path)
    def stop(label):
        if label == 'migration:intent:published':
            raise RuntimeError('stop')
    with pytest.raises(RuntimeError):
        migrate_legacy_wals(tmp_path, owners, fault_injector=stop)
    path = tmp_path / '.engineering-bootstrap/wal-migration-intent.json'
    intent = json.loads(path.read_bytes())
    intent['journals']['wal']['epoch'] = epoch
    path.write_text(json.dumps(_seal(intent)))
    with pytest.raises(WalIntegrityError):
        migrate_legacy_wals(tmp_path, owners)
    assert not (tmp_path / '.engineering-bootstrap/wal-ownership.json').exists()


def test_physical_child_exit_migration_boundaries(tmp_path):
    import os
    from pathlib import Path
    import sys
    from runtime.test_runner import run_test_command
    from runtime.resource_lifecycle import ResourceManager
    child = '''
import os, sys, json
from pathlib import Path
from runtime.wal_migration import migrate_legacy_wals
def stop(label):
    if label == sys.argv[3]:
        os._exit(91)
migrate_legacy_wals(Path(sys.argv[1]), json.loads(sys.argv[2]), fault_injector=stop)
'''
    manager = ResourceManager(tmp_path / 'children.json')
    boundaries = ['intent:published', 'catalog:published', 'catalog:acknowledged',
                  'other:marker.json:staged', 'other:head.json:staged',
                  'other:migration.json:staged', 'other:publication:prepared',
                  'other:generation:published', 'wal:generation:published', 'acknowledged']
    for index, boundary in enumerate(boundaries):
        root = tmp_path / str(index)
        root.mkdir()
        owners = _legacy(root, ('other', 'wal'))
        result = run_test_command([sys.executable, '-c', child, str(root), json.dumps(owners), 'migration:' + boundary],
            cwd=Path(__file__).parents[1], environment=os.environ, resource_manager=manager,
            run_id=f'migration-child-{index}', lane_id='wal-migration-crash', timeout_seconds=20,
            manage_process_temp=True)
        assert result['exit_code'] == 91, result.get('stderr')
        assert result['execution_started'] and result['process_tree_terminated']
        assert result['test_workspace']['reclaimed']
        migrated = migrate_legacy_wals(root, owners)
        assert all(head['sequence'] == 0 for head in migrated['generations'].values())


def test_capture_validates_one_charged_manifest_image(tmp_path, monkeypatch):
    from runtime import wal_migration as owner
    from runtime.wal_ownership import WalOwnership, SCHEMA
    owners = _legacy(tmp_path)
    info = tmp_path.stat()
    catalog = WalOwnership(tmp_path, dict(schema_version=SCHEMA,
        root_identity=dict(device=info.st_dev, inode=info.st_ino), owners=owners))
    budget = owner._Budget()
    image = budget.image
    calls = []
    def counted(path, **kwargs):
        calls.append(path)
        return image(path, **kwargs)
    monkeypatch.setattr(budget, 'image', counted)
    def second_image(*args):
        raise AssertionError('uncharged second manifest image')
    monkeypatch.setattr(JsonWal, '_load_manifest', second_image)
    snapshot = owner._capture(catalog, tmp_path / 'wal', budget)
    manifests = [path for path in calls if path.name == 'manifest.json']
    assert len(manifests) == len(set(manifests)) == 1
    assert snapshot['history']['committed']
