from __future__ import annotations

import json
from pathlib import Path
import zipfile
import pytest

from scripts.archive_project_map_history import apply, plan


def test_large_admitted_archive_intent_can_resume(tmp_path, monkeypatch):
    import hashlib
    import scripts.archive_project_map_history as owner
    _maps(tmp_path, 3)
    original_plan = owner._plan_history
    def large_plan(*args, **kwargs):
        result = original_plan(*args, **kwargs)
        result['manifest']['retained_test_metadata'] = 'x' * (1100 * 1024)
        result['manifest_sha256'] = hashlib.sha256(owner._canonical(result['manifest'])).hexdigest()
        return result
    def interrupt(*args, **kwargs):
        raise OSError('interrupt after durable intent')
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_plan_history', large_plan)
        patch.setattr(owner, 'reclaim_archived_inventory', interrupt)
        with pytest.raises(OSError, match='interrupt after durable intent'):
            owner.apply(tmp_path, keep_latest=1)
    assert owner.apply(tmp_path, keep_latest=1)['changed']
    assert owner.plan(tmp_path, keep_latest=1)['selected_count'] == 0


def _maps(root, count):
    from runtime.project_intelligence import build_project_map
    for index in range(count):
        (root / 'app.py').write_text(f'def answer(): return {index}\n', encoding='utf-8')
        result = build_project_map(root)
        assert result['valid']
    return root / '.agentic_engineering_os_px/project-map-history'


@pytest.mark.parametrize('resume', [False, True])
def test_archive_replacement_after_verification_preserves_history_sources(tmp_path, monkeypatch, resume):
    import scripts.archive_project_map_history as owner
    history = _maps(tmp_path, 4)
    if resume:
        def interrupt(*args, **kwargs):
            raise OSError('interrupt before reclamation')
        with monkeypatch.context() as patch:
            patch.setattr(owner, 'reclaim_archived_inventory', interrupt)
            with pytest.raises(OSError, match='interrupt before reclamation'):
                owner.apply(tmp_path, keep_latest=1)
    before = {p.relative_to(history): p.read_bytes() for p in history.rglob('*') if p.is_file()}
    verify = owner._verify_archive

    from tests.support.archive_faults import replace_after_verify

    monkeypatch.setattr(owner, '_verify_archive', replace_after_verify(verify))
    # Fresh history planning may revalidate ancestry before the final digest
    # check. Either refusal must precede any source reclamation.
    with pytest.raises(ValueError):
        owner.apply(tmp_path, keep_latest=1)
    assert {p.relative_to(history): p.read_bytes() for p in history.rglob('*') if p.is_file()} == before


def test_project_map_history_archive_is_verified_and_recoverable(tmp_path: Path) -> None:
    history = _maps(tmp_path, 4)
    dry_run = plan(tmp_path, keep_latest=1)
    assert dry_run["selected_count"] == 2
    assert all(path.is_dir() for path in history.iterdir())
    result = apply(tmp_path, keep_latest=1)
    assert result["changed"] is True
    assert len([path for path in history.iterdir() if path.is_dir()]) == 1
    archive = Path(str(result["archive"]))
    assert archive.is_file()
    with zipfile.ZipFile(archive) as sealed:
        assert sealed.testzip() is None
        assert "MANIFEST.json" in sealed.namelist()
        assert len(sealed.namelist()) == dry_run['manifest']['file_count'] + 1
    receipt = json.loads(Path(str(result["receipt"])).read_text(encoding="utf-8"))
    assert receipt["hard_delete_without_archive"] is False
    assert receipt["archive_sha256"] == result["archive_sha256"]
    assert receipt["reclaimed_bytes"] > 0
    # The surviving oldest receipt points into the verified completed archive.
    assert plan(tmp_path, keep_latest=1)['selected_count'] == 0
    _maps(tmp_path, 1)
    assert apply(tmp_path, keep_latest=1)['changed']
    assert plan(tmp_path, keep_latest=1)['selected_count'] == 0


def test_archive_verifier_rejects_duplicate_manifest_before_payload_read(tmp_path, monkeypatch):
    from scripts.archive_project_map_history import _verify_archive
    path = tmp_path / 'duplicate.zip'
    manifest = {'files': []}
    with pytest.warns(UserWarning, match='Duplicate name'):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('MANIFEST.json', '{}')
            archive.writestr('MANIFEST.json', '{}')
    def unexpected(*args, **kwargs):
        raise AssertionError('payload read before directory admission')
    monkeypatch.setattr(zipfile.ZipFile, 'open', unexpected)
    with pytest.raises(ValueError, match='duplicate archive member'):
        _verify_archive(path, manifest)


def test_archive_verifier_digest_identifies_the_acquired_validated_image(tmp_path, monkeypatch):
    import hashlib
    import runtime.archive_io as archive_io
    import scripts.archive_project_map_history as owner
    path = tmp_path / 'image.zip'
    manifest = {'files': []}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('MANIFEST.json', owner._canonical(manifest) + b'\n')
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    acquire = archive_io.read_archive_bytes

    def replace_after_acquisition(*args, **kwargs):
        image = acquire(*args, **kwargs)
        path.write_bytes(b'unverified replacement')
        return image

    monkeypatch.setattr(archive_io, 'read_archive_bytes', replace_after_acquisition)
    assert owner._verify_archive(path, manifest) == expected
    assert hashlib.sha256(path.read_bytes()).hexdigest() != expected


def test_archive_writer_rejects_changed_source_and_preserves_it(tmp_path):
    from scripts.archive_project_map_history import _write_archive
    history = _maps(tmp_path, 3)
    manifest = plan(tmp_path, keep_latest=1)['manifest']
    source = history / manifest['files'][0]['path']
    source.write_bytes(b'changed after inventory')
    target = tmp_path / 'changed.zip'
    with pytest.raises(ValueError, match='differs from admitted inventory'):
        _write_archive(history, target, manifest)
    assert source.read_bytes() == b'changed after inventory'
    assert not target.exists()


def test_project_map_history_archive_noops_when_only_retained_set_exists(
    tmp_path: Path,
) -> None:
    history = _maps(tmp_path, 2)
    snapshot = next(history.iterdir())
    result = apply(tmp_path, keep_latest=1)
    assert result["changed"] is False
    assert snapshot.is_dir()


def test_map_history_rejects_unlinked_snapshot_without_deleting_it(tmp_path):
    history = _maps(tmp_path, 2)
    unlinked = history / 'unclassified'
    unlinked.mkdir()
    (unlinked / 'user.txt').write_text('preserve')
    with pytest.raises(ValueError, match='outside producer ancestry'):
        apply(tmp_path, keep_latest=1)
    assert (unlinked / 'user.txt').read_text() == 'preserve'


def test_map_history_uses_producer_exclusive_lock(tmp_path):
    _maps(tmp_path, 2)
    lock = tmp_path / '.agentic_engineering_os_px/.project-map.lock'
    lock.write_text('existing producer custody')
    with pytest.raises(FileExistsError):
        apply(tmp_path, keep_latest=1)
    assert lock.read_text() == 'existing producer custody'


def test_map_history_interrupted_cleanup_resumes_and_preserves_ancestry(tmp_path, monkeypatch):
    history = _maps(tmp_path, 4)
    unlink = Path.unlink
    count = 0
    def stop(path, *args, **kwargs):
        nonlocal count
        if history in path.parents:
            count += 1
            if count == 3:
                raise OSError('interrupted map cleanup')
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', stop)
        with pytest.raises(OSError, match='interrupted map cleanup'):
            apply(tmp_path, keep_latest=1)
    assert not (tmp_path / '.agentic_engineering_os_px/.project-map.lock').exists()
    result = apply(tmp_path, keep_latest=1)
    assert result['changed']
    assert plan(tmp_path, keep_latest=1)['selected_count'] == 0


def test_corrupt_historical_payload_refuses_before_archive_effects(tmp_path):
    history = _maps(tmp_path, 4)
    selected = Path(plan(tmp_path, keep_latest=1)['selected_paths'][0])
    receipt = json.loads((selected / 'map-receipt.json').read_bytes())
    payload = selected / next(iter(receipt['file_sha256']))
    payload.write_bytes(b'corrupt retained payload')
    before = {p.relative_to(history).as_posix(): p.read_bytes() for p in history.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='payload differs from producer receipt'):
        apply(tmp_path, keep_latest=1)
    assert {p.relative_to(history).as_posix(): p.read_bytes() for p in history.rglob('*') if p.is_file()} == before


def test_restored_history_is_consumed_without_current_freshness_promotion(tmp_path):
    import hashlib
    from runtime.project_intelligence import validate_project_map, diff_project_maps
    _maps(tmp_path, 4)
    manifest = plan(tmp_path, keep_latest=1)['manifest']
    selected = manifest['archived_snapshots'][0]
    result = apply(tmp_path, keep_latest=1)
    restored = tmp_path / 'restored-historical-map'
    restored.mkdir()
    with zipfile.ZipFile(result['archive']) as archive:
        for row in manifest['files']:
            if row['path'].startswith(selected + '/'):
                raw = archive.read(row['path'])
                assert hashlib.sha256(raw).hexdigest() == row['sha256']
                output = restored / row['path'][len(selected) + 1:]
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(raw)
    historical = validate_project_map(restored, check_freshness=False)
    assert historical['valid'], historical
    difference = diff_project_maps(restored, tmp_path)
    assert difference['valid'] and 'app.py' in difference['files']['changed']
    assert not validate_project_map(restored, check_freshness=True)['valid']


# --- G09: check-to-reclamation custody window ---------------------------------


def _history_snapshot(history):
    return {p.relative_to(history): p.read_bytes() for p in history.rglob('*') if p.is_file()}


def _history_case(tmp_path, monkeypatch, history, mutator):
    import scripts.archive_project_map_history as owner
    seen = []
    original = owner.reclaim_archived_inventory

    def armed(root, manifest, **kwargs):
        def act():
            archives = list((tmp_path / '.agentic_engineering_os_px'
                             / 'project-map-history-archives').glob('*.zip'))
            assert archives, 'expected a verified archive in custody'
            if not seen:
                seen.append(archives[0])
                mutator(archives[0])
        return original(root, manifest, custody_check=act, **kwargs)

    monkeypatch.setattr(owner, 'reclaim_archived_inventory', armed)
    with pytest.raises(ValueError, match='archive custody image|archive cleanup|project history'):
        owner.apply(tmp_path, keep_latest=1)
    assert seen, 'the custody interval was never reached; the test proved nothing'


def test_history_archive_replaced_inside_reclamation_interval_preserves_sources(tmp_path, monkeypatch):
    history = _maps(tmp_path, 4)
    before = _history_snapshot(history)
    _history_case(tmp_path, monkeypatch, history,
                  lambda archive: archive.write_bytes(b'not the verified recovery archive'))
    assert _history_snapshot(history) == before
    assert len([p for p in history.iterdir() if p.is_dir()]) == 3


def test_history_archive_written_in_place_inside_reclamation_interval_preserves_sources(tmp_path, monkeypatch):
    history = _maps(tmp_path, 4)
    before = _history_snapshot(history)

    from tests.support.archive_faults import flip_one_byte

    _history_case(tmp_path, monkeypatch, history, flip_one_byte)
    assert _history_snapshot(history) == before


def test_history_archive_renamed_away_inside_reclamation_interval_preserves_sources(tmp_path, monkeypatch):
    history = _maps(tmp_path, 4)
    before = _history_snapshot(history)
    _history_case(tmp_path, monkeypatch, history,
                  lambda archive: archive.rename(archive.with_name(archive.name + '.displaced')))
    assert _history_snapshot(history) == before


def test_history_archive_replaced_during_resume_refuses(tmp_path, monkeypatch):
    import scripts.archive_project_map_history as owner
    history = _maps(tmp_path, 4)

    def interrupt(root, manifest, **kwargs):
        raise OSError('interrupt before reclamation')

    with monkeypatch.context() as patch:
        patch.setattr(owner, 'reclaim_archived_inventory', interrupt)
        with pytest.raises(OSError, match='interrupt before reclamation'):
            owner.apply(tmp_path, keep_latest=1)

    archives = list((tmp_path / '.agentic_engineering_os_px'
                     / 'project-map-history-archives').glob('*.zip'))
    assert len(archives) == 1
    archives[0].write_bytes(b'replaced between runs')
    before = _history_snapshot(history)
    with pytest.raises(ValueError):
        owner.apply(tmp_path, keep_latest=1)
    assert _history_snapshot(history) == before
