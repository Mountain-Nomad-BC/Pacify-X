"""Recoverably archive superseded project-map snapshots.

Dry-run is the default.  Apply mode writes and verifies a deterministic ZIP
before reclaiming only the exact archived snapshot directories.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
import time


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ARCHIVE_INTENT_BYTES = 8 * 1024 * 1024


def _archive_intent_bytes(value):
    from runtime.json_io import bounded_canonical_json_bytes
    return bounded_canonical_json_bytes(value, max_bytes=ARCHIVE_INTENT_BYTES)


def _read_archive_intent(path):
    from runtime.json_io import decode_json_object
    from runtime.wal_transaction import _bounded_image
    return decode_json_object(_bounded_image(path, limit=ARCHIVE_INTENT_BYTES),
                              max_bytes=ARCHIVE_INTENT_BYTES)


def _new_archive_intent(schema, manifest, digest, filename):
    value = dict(schema_version=schema, state='cleanup_started', manifest=manifest,
                 manifest_sha256=digest, archive=filename, archive_sha256='0' * 64)
    # The actual archive hash has the same fixed width. Admit the complete
    # recovery envelope before creating an archive or reclaiming any source.
    _archive_intent_bytes(value)
    return value


def _inventory_root_identity(root, expected=None):
    from runtime.wal_transaction import _reject_nominal_link_chain
    root = Path(os.path.abspath(root))
    _reject_nominal_link_chain(root, Path(root.anchor), label='archive authority root')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('archive authority root is not a directory')
    identity = {'device': info.st_dev, 'inode': info.st_ino}
    if expected is not None and identity != expected:
        raise ValueError('archive authority root generation changed')
    return identity


def bounded_inventory(root: Path, selected: list[Path]) -> dict[str, object]:
    """Capture exact files and directories for an owned archive disposition."""
    from runtime.wal_transaction import _bounded_image, _reject_nominal_link_chain
    root_identity = _inventory_root_identity(root)
    files, directories = [], []
    pending = list(selected)
    entries = 0
    total = 0
    deadline = time.monotonic() + 60
    while pending:
        path = pending.pop()
        entries += 1
        if entries > 8192 or time.monotonic() >= deadline:
            raise ValueError('archive inventory traversal budget exceeded')
        _reject_nominal_link_chain(path, root, label='archive inventory')
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        identity = {'device': info.st_dev, 'inode': info.st_ino}
        if stat.S_ISDIR(info.st_mode):
            directories.append({'path': relative, 'identity': identity})
            with os.scandir(path) as children:
                for child in children:
                    if len(pending) + entries >= 8192:
                        raise ValueError('archive inventory entry budget exceeded')
                    pending.append(Path(child.path))
        elif stat.S_ISREG(info.st_mode):
            if len(files) >= 4096 or info.st_nlink != 1:
                raise ValueError('archive file count or physical ownership is invalid')
            raw = _bounded_image(path, limit=min(64 * 1024 * 1024, 256 * 1024 * 1024 - total))
            total += len(raw)
            files.append({'path': relative, 'identity': identity, 'size_bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest()})
        else:
            raise ValueError('archive inventory contains a nonregular entry')
    _inventory_root_identity(root, root_identity)
    return {'root_identity': root_identity, 'files': sorted(files, key=lambda row: row['path']),
            'directories': sorted(directories, key=lambda row: row['path'])}


def reclaim_archived_inventory(root: Path, manifest, *, resume=False):
    """Remove only still-identical archived entries; never recursively delete.

    A late unknown file is left in place, and rmdir fails rather than deleting it.
    The caller retains a verified archive and durable cleanup intent first.
    """
    from runtime.wal_transaction import _bounded_image, _reject_nominal_link_chain
    root_identity = manifest.get('root_identity')
    if type(root_identity) is not dict or set(root_identity) != {'device', 'inode'}:
        raise ValueError('archive cleanup has no source root identity')
    _inventory_root_identity(root, root_identity)
    if (type(manifest.get('files')) is not list or len(manifest['files']) > 4096
            or type(manifest.get('directories')) is not list or len(manifest['directories']) > 8192):
        raise ValueError('invalid bounded archive cleanup inventory')
    rows = [*manifest['files'], *manifest['directories']]
    # Validate the entire surviving set before any deletion. On resume, absence
    # is an already-applied cleanup effect, not permission to adopt new entries.
    expected = {}
    for row in rows:
        name = row.get('path')
        if (type(name) is not str or not name or name == '.' or Path(name).is_absolute()
                or '..' in Path(name).parts or Path(name).as_posix() != name
                or name in expected or len(name.encode('utf-8')) > 4096):
            raise ValueError('noncanonical or duplicate archive cleanup path')
        identity = row.get('identity')
        if (type(identity) is not dict or set(identity) != {'device', 'inode'}
                or any(type(value) is not int or value < 0 for value in identity.values())):
            raise ValueError('invalid archive physical identity')
        if 'sha256' in row and (type(row.get('size_bytes')) is not int or not 0 <= row['size_bytes'] <= 64 * 1024 * 1024):
            raise ValueError('invalid archived size')
        expected[name] = row
    for row in rows:
        _inventory_root_identity(root, root_identity)
        path = root / row['path']
        _reject_nominal_link_chain(path, root, label='archive cleanup')
        if not path.exists():
            if resume:
                continue
            raise ValueError('archive cleanup source disappeared')
        info = path.lstat()
        if {'device': info.st_dev, 'inode': info.st_ino} != row['identity']:
            raise ValueError('archive cleanup source generation changed')
        if 'sha256' in row:
            raw = _bounded_image(path, limit=row['size_bytes'])
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('archive cleanup source bytes changed')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('archive cleanup directory changed type')
    for row in manifest['directories']:
        _inventory_root_identity(root, root_identity)
        directory = root / row['path']
        if directory.exists():
            with os.scandir(directory) as entries:
                for entry in entries:
                    if Path(entry.path).relative_to(root).as_posix() not in expected:
                        raise ValueError('archive cleanup contains an unarchived entry')
    for row in manifest['files']:
        _inventory_root_identity(root, root_identity)
        path = root / row['path']
        if path.exists():
            # Repeat identity/content checks immediately before the exact unlink.
            info = path.lstat()
            if {'device': info.st_dev, 'inode': info.st_ino} != row['identity'] or _is_reparse(path):
                raise ValueError('archive cleanup source changed before unlink')
            raw = _bounded_image(path, limit=row['size_bytes'])
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('archive cleanup bytes changed before unlink')
            path.unlink()
    for row in sorted(manifest['directories'], key=lambda item: len(Path(item['path']).parts), reverse=True):
        _inventory_root_identity(root, root_identity)
        path = root / row['path']
        if path.exists():
            info = path.lstat()
            if {'device': info.st_dev, 'inode': info.st_ino} != row['identity'] or _is_reparse(path):
                raise ValueError('archive cleanup directory changed before rmdir')
            path.rmdir()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    value = path.lstat()
    return path.is_symlink() or bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _receipt_image(path):
    from runtime.wal_transaction import _bounded_image
    from runtime.json_io import decode_json_object
    from runtime.project_intelligence import _stable_hash
    raw = _bounded_image(path, limit=1024 * 1024)
    value = decode_json_object(raw, max_bytes=1024 * 1024)
    body = {k: v for k, v in value.items() if k != 'receipt_sha256'}
    if value.get('promotion') != 'promoted' or value.get('receipt_sha256') != _stable_hash(body):
        raise ValueError('project-map history has no valid promoted producer receipt')
    return raw, value


def _archived_boundary(root, name):
    archive_root = root / '.engineering-bootstrap/project-map-history-archives'
    if not archive_root.exists():
        return False
    _inventory_root_identity(archive_root)
    count = 0
    with os.scandir(archive_root) as entries:
        for entry in entries:
            count += 1
            if count > 10000:
                raise ValueError('project history archive lookup bound exceeded')
            if not (entry.name.startswith('intent-') and entry.name.endswith('.json')):
                continue
            intent = _read_archive_intent(Path(entry.path))
            manifest = intent.get('manifest', {})
            if intent.get('state') != 'complete' or name not in manifest.get('archived_snapshots', []):
                continue
            if hashlib.sha256(_canonical(manifest)).hexdigest() != intent.get('manifest_sha256'):
                raise ValueError('project history archive boundary manifest changed')
            locator = intent.get('archive')
            if type(locator) is not str or Path(locator).name != locator:
                raise ValueError('project history archive boundary locator is invalid')
            archive = archive_root / locator
            if _sha256(archive) != intent.get('archive_sha256'):
                raise ValueError('project history archive boundary bytes changed')
            _verify_archive(archive, manifest)
            return True
    return False


def _plan_history(root, keep_latest, *, producer_lock_held=False):
    from runtime.wal_transaction import _reject_nominal_link_chain
    if type(keep_latest) is not int or not 1 <= keep_latest <= 20:
        raise ValueError('keep_latest must be an actual integer between 1 and 20')
    root = Path(os.path.abspath(root))
    _inventory_root_identity(root)
    history = root / '.engineering-bootstrap/project-map-history'
    _inventory_root_identity(history)
    lock = root / '.engineering-bootstrap/.project-map.lock'
    if not producer_lock_held and lock.exists():
        raise ValueError('project-map producer is active or requires recovery')
    head_path = root / '.engineering-bootstrap/project-map/map-receipt.json'
    head_raw, receipt = _receipt_image(head_path)
    present = {}
    with os.scandir(history) as entries:
        for entry in entries:
            if len(present) >= 10000 or not entry.is_dir(follow_symlinks=False) or _is_reparse(Path(entry.path)):
                raise ValueError('project history inventory is unclassified or exceeds bound')
            present[entry.name] = Path(entry.path)
    ordered = []
    receipts = {}
    seen = set()
    while receipt.get('archived_previous') is not None:
        locator = receipt['archived_previous']
        if type(locator) is not str:
            raise ValueError('project history predecessor is not a path')
        previous = Path(locator)
        if not previous.is_absolute() or previous.parent != history or '..' in previous.parts:
            raise ValueError('project history predecessor escapes producer history')
        _reject_nominal_link_chain(previous, root, label='project history predecessor')
        if previous.name in seen or len(seen) >= 10000:
            raise ValueError('project history ancestry is cyclic or exceeds bound')
        seen.add(previous.name)
        if previous.name not in present:
            if not _archived_boundary(root, previous.name):
                raise ValueError('project history ancestry has an unproved missing predecessor')
            break
        ordered.append(previous)
        _raw, receipt = _receipt_image(previous / 'map-receipt.json')
        receipts[previous.name] = (_raw, receipt)
    if {p.name for p in ordered} != set(present):
        raise ValueError('project history contains snapshots outside producer ancestry')
    selected = ordered[keep_latest:]
    inventory = bounded_inventory(history, selected)
    acquired = {row['path']: row['sha256'] for row in inventory['files']}
    for snapshot in selected:
        raw, receipt = receipts[snapshot.name]
        if acquired.get(snapshot.name + '/map-receipt.json') != hashlib.sha256(raw).hexdigest():
            raise ValueError('project-map producer receipt changed during inventory')
        commitments = receipt.get('file_sha256')
        if type(commitments) is not dict or not commitments or len(commitments) > 4096:
            raise ValueError('project-map producer payload commitments are missing or unbounded')
        for name, digest in commitments.items():
            from runtime.archive_io import portable_member_name
            portable_member_name(name, allow_directory=False)
            if acquired.get(snapshot.name + '/' + name) != digest:
                raise ValueError('project-map payload differs from producer receipt')
    if _receipt_image(head_path)[0] != head_raw or (not producer_lock_held and lock.exists()):
        raise ValueError('project-map producer generation changed during planning')
    manifest = dict(schema_version='px.project-map-history-archive-manifest/2.0',
        history_root='.engineering-bootstrap/project-map-history',
        producer_head_sha256=hashlib.sha256(head_raw).hexdigest(),
        chronology='linked-promoted-producer-receipts',
        retained_live_snapshots=[p.name for p in ordered[:keep_latest]],
        archived_snapshots=[p.name for p in selected],
        file_count=len(inventory['files']), size_bytes=sum(row['size_bytes'] for row in inventory['files']), **inventory)
    return dict(valid=True, apply=False, manifest=manifest,
        manifest_sha256=hashlib.sha256(_canonical(manifest)).hexdigest(), selected_count=len(selected),
        selected_paths=[p.as_posix() for p in selected])


def plan(root: Path, *, keep_latest: int = 2):
    return _plan_history(root, keep_latest)


def _write_archive(history: Path, target: Path, manifest: dict[str, object]) -> None:
    from runtime.archive_io import BoundedArchiveWriter, reject_path_links
    from runtime.wal_transaction import _bounded_image
    expected, manifest_bytes = _archive_manifest(manifest)
    _inventory_root_identity(history, manifest['root_identity'])
    reject_path_links(target)
    temporary = target.with_suffix(".zip.prepared")
    if temporary.exists() or target.exists():
        raise ValueError("prepared project-map archive already exists")
    with temporary.open('xb') as stream, zipfile.ZipFile(
        BoundedArchiveWriter(stream, 272 * 1024 * 1024),
        "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=False
    ) as archive:
        manifest_info = zipfile.ZipInfo("MANIFEST.json", FIXED_ZIP_TIME)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(manifest_info, manifest_bytes)
        for name, row in expected.items():
            source = history / name
            _inventory_root_identity(history, manifest['root_identity'])
            reject_path_links(source)
            before = source.lstat()
            raw = _bounded_image(source, limit=64 * 1024 * 1024)
            after = source.lstat()
            if ({'device': before.st_dev, 'inode': before.st_ino} != row['identity']
                    or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                    or before.st_nlink != 1 or after.st_nlink != 1
                    or len(raw) != row['size_bytes']
                    or hashlib.sha256(raw).hexdigest() != row['sha256']):
                raise ValueError('archive source differs from admitted inventory')
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    _verify_archive(temporary, manifest)
    os.replace(temporary, target)


def _archive_manifest(manifest):
    from runtime.archive_io import member_identity, portable_member_name
    rows = manifest.get('files')
    if type(rows) is not list or len(rows) > 4096:
        raise ValueError('archive manifest file denominator is invalid')
    expected, identities, total = {}, {'manifest.json'}, 0
    for row in rows:
        name = portable_member_name(row['path'], allow_directory=False)
        identity = member_identity(name, allow_directory=False)
        size = row['size_bytes']
        digest = row['sha256']
        if (identity in identities or type(size) is not int or not 0 <= size <= 64 * 1024 * 1024
                or type(digest) is not str or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('archive manifest member is invalid')
        total += size
        if total > 256 * 1024 * 1024:
            raise ValueError('archive manifest aggregate byte budget exceeded')
        identities.add(identity)
        expected[name] = row
    raw = _canonical(manifest) + b'\n'
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('archive manifest byte budget exceeded')
    return expected, raw


def _verify_archive(path: Path, manifest: dict[str, object]) -> None:
    from runtime.archive_io import ArchiveLimits, read_archive_bytes, read_stream_bytes, validated_zip
    expected, manifest_bytes = _archive_manifest(manifest)
    limits = ArchiveLimits(max_archive_bytes=272 * 1024 * 1024,
        max_expanded_bytes=260 * 1024 * 1024, max_member_bytes=64 * 1024 * 1024,
        max_members=4097)
    with validated_zip(read_archive_bytes(path, limits), limits) as (archive, infos):
        if {info.filename for info in infos} != {*expected, 'MANIFEST.json'}:
            raise ValueError("project-map archive membership verification failed")
        with archive.open('MANIFEST.json') as stream:
            stored_manifest = read_stream_bytes(stream, max_bytes=4 * 1024 * 1024,
                expected_size=len(manifest_bytes))
        if stored_manifest != manifest_bytes:
            raise ValueError("project-map archive manifest verification failed")
        for name, row in expected.items():
            with archive.open(name) as stream:
                raw = read_stream_bytes(stream, max_bytes=64 * 1024 * 1024,
                    expected_size=row['size_bytes'])
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError(f"project-map archive member hash mismatch: {name}")


def apply(root: Path, *, keep_latest: int = 2):
    from runtime.wal_transaction import _atomic_replace, _reject_nominal_link_chain, _write_new, _attach_outcome
    from runtime.json_io import decode_json_object
    from runtime.wal_transaction import _bounded_image
    import uuid
    root = Path(os.path.abspath(root))
    _inventory_root_identity(root)
    if type(keep_latest) is not int or not 1 <= keep_latest <= 20:
        raise ValueError('keep_latest must be an actual bounded integer')
    control = root / '.engineering-bootstrap'
    history = control / 'project-map-history'
    _inventory_root_identity(history)
    lock = control / '.project-map.lock'
    _reject_nominal_link_chain(lock, root, label='project map producer lock')
    run_id = 'archive-' + uuid.uuid4().hex
    # Use the producer's existing exclusive-create protocol. FileLock would
    # leave this sentinel present and permanently block its open("x") producer.
    _write_new(lock, _canonical(dict(schema_version='1.0', run_id=run_id,
        project=root.as_posix(), output=(control / 'project-map').as_posix(),
        created_utc=datetime.now(timezone.utc).isoformat(), pid=os.getpid(), operation='archive-history')))
    lock_info = lock.lstat()
    lock_identity = (lock_info.st_dev, lock_info.st_ino)
    try:
        archive_root = control / 'project-map-history-archives'
        _reject_nominal_link_chain(archive_root, root, label='project history archive root')
        pending = []
        if archive_root.exists():
            with os.scandir(archive_root) as entries:
                count = 0
                for entry in entries:
                    count += 1
                    if count > 10000:
                        raise ValueError('project history disposition bound exceeded')
                    if entry.name.startswith('intent-') and entry.name.endswith('.json'):
                        p = Path(entry.path)
                        value = _read_archive_intent(p)
                        if value.get('state') != 'complete':
                            pending.append((p, value))
                            if len(pending) > 1:
                                raise ValueError('multiple pending project history dispositions')
        if pending:
            intent_path, intent = pending[0]
            if (intent.get('schema_version') != 'px.project-history-intent/1.0' or intent.get('state') != 'cleanup_started'):
                raise ValueError('invalid project history disposition')
            manifest = intent['manifest']
            digest = hashlib.sha256(_canonical(manifest)).hexdigest()
            if digest != intent['manifest_sha256'] or manifest['history_root'] != '.engineering-bootstrap/project-map-history':
                raise ValueError('project history disposition binding mismatch')
            locator = intent['archive']
            if type(locator) is not str or Path(locator).name != locator:
                raise ValueError('invalid project history archive locator')
            target = archive_root / locator
            if _sha256(target) != intent['archive_sha256']:
                raise ValueError('project history archive bytes changed')
            _verify_archive(target, manifest)
            decision = dict(valid=True, apply=False, manifest=manifest, manifest_sha256=digest, selected_count=len(manifest['archived_snapshots']))
        else:
            decision = _plan_history(root, keep_latest, producer_lock_held=True)
            manifest = decision['manifest']
            if not manifest['archived_snapshots']:
                return {**decision, 'apply': True, 'changed': False}
            digest = decision['manifest_sha256']
            archive_root.mkdir(exist_ok=True)
            target = archive_root / ('project-map-history-' + digest + '.zip')
            intent = _new_archive_intent('px.project-history-intent/1.0', manifest, digest, target.name)
            if not target.exists():
                _write_archive(history, target, manifest)
            _verify_archive(target, manifest)
            selected = [history / name for name in manifest['archived_snapshots']]
            if bounded_inventory(history, selected) != {key: manifest[key] for key in ('root_identity', 'files', 'directories')}:
                raise ValueError('project history changed after archive verification')
            if hashlib.sha256(_receipt_image(control / 'project-map/map-receipt.json')[0]).hexdigest() != manifest['producer_head_sha256']:
                raise ValueError('project map head changed before history cleanup')
            intent['archive_sha256'] = _sha256(target)
            intent_path = archive_root / ('intent-' + digest + '.json')
            _write_new(intent_path, _archive_intent_bytes(intent))
        reclaim_archived_inventory(history, manifest, resume=bool(pending))
        receipt = dict(schema_version='px.project-map-history-archive-receipt/2.0',
            created_utc=datetime.now(timezone.utc).isoformat(), archive=target.relative_to(root).as_posix(),
            archive_sha256=intent['archive_sha256'], manifest_sha256=digest,
            archived_snapshots=manifest['archived_snapshots'], retained_live_snapshots=manifest['retained_live_snapshots'],
            file_count=manifest['file_count'], source_size_bytes=manifest['size_bytes'], archive_size_bytes=target.stat().st_size,
            reclaimed_bytes=manifest['size_bytes'] - target.stat().st_size,
            recovery='Verify retained archive digest and manifest before restoring the named history snapshots.',
            hard_delete_without_archive=False, cleanup_complete=True)
        receipt_path = control / 'cleanup-receipts' / ('project-map-history-' + digest + '.json')
        _atomic_replace(receipt_path, _canonical(receipt), label='history-cleanup-receipt', fault_injector=None)
        _atomic_replace(intent_path, _archive_intent_bytes({**intent, 'state': 'complete'}), label='history-cleanup-complete', fault_injector=None)
        return {**decision, 'apply': True, 'changed': True, 'archive': target.as_posix(),
                'archive_sha256': intent['archive_sha256'], 'archive_size_bytes': target.stat().st_size,
                'reclaimed_bytes': receipt['reclaimed_bytes'], 'receipt': receipt_path.as_posix()}
    finally:
        import sys
        original = sys.exc_info()[1]
        try:
            _reject_nominal_link_chain(lock, root, label='project map lock custody')
            current = lock.lstat()
            retained_value = decode_json_object(_bounded_image(lock, limit=4096), max_bytes=4096)
            if (current.st_dev, current.st_ino) != lock_identity or retained_value.get('run_id') != run_id:
                raise ValueError('project map archive lock generation changed')
            retained_lock = control / 'project-map-lock-history' / (run_id + '.json')
            _reject_nominal_link_chain(retained_lock, root, label='project map lock history')
            retained_lock.parent.mkdir(exist_ok=True)
            if retained_lock.exists():
                raise ValueError('project map lock custody destination already exists')
            os.replace(lock, retained_lock)
        except BaseException as cleanup_error:
            if original is None:
                raise
            _attach_outcome(original, 'archive_lock_custody', {'closed': False, 'error_type': type(cleanup_error).__name__})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--keep-latest", type=int, default=2)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        apply(args.root, keep_latest=args.keep_latest)
        if args.apply
        else plan(args.root, keep_latest=args.keep_latest)
    )
    bounded = {key: value for key, value in result.items() if key != "manifest"}
    print(json.dumps(bounded, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
