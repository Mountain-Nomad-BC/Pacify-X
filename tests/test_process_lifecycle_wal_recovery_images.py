"""Whole-transaction acquisition and restored-journal causal fixtures."""
import json
import shutil

import pytest

from runtime import wal_transaction as wal


def prepared(root, count=2, identifier='pending'):
    root.mkdir(parents=True, exist_ok=True)
    owner = wal.JsonWal(root / 'wal', root)
    artifacts = []
    for index in range(count):
        target = root / f'{index}.txt'
        target.write_text('before')
        artifacts.append(wal.TextArtifact('state', target, 'after'))
    def stop(point):
        if point == 'manifest:prepared:published':
            raise RuntimeError('fixture interruption')
    with pytest.raises(RuntimeError, match='fixture interruption'):
        owner.commit(artifacts, transaction_id=identifier, fault_injector=stop)
    return owner, root / 'wal/transactions' / identifier


def images(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file() and path.name != '.wal.lock'}


@pytest.mark.parametrize('mode', ['apply', 'recover'])
def test_late_invalid_image_refuses_before_first_target(tmp_path, mode):
    owner, transaction = prepared(tmp_path)
    (transaction / 'after/0001.txt').write_bytes(b'corrupt')
    before = images(tmp_path)
    with pytest.raises(wal.WalIntegrityError):
        if mode == 'apply':
            owner._apply(transaction, owner._load_manifest(transaction))
        else:
            owner.recover()
    assert images(tmp_path) == before


def test_apply_uses_verified_staged_bytes_after_acquisition(tmp_path):
    owner, transaction = prepared(tmp_path)
    manifest = owner._load_manifest(transaction)
    def replace_later_image(point):
        if point == 'target:0:published':
            (transaction / 'after/0001.txt').write_bytes(b'corrupt')
    owner._apply(transaction, manifest, replace_later_image)
    assert (tmp_path / '0.txt').read_bytes() == b'after'
    assert (tmp_path / '1.txt').read_bytes() == b'after'


@pytest.mark.parametrize('entry', ['inspect', 'recover'])
def test_multiple_legacy_pending_transactions_have_no_inferred_order(tmp_path, entry):
    owner, _ = prepared(tmp_path / 'destination', 1, 'z-first')
    _, second = prepared(tmp_path / 'source', 1, 'a-second')
    shutil.copytree(second, owner.journal_root / 'transactions/a-second')
    before = images(tmp_path)
    with pytest.raises(wal.WalIntegrityError, match='chronology'):
        getattr(owner, entry)()
    assert images(tmp_path) == before


def test_recovery_acquires_one_manifest_image(tmp_path, monkeypatch):
    owner, transaction = prepared(tmp_path)
    original = owner._load_manifest
    reads = []
    def once(path):
        reads.append(path)
        if len(reads) > 1:
            pytest.fail('recovery decoded a second manifest image')
        return original(path)
    monkeypatch.setattr(owner, '_load_manifest', once)
    assert owner.recover()['valid']
    assert reads == [transaction]


def test_staged_images_are_acquired_once_per_apply(tmp_path, monkeypatch):
    owner, transaction = prepared(tmp_path)
    manifest = owner._load_manifest(transaction)
    original = wal._bounded_image
    opened = []
    def count(path, **kwargs):
        if path.is_relative_to(transaction):
            opened.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(wal, '_bounded_image', count)
    owner._apply(transaction, manifest)
    assert len(opened) == len(set(opened)) == 4


def test_aggregate_recovery_acquisition_refuses_before_publication(tmp_path, monkeypatch):
    owner, transaction = prepared(tmp_path)
    manifest = owner._load_manifest(transaction)
    before = images(tmp_path)
    monkeypatch.setattr(wal, 'MAX_INSPECTION_BYTES', 12)
    with pytest.raises(wal.WalIntegrityError, match='byte budget'):
        owner._apply(transaction, manifest)
    assert images(tmp_path) == before


def test_later_external_target_change_preserves_conflict(tmp_path):
    owner, transaction = prepared(tmp_path)
    def race(point):
        if point == 'target:0:published':
            (tmp_path / '1.txt').write_bytes(b'external')
    with pytest.raises(wal.WalIntegrityError, match='outside transaction'):
        owner._apply(transaction, owner._load_manifest(transaction), race)
    assert (tmp_path / '0.txt').read_bytes() == b'after'
    assert (tmp_path / '1.txt').read_bytes() == b'external'


@pytest.mark.parametrize('mutate', ['boolean-index', 'duplicate-target', 'aliased-stage'])
def test_resealed_manifest_semantics_refuse_before_effect(tmp_path, mutate):
    owner, transaction = prepared(tmp_path)
    path = transaction / 'manifest.json'
    manifest = json.loads(path.read_bytes())
    if mutate == 'boolean-index':
        manifest['artifacts'][0]['index'] = False
    elif mutate == 'duplicate-target':
        manifest['artifacts'][1]['path'] = manifest['artifacts'][0]['path']
    else:
        manifest['artifacts'][1]['after']['stage'] = manifest['artifacts'][0]['after']['stage']
    intents = [{'role': row['role'], 'path': row['path'], 'sha256': row['after']['sha256']}
               for row in manifest['artifacts']]
    manifest['intent_sha256'] = wal._sha_bytes(wal._canonical(intents))
    path.write_bytes(wal._canonical(wal._sealed_manifest(manifest)))
    before = images(tmp_path)
    with pytest.raises(wal.WalIntegrityError):
        owner.recover()
    assert images(tmp_path) == before


@pytest.mark.parametrize('conflict', [False, True])
def test_restored_before_images_and_interrupted_journal_are_actually_used(tmp_path, conflict):
    source = tmp_path / 'source'
    _, transaction = prepared(source)
    restored = tmp_path / 'restored'
    restored.mkdir()
    manifest = json.loads((transaction / 'manifest.json').read_bytes())
    for row in manifest['artifacts']:
        (restored / row['path']).write_bytes((transaction / row['before']['stage']).read_bytes())
    shutil.copytree(transaction, restored / 'wal/transactions/pending')
    owner = wal.JsonWal(restored / 'wal', restored)
    if conflict:
        (restored / '1.txt').write_bytes(b'external')
        before = images(restored)
        with pytest.raises(wal.WalIntegrityError):
            owner.recover()
        assert images(restored) == before
    else:
        assert owner.recover()['completed'] == ['pending']
        assert [(restored / f'{index}.txt').read_bytes() for index in range(2)] == [b'after', b'after']
        assert owner.inspect()['requires_recovery'] is False
