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
    return root / '.engineering-bootstrap/project-map-history'


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
    lock = tmp_path / '.engineering-bootstrap/.project-map.lock'
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
    assert not (tmp_path / '.engineering-bootstrap/.project-map.lock').exists()
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
