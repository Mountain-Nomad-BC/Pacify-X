"""Explicit current-state activation of quiescent legacy WAL owners.

The caller must establish compatible writers and admit this operation. Locks
exclude cooperating writers; supplied catalog metadata is not that admission.
Historical payloads remain unverified until a recovery/archive owner uses them.
No historical file is modified or assigned an inferred sequence.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import time
import uuid

from .file_lock import FileLock
from .json_io import decode_json_object
from .wal_generation import SCHEMA as GENERATION_SCHEMA, WalGeneration, seal
from .wal_ownership import ACTIVATION, RELATIVE, SCHEMA as OWNERSHIP_SCHEMA, WalOwnership
from .wal_transaction import (
    JsonWal, WalIntegrityError, _bounded_image, _canonical, _fsync_directory,
    _is_symlink_or_reparse, _reject_nominal_link_chain, _validate_manifest,
    _wal_lock, _write_new,
)

SCHEMA = 'px.wal-migration/1.0'
INTENT = Path('.engineering-bootstrap/wal-migration-intent.json')
LIMIT = 64 * 1024 * 1024


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _seal(value):
    body = {key: item for key, item in value.items() if key != 'sha256'}
    return {**body, 'sha256': _digest(_canonical(body, max_bytes=LIMIT))}


def _validate_intent(intent, catalog, journals):
    fields = {'schema_version', 'catalog_sha256', 'catalog', 'journals', 'scope', 'sha256'}
    if (type(intent) is not dict or set(intent) != fields or _seal(intent) != intent
            or intent['schema_version'] != SCHEMA or intent['catalog_sha256'] != catalog.sha256
            or intent['catalog'] != decode_json_object(catalog._raw, max_bytes=1024 * 1024)
            or intent['scope'] != 'current-state activation; historical payload contents unverified'
            or type(intent['journals']) is not dict
            or set(intent['journals']) != {p.relative_to(catalog.root).as_posix() for p in journals}):
        raise WalIntegrityError('migration intent does not bind this declaration')
    for item in intent['journals'].values():
        if (type(item) is not dict or set(item) != {'epoch', 'inventory'}
                or type(item['epoch']) is not str or re.fullmatch(r'[0-9a-f]{32}', item['epoch']) is None
                or type(item['inventory']) is not dict
                or set(item['inventory']) != {'journal_identity', 'history', 'targets'}):
            raise WalIntegrityError('migration journal intent is malformed')


class _Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 60
        self.entries = 0
        self.bytes = 0

    def check(self):
        self.entries += 1
        if self.entries > 32768 or time.monotonic() >= self.deadline:
            raise WalIntegrityError('migration inventory work budget exceeded')

    def image(self, path, *, limit=8 * 1024 * 1024):
        self.check()
        if self.bytes >= LIMIT:
            raise WalIntegrityError('migration acquired-image budget exceeded')
        raw = _bounded_image(path, limit=min(limit, LIMIT - self.bytes))
        self.bytes += len(raw)
        return raw


def _inventory(path, budget, *, target=False, manifest_phases=None):
    """Exact bounded membership; only targets and manifests acquire bodies."""
    _reject_nominal_link_chain(path, Path(path.anchor), label='migration input')
    if not path.exists():
        return None
    rows = []
    pending = [(path, '')]
    while pending:
        current, name = pending.pop()
        budget.check()
        if _is_symlink_or_reparse(current):
            raise WalIntegrityError('linked migration input')
        info = current.stat()
        row = dict(path=name, device=info.st_dev, inode=info.st_ino)
        if current.is_dir():
            row['kind'] = 'directory'
            if len(Path(name).parts) > 64:
                raise WalIntegrityError('migration inventory depth exceeded')
            with os.scandir(current) as entries:
                for entry in entries:
                    budget.check()
                    pending.append((Path(entry.path), name + '/' + entry.name if name else entry.name))
        elif current.is_file() and info.st_nlink == 1:
            row.update(kind='file', size=info.st_size)
            if target or current.name == 'manifest.json':
                raw = budget.image(current, limit=LIMIT if target else 8 * 1024 * 1024)
                row['sha256'] = _digest(raw)
                if not target and current.name == 'manifest.json':
                    manifest = _validate_manifest(decode_json_object(raw, max_bytes=8 * 1024 * 1024), current.parent.name)
                    if manifest['schema_version'] != '1.0':
                        raise WalIntegrityError('legacy migration cannot adopt generation manifests')
                    if manifest_phases is not None:
                        manifest_phases[name] = manifest['phase']
        else:
            raise WalIntegrityError('migration input is not an exclusively owned regular file')
        rows.append(row)
    return sorted(rows, key=lambda row: row['path'])


def _capture(catalog, journal, budget):
    wal = JsonWal(journal, catalog.root)
    if wal._pending_transactions():
        raise WalIntegrityError('legacy migration requires explicit pending WAL recovery')
    history = {}
    committed_phases = {}
    for name in ('committed', 'rolled-back', 'archives'):
        history[name] = _inventory(
            journal / name, budget,
            manifest_phases=committed_phases if name == 'committed' else None,
        )
    committed = history['committed'] or []
    for row in committed:
        if row['kind'] == 'directory' and row['path'] and '/' not in row['path']:
            # Validate the same charged image used by the inventory digest.
            if committed_phases.get(row['path'] + '/manifest.json') != 'committed':
                raise WalIntegrityError('legacy committed transaction lacks a settled manifest')
    targets = {}
    for path, kind, _owner in catalog._owners[journal]:
        if kind == 'exact' and path.exists() and not path.is_file():
            raise WalIntegrityError('exact migration target is not a file')
        targets[path.relative_to(catalog.root).as_posix()] = _inventory(path, budget, target=True)
    info = journal.stat()
    return dict(journal_identity={'device': info.st_dev, 'inode': info.st_ino},
                history=history, targets=targets)


def _retain(path, raw):
    if path.exists() or path.is_symlink():
        if _bounded_image(path, limit=max(len(raw), 1)) != raw:
            raise WalIntegrityError('conflicting retained migration file: ' + path.name)
    else:
        _write_new(path, raw)


def migrate_legacy_wals(root, owners, *, fault_injector=None):
    """Activate all declared journals, or resume the exact retained transition.

    This is an explicit effectful owner, never automatic startup recovery.
    Retrying after subsequent generation writes preserves the current header.
    """
    root = Path(os.path.abspath(root))
    _reject_nominal_link_chain(root, Path(root.anchor), label='migration root')
    root = root.resolve(strict=True)
    info = root.stat()
    catalog = WalOwnership(root, dict(schema_version=OWNERSHIP_SCHEMA,
        root_identity={'device': info.st_dev, 'inode': info.st_ino}, owners=owners))
    control = root / '.engineering-bootstrap'
    _reject_nominal_link_chain(control, root, label='migration control')
    control.mkdir(exist_ok=True)

    def fault(label):
        if fault_injector:
            fault_injector('migration:' + label)

    with FileLock(control / '.wal-ownership-admission.lock', timeout_seconds=10), ExitStack() as stack:
        budget = _Budget()
        catalog._reject_ancestor_catalog()
        journals = sorted(catalog._owners, key=lambda p: str(p).casefold())
        for journal in journals:
            budget.check()
            journal.mkdir(parents=True, exist_ok=True)
            stack.enter_context(_wal_lock(journal / '.wal.lock', 10))
        intent_path = root / INTENT
        if intent_path.exists() or intent_path.is_symlink():
            raw = _bounded_image(intent_path, limit=LIMIT)
            intent = decode_json_object(raw, max_bytes=LIMIT)
            _validate_intent(intent, catalog, journals)
        else:
            if (root / RELATIVE).exists() or (root / ACTIVATION).exists():
                raise WalIntegrityError('existing catalog requires its original migration intent')
            catalog._reject_descendant_catalog()
            inventories = {}
            for journal in journals:
                if (journal / 'generation').exists():
                    raise WalIntegrityError('existing generation cannot be adopted by migration')
                inventories[journal.relative_to(root).as_posix()] = dict(epoch=uuid.uuid4().hex, inventory=_capture(catalog, journal, budget))
            intent = _seal(dict(schema_version=SCHEMA, catalog_sha256=catalog.sha256,
                catalog=decode_json_object(catalog._raw, max_bytes=1024 * 1024), journals=inventories,
                scope='current-state activation; historical payload contents unverified'))
            _write_new(intent_path, _canonical(intent, max_bytes=LIMIT))
            fault('intent:published')

        # Every not-yet-activated journal must still match before catalog effects.
        for journal in journals:
            budget.check()
            item = intent['journals'][journal.relative_to(root).as_posix()]
            publication = journal / ('.generation-' + item['epoch'] + '.publication.json')
            staging = journal / ('.generation-' + item['epoch'] + '.prepared')
            if publication.exists() and not (journal / 'generation').exists() and not staging.exists():
                raise WalIntegrityError('published generation authority is missing')
            if not (journal / 'generation').exists() and _capture(catalog, journal, budget) != item['inventory']:
                raise WalIntegrityError('legacy inputs changed since migration intent')
        _retain(root / RELATIVE, catalog._raw)
        fault('catalog:published')
        catalog._reject_descendant_catalog()
        _retain(root / ACTIVATION, _canonical(dict(schema_version=OWNERSHIP_SCHEMA, catalog_sha256=catalog.sha256)))
        fault('catalog:acknowledged')
        heads = {}
        for journal in journals:
            budget.check()
            name = journal.relative_to(root).as_posix()
            item = intent['journals'][name]
            epoch = item['epoch']
            binding = seal(dict(schema_version=SCHEMA, intent_sha256=intent['sha256'],
                inventory_sha256=_digest(_canonical(item['inventory'], max_bytes=LIMIT)),
                epoch=epoch, ownership_sha256=catalog.sha256,
                scope='current-state activation; historical payload contents unverified'))
            generation = WalGeneration(journal)
            publication = journal / ('.generation-' + epoch + '.publication.json')
            def publication_record(directory):
                info = directory.stat()
                return seal(dict(schema_version=SCHEMA, intent_sha256=intent['sha256'],
                    epoch=epoch, generation_identity={'device': info.st_dev, 'inode': info.st_ino}))
            if generation.root.exists():
                head = generation.read()
                if generation._read('migration.json') != binding or head['epoch'] != epoch:
                    raise WalIntegrityError('existing generation is not this migration')
                if _bounded_image(publication, limit=16384) != _canonical(publication_record(generation.root)):
                    raise WalIntegrityError('generation publication authority differs')
                heads[name] = head
                continue
            if _capture(catalog, journal, budget) != item['inventory']:
                raise WalIntegrityError('legacy inputs changed before activation')
            marker = seal(dict(schema_version='px.wal-generation/2.0', epoch=epoch,
                ownership_sha256=catalog.sha256, journal_path=os.path.normcase(str(journal)),
                journal_identity=item['inventory']['journal_identity'], migration_sha256=binding['sha256']))
            head = seal(dict(schema_version=GENERATION_SCHEMA, epoch=epoch, ownership_sha256=catalog.sha256,
                sequence=0, phase='settled_initial', transaction_id=None, intent_sha256=None,
                manifest_binding=None, previous_token=None))
            staging = journal / ('.generation-' + epoch + '.prepared')
            _reject_nominal_link_chain(staging, root, label='migration staging')
            staging.mkdir(exist_ok=True)
            with os.scandir(staging) as entries:
                for entry in entries:
                    if entry.name not in {'marker.json', 'head.json', 'migration.json'}:
                        raise WalIntegrityError('unclassified migration staging member')
            for filename, value in [('marker.json', marker), ('head.json', head), ('migration.json', binding)]:
                _retain(staging / filename, _canonical(value))
                fault(name + ':' + filename + ':staged')
            _retain(publication, _canonical(publication_record(staging)))
            fault(name + ':publication:prepared')
            os.rename(staging, generation.root)
            _fsync_directory(journal)
            fault(name + ':generation:published')
            heads[name] = generation.read()
        fault('acknowledged')
        return dict(schema_version=SCHEMA, valid=True, intent_sha256=intent['sha256'],
                    generations=heads, historical_payloads_verified=False)
