from __future__ import annotations

import json
from pathlib import Path
import zipfile
import pytest

from scripts.archive_committed_wal import apply, plan
from runtime.wal_ownership import WalOwnership
from runtime.wal_transaction import JsonArtifact, JsonWal


def _real_transactions(root):
    journal = root / '.engineering-bootstrap/operation-bus/wal'
    target = root / '.engineering-bootstrap/operation-bus/state.json'
    WalOwnership.activate(root, [dict(journal=journal.relative_to(root).as_posix(),
        domains=[dict(path=target.relative_to(root).as_posix(), kind='exact')])])
    wal = JsonWal(journal, root)
    wal.activate_generation(root)
    for index, name in enumerate(['zz-first', 'aa-second', 'mm-third', 'bb-fourth']):
        wal.commit([JsonArtifact('state', target, {'index': index, 'payload': 'x' * 1000})], transaction_id=name)
    return wal, journal / 'committed'


def test_committed_wal_archive_keeps_recent_transactions_recoverable(
    tmp_path: Path,
) -> None:
    wal, committed = _real_transactions(tmp_path)
    dry_run = plan(tmp_path, keep_latest=2)
    assert dry_run["selected_count"] == 2
    assert dry_run['manifest']['archived_transactions'] == ['zz-first', 'aa-second']
    assert dry_run['manifest']['retained_live_transactions'] == ['mm-third', 'bb-fourth']
    result = apply(tmp_path, keep_latest=2)
    assert result["changed"] is True
    assert len([path for path in committed.iterdir() if path.is_dir()]) == 2
    archive = Path(str(result["archive"]))
    with zipfile.ZipFile(archive) as sealed:
        assert sealed.testzip() is None
        assert len(sealed.namelist()) == dry_run['manifest']['file_count'] + 1
    receipt = json.loads(Path(str(result["receipt"])).read_text(encoding="utf-8"))
    assert receipt["hard_delete_without_archive"] is False
    assert receipt["archive_sha256"] == result["archive_sha256"]
    assert wal.inspect()['requires_recovery'] is False


@pytest.mark.parametrize('keep', [True, 1.0, '2', 0, 10001])
def test_archive_requires_actual_bounded_retention_count(tmp_path, keep):
    _wal, _committed = _real_transactions(tmp_path)
    with pytest.raises(ValueError):
        plan(tmp_path, keep_latest=keep)


def test_legacy_uuid_order_does_not_supply_chronology(tmp_path):
    committed = tmp_path / '.engineering-bootstrap/operation-bus/wal/committed'
    (committed / 'zz').mkdir(parents=True)
    (committed / 'aa').mkdir()
    with pytest.raises(ValueError, match='chronology'):
        plan(tmp_path, keep_latest=1)
    assert sorted(p.name for p in committed.iterdir()) == ['aa', 'zz']


def test_archive_refuses_payload_that_disagrees_with_transaction_manifest(tmp_path):
    _wal, committed = _real_transactions(tmp_path)
    manifest = json.loads((committed / 'zz-first/manifest.json').read_bytes())
    payload = committed / 'zz-first' / manifest['artifacts'][0]['after']['stage']
    payload.write_text('{"corrupt": true}')
    with pytest.raises(ValueError, match='payload'):
        apply(tmp_path, keep_latest=2)
    assert payload.read_text() == '{"corrupt": true}'
    assert not (committed.parent / 'archives').exists()


@pytest.mark.parametrize('conflict', ['none', 'target', 'generation'])
def test_verified_archive_reconstructs_actual_recovery_scenario(tmp_path, conflict):
    """Relocated fixture authority is explicit, not a copied live checkpoint."""
    import hashlib
    from runtime.wal_generation import WalGeneration, immutable_manifest_digest, seal
    from runtime.wal_transaction import _canonical, _sealed_manifest, WalIntegrityError
    source = tmp_path / 'source'
    source.mkdir()
    _wal, _committed = _real_transactions(source)
    archived = apply(source, keep_latest=2)
    archive_path = Path(archived['archive'])
    # The archive owner has already verified its exact membership and bytes.
    # These tiny fixture bytes are captured once for relocation into a new root.
    import io
    archive_bytes = archive_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        transaction = json.loads(archive.read('aa-second/manifest.json'))
        images = {}
        for artifact in transaction['artifacts']:
            for phase in ('before', 'after'):
                record = artifact[phase]
                if phase == 'before' and not record['exists']:
                    continue
                raw = archive.read('aa-second/' + record['stage'])
                assert hashlib.sha256(raw).hexdigest() == record['sha256']
                images[record['stage']] = raw
    destination = tmp_path / 'reconstructed'
    destination.mkdir()
    journal = destination / 'wal'
    owners = [dict(journal='wal', domains=[dict(path=a['path'], kind='exact') for a in transaction['artifacts']])]
    catalog = WalOwnership.activate(destination, owners)
    wal = JsonWal(journal, destination)
    wal.activate_generation(destination)
    generation = WalGeneration(journal)
    marker = generation._read('marker.json')
    marker = seal({**marker, 'epoch': transaction['generation']['epoch']})
    (generation.root / 'marker.json').write_bytes(_canonical(marker))
    header = seal(dict(schema_version='px.wal-generation/1.0', ownership_sha256=catalog.sha256,
        **transaction['generation'], phase='prepared_effects_possible', transaction_id=transaction['transaction_id'],
        intent_sha256=transaction['intent_sha256'], manifest_binding=immutable_manifest_digest(transaction)))
    if conflict == 'generation':
        header = seal({**header, 'previous_token': 'f' * 64})
    (generation.root / 'head.json').write_bytes(_canonical(header))
    pending = journal / 'transactions' / transaction['transaction_id']
    pending.mkdir(parents=True)
    for name, raw in images.items():
        path = pending / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
    (pending / 'manifest.json').write_bytes(_canonical(_sealed_manifest({**transaction, 'phase': 'prepared'})))
    artifact = transaction['artifacts'][0]
    target = destination / artifact['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(images[artifact['before']['stage']])
    if conflict == 'target':
        target.write_bytes(b'{"conflict":true}')
    before = target.read_bytes()
    provenance = dict(kind='reconstructed recovery-scenario proof', original_checkpoint_restored=False,
        archive_sha256=hashlib.sha256(archive_bytes).hexdigest(), source_manifest_sha256=transaction['manifest_sha256'],
        destination_catalog_sha256=catalog.sha256)
    (destination / 'fixture-provenance.json').write_text(json.dumps(provenance))
    if conflict != 'none':
        with pytest.raises(WalIntegrityError):
            wal.recover()
        assert target.read_bytes() == before
    else:
        wal.recover()
        assert target.read_bytes() == images[artifact['after']['stage']]
        assert generation.read()['phase'] == 'settled_committed'
        assert wal.inspect()['requires_recovery'] is False


def test_new_file_after_archive_verification_is_not_deleted(tmp_path, monkeypatch):
    import scripts.archive_committed_wal as module
    _wal, committed = _real_transactions(tmp_path)
    verify = module._verify_archive
    def add_file(path, manifest):
        verify(path, manifest)
        (committed / 'zz-first/new-user-file.txt').write_text('retain me')
    monkeypatch.setattr(module, '_verify_archive', add_file)
    with pytest.raises(ValueError, match='inventory changed'):
        apply(tmp_path, keep_latest=2)
    assert (committed / 'zz-first/new-user-file.txt').read_text() == 'retain me'
    assert len(list(committed.iterdir())) == 4


def test_interrupted_exact_cleanup_resumes_from_verified_intent(tmp_path, monkeypatch):
    _wal, committed = _real_transactions(tmp_path)
    unlink = Path.unlink
    calls = []
    def interrupt(path, *args, **kwargs):
        if committed in path.parents:
            calls.append(path)
            if len(calls) == 2:
                raise OSError('interrupted cleanup')
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', interrupt)
        with pytest.raises(OSError, match='interrupted cleanup'):
            apply(tmp_path, keep_latest=2)
    intents = list((committed.parent / 'archives').glob('intent-*.json'))
    assert len(intents) == 1
    assert json.loads(intents[0].read_bytes())['state'] == 'cleanup_started'
    result = apply(tmp_path, keep_latest=2)
    assert result['changed'] is True
    assert sorted(p.name for p in committed.iterdir()) == ['bb-fourth', 'mm-third']
    assert json.loads(intents[0].read_bytes())['state'] == 'complete'


def test_late_unarchived_entry_survives_exact_reclamation(tmp_path, monkeypatch):
    import scripts.archive_committed_wal as module
    _wal, committed = _real_transactions(tmp_path)
    reclaim = module.reclaim_archived_inventory
    def add_before_reclaim(root, manifest, **kwargs):
        (committed / 'zz-first/late.txt').write_text('not in archive')
        return reclaim(root, manifest, **kwargs)
    monkeypatch.setattr(module, 'reclaim_archived_inventory', add_before_reclaim)
    with pytest.raises(ValueError, match='unarchived entry'):
        apply(tmp_path, keep_latest=2)
    assert (committed / 'zz-first/late.txt').read_text() == 'not in archive'


@pytest.mark.parametrize('interrupted', [False, True, 'after-files'])
def test_moved_committed_root_link_cannot_redirect_cleanup(tmp_path, monkeypatch, interrupted):
    import scripts.archive_committed_wal as module
    project = tmp_path / 'project'
    project.mkdir()
    _wal, committed = _real_transactions(project)
    if interrupted is True:
        def stop(root, manifest, **kwargs):
            raise OSError('interrupted before cleanup')
        with monkeypatch.context() as patch:
            patch.setattr(module, 'reclaim_archived_inventory', stop)
            with pytest.raises(OSError):
                apply(project, keep_latest=2)
    elif interrupted == 'after-files':
        rmdir = Path.rmdir
        def stop_rmdir(path, *args, **kwargs):
            if committed in path.parents:
                raise OSError('interrupted after exact file cleanup')
            return rmdir(path, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'rmdir', stop_rmdir)
            with pytest.raises(OSError):
                apply(project, keep_latest=2)
    outside = tmp_path / 'outside-project'
    assert outside.absolute().parent == tmp_path.absolute()
    assert tmp_path.absolute() in committed.absolute().parents
    committed.rename(outside)
    try:
        committed.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('directory links are unavailable')
    before = {p.relative_to(outside).as_posix(): p.read_bytes() for p in outside.rglob('*') if p.is_file()}
    directories = sorted(p.relative_to(outside).as_posix() for p in outside.rglob('*') if p.is_dir())
    with pytest.raises((ValueError, RuntimeError)):
        apply(project, keep_latest=2)
    assert {p.relative_to(outside).as_posix(): p.read_bytes() for p in outside.rglob('*') if p.is_file()} == before
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob('*') if p.is_dir()) == directories
