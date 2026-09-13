"""Hash-seal and reclaim superseded committed JSON-WAL transaction folders."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.archive_project_map_history import (
    _archive_intent_bytes,
    _read_archive_intent,
    _new_archive_intent,
    _canonical,
    _is_reparse,
    _sha256,
    _verify_archive,
    _write_archive,
    bounded_inventory,
    reclaim_archived_inventory,
)


MAX_HASH_WORKERS = 8


def _journal(root, wal_root):
    from runtime.wal_transaction import JsonWal, _reject_nominal_link_chain
    root = Path(os.path.abspath(root))
    _reject_nominal_link_chain(root, Path(root.anchor), label='archive project root')
    root = root.resolve(strict=True)
    nominal = wal_root if wal_root.is_absolute() else root / wal_root
    if '..' in nominal.parts:
        raise ValueError('WAL root contains parent traversal')
    _reject_nominal_link_chain(nominal, root, label='archive WAL root')
    journal = nominal.resolve(strict=True)
    _reject_nominal_link_chain(journal / 'committed', root, label='committed archive root')
    _reject_nominal_link_chain(journal / 'archives', root, label='archive custody root')
    relative = journal.relative_to(root)
    if journal.name not in {'wal', '.wal'} or '.engineering-bootstrap' not in relative.parts:
        raise ValueError('WAL root is not an admitted PX journal')
    return root, JsonWal(journal, root)


def _hash_inventory(committed, transactions):
    return bounded_inventory(committed, transactions)['files']


def _plan(root, wal, keep_latest):
    from runtime.wal_transaction import _validate_manifest, _bounded_image
    from runtime.json_io import decode_json_object
    if type(keep_latest) is not int or not 1 <= keep_latest <= 10000:
        raise ValueError('keep_latest must be an actual integer between 1 and 10000')
    protocol = wal._generation_protocol()
    if protocol is None:
        raise ValueError('legacy WAL has no authoritative chronology; retain it for explicit migration')
    token = wal.capture_generation()
    head = protocol[2]
    committed = wal.journal_root / 'committed'
    transactions = []
    prepared = {}
    sequences = set()
    with os.scandir(committed) as entries:
        for entry in entries:
            if len(transactions) >= 10000:
                raise ValueError('committed transaction inventory exceeds bound')
            path = Path(entry.path)
            if _is_reparse(path) or not entry.is_dir(follow_symlinks=False):
                raise ValueError('committed WAL contains an unclassified entry')
            raw = _bounded_image(path / 'manifest.json', limit=1024 * 1024)
            manifest = _validate_manifest(decode_json_object(raw, max_bytes=1024 * 1024), path.name)
            prepared[path.name] = (manifest, hashlib.sha256(raw).hexdigest())
            generation = manifest.get('generation')
            if (manifest['phase'] != 'committed' or not generation
                    or generation['epoch'] != head['epoch']
                    or generation['sequence'] > head['sequence']
                    or generation['sequence'] in sequences):
                raise ValueError('committed WAL has unknown or conflicting chronology')
            sequences.add(generation['sequence'])
            transactions.append((generation['sequence'], path))
    transactions.sort(key=lambda row: row[0])
    selected = [path for _sequence, path in transactions[:-keep_latest]]
    inventory = bounded_inventory(committed, selected)
    # Reuse the acquired inventory hashes: preserve transaction semantics as
    # well as archive-byte custody, without rereading historical payload bodies.
    files = {row['path']: row for row in inventory['files']}
    for path in selected:
        transaction, manifest_digest = prepared[path.name]
        if files.get(path.name + '/manifest.json', {}).get('sha256') != manifest_digest:
            raise ValueError('transaction manifest changed during archive acquisition')
        for artifact in transaction['artifacts']:
            for phase in ('before', 'after'):
                image = artifact[phase]
                if phase == 'before' and not image['exists']:
                    continue
                if files.get(path.name + '/' + image['stage'], {}).get('sha256') != image['sha256']:
                    raise ValueError('archived payload differs from transaction manifest')
    if wal.capture_generation() != token:
        raise ValueError('producer generation changed during archive planning')
    manifest = dict(schema_version='px.committed-wal-archive-manifest/2.0',
        wal_root=wal.journal_root.relative_to(root).as_posix(), generation=head,
        retained_live_transactions=[path.name for _sequence, path in transactions[-keep_latest:]],
        archived_transactions=[path.name for path in selected],
        file_count=len(inventory['files']), size_bytes=sum(row['size_bytes'] for row in inventory['files']),
        **inventory)
    return dict(valid=True, apply=False, manifest=manifest,
                manifest_sha256=hashlib.sha256(_canonical(manifest)).hexdigest(), selected_count=len(selected))


def plan(root, *, wal_root=Path('.engineering-bootstrap/operation-bus/wal'), keep_latest=200):
    root, wal = _journal(root, wal_root)
    return _plan(root, wal, keep_latest)


def _publish(path, value):
    from runtime.wal_transaction import _atomic_replace, _reject_nominal_link_chain
    _reject_nominal_link_chain(path, Path(path.anchor), label='archive custody publication')
    _atomic_replace(path, _archive_intent_bytes(value), label='archive-custody', fault_injector=None)


def _pending_intent(archive_root):
    found = []
    if not archive_root.exists():
        return None
    count = 0
    with os.scandir(archive_root) as entries:
        for entry in entries:
            count += 1
            if count > 30000:
                raise ValueError('archive custody inventory bound exceeded')
            if entry.name.startswith('intent-') and entry.name.endswith('.json'):
                path = Path(entry.path)
                value = _read_archive_intent(path)
                if value.get('state') != 'complete':
                    found.append((path, value))
                    if len(found) > 1:
                        raise ValueError('multiple unresolved archive dispositions require recovery')
    return found[0] if found else None


def apply(root, *, wal_root=Path('.engineering-bootstrap/operation-bus/wal'), keep_latest=200):
    from runtime.wal_transaction import _wal_lock
    root, wal = _journal(root, wal_root)
    if type(keep_latest) is not int or not 1 <= keep_latest <= 10000:
        raise ValueError('keep_latest must be an actual bounded integer')
    # Producer exclusion spans selection, archive verification, intent and
    # exact-entry reclamation. No live invocation is implicit in this helper.
    with _wal_lock(wal._lock_path, wal.lock_timeout_seconds):
        token = wal.capture_generation()
        if token is None:
            raise ValueError('legacy WAL has no authoritative chronology')
        archive_root = wal.journal_root / 'archives'
        pending = _pending_intent(archive_root)
        if pending:
            intent_path, intent = pending
            if (set(intent) != {'schema_version', 'state', 'manifest', 'manifest_sha256', 'archive', 'archive_sha256'}
                    or intent['schema_version'] != 'px.wal-archive-intent/1.0'
                    or intent['state'] != 'cleanup_started'):
                raise ValueError('invalid retained archive disposition')
            manifest = intent['manifest']
            digest = hashlib.sha256(_canonical(manifest)).hexdigest()
            if digest != intent['manifest_sha256'] or manifest['wal_root'] != wal.journal_root.relative_to(root).as_posix():
                raise ValueError('archive disposition binding mismatch')
            head = wal._generation_protocol()[2]
            if head['epoch'] != manifest['generation']['epoch'] or head['sequence'] < manifest['generation']['sequence']:
                raise ValueError('archive disposition is outside the current producer epoch')
            name = intent['archive']
            if type(name) is not str or Path(name).name != name or not name.endswith('.zip'):
                raise ValueError('invalid archive locator')
            target = archive_root / name
            if _sha256(target) != intent['archive_sha256']:
                raise ValueError('retained archive bytes changed')
            _verify_archive(target, manifest)
            decision = dict(valid=True, apply=False, manifest=manifest, manifest_sha256=digest,
                            selected_count=len(manifest['archived_transactions']))
        else:
            decision = _plan(root, wal, keep_latest)
            manifest = decision['manifest']
            if not manifest['archived_transactions']:
                return {**decision, 'apply': True, 'changed': False}
            archive_root.mkdir(parents=True, exist_ok=True)
            digest = decision['manifest_sha256']
            target = archive_root / ('committed-' + digest + '.zip')
            intent = _new_archive_intent('px.wal-archive-intent/1.0', manifest, digest, target.name)
            if target.exists():
                _verify_archive(target, manifest)
            else:
                _write_archive(wal.journal_root / 'committed', target, manifest)
                _verify_archive(target, manifest)
            selected = [wal.journal_root / 'committed' / name for name in manifest['archived_transactions']]
            if bounded_inventory(wal.journal_root / 'committed', selected) != {key: manifest[key] for key in ('root_identity', 'files', 'directories')}:
                raise ValueError('source inventory changed after archive verification')
            intent['archive_sha256'] = _sha256(target)
            intent_path = archive_root / ('intent-' + digest + '.json')
            if intent_path.exists():
                raise ValueError('archive disposition already exists')
            _publish(intent_path, intent)
        # The verified archive and durable intent precede every unlink. A
        # resumed partial cleanup accepts only original surviving identities.
        reclaim_archived_inventory(wal.journal_root / 'committed', manifest, resume=bool(pending))
        receipt = dict(schema_version='px.committed-wal-archive-receipt/2.0',
            created_utc=datetime.now(timezone.utc).isoformat(), wal_root=manifest['wal_root'],
            archive=target.relative_to(root).as_posix(), archive_sha256=intent['archive_sha256'],
            manifest_sha256=decision['manifest_sha256'], archived_transactions=manifest['archived_transactions'],
            retained_live_transactions=manifest['retained_live_transactions'], file_count=manifest['file_count'],
            source_size_bytes=manifest['size_bytes'], archive_size_bytes=target.stat().st_size,
            reclaimed_bytes=manifest['size_bytes'] - target.stat().st_size,
            recovery='Restore verified exact before/after images and the bound generation authority in an owned fixture before replay; extraction into committed alone is not a recovery proof.',
            hard_delete_without_archive=False, cleanup_complete=True)
        receipt_path = root / '.engineering-bootstrap/cleanup-receipts' / ('committed-wal-' + decision['manifest_sha256'] + '.json')
        _publish(receipt_path, receipt)
        _publish(intent_path, {**intent, 'state': 'complete'})
        return {**decision, 'apply': True, 'changed': True, 'archive': target.as_posix(),
                'archive_sha256': intent['archive_sha256'], 'archive_size_bytes': target.stat().st_size,
                'reclaimed_bytes': receipt['reclaimed_bytes'], 'receipt': receipt_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--wal-root", type=Path, default=Path(".engineering-bootstrap/operation-bus/wal")
    )
    parser.add_argument("--keep-latest", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        apply(args.root, wal_root=args.wal_root, keep_latest=args.keep_latest)
        if args.apply
        else plan(args.root, wal_root=args.wal_root, keep_latest=args.keep_latest)
    )
    print(json.dumps({key: value for key, value in result.items() if key != "manifest"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
