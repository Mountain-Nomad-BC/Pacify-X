"""Retain and migrate one selected resource database from schema v2 to v3.

The selector is the final atomic effect. Its old bytes and database generation
remain in place, so interrupted attempts never discard authoritative history.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from runtime.archive_io import reject_path_links  # noqa: E402
from runtime.file_lock import FileLock  # noqa: E402
from runtime.json_io import bounded_canonical_json_bytes, decode_json_object  # noqa: E402
from runtime.resource_lifecycle import ResourceLedger, ResourceRecord  # noqa: E402
from runtime.resource_storage import (  # noqa: E402
    DATABASE_SCHEMA_VERSION,
    IndexedResourceStorage,
    SELECTOR_SCHEMA,
    selected_storage,
)
from runtime.wal_transaction import _atomic_replace, _bounded_image, _write_new  # noqa: E402
from scripts.migrate_resource_ledger import _require_quiescent  # noqa: E402


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _same_records(left, right):
    return json.loads(json.dumps([asdict(row) for row in left])) == json.loads(
        json.dumps([asdict(row) for row in right])
    )


def migrate(ledger_path, *, expected_selector_sha256, fault_injector=None, dry_run=False):
    if (type(expected_selector_sha256) is not str or len(expected_selector_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_selector_sha256)):
        raise ValueError('migration requires an exact selector SHA-256')
    ledger_path = Path(ledger_path)
    reject_path_links(ledger_path)
    owner = ResourceLedger(ledger_path)

    def boundary(label):
        if fault_injector is not None:
            fault_injector(label)

    with owner._lock, FileLock(owner.lock_path, timeout_seconds=30):
        raw = _bounded_image(owner.path, limit=4096)
        payload = decode_json_object(raw, max_bytes=4096)
        selected = selected_storage(owner.path, payload, ResourceRecord)
        if selected is None:
            raise ValueError('resource storage v3 migration requires an indexed selector')
        source_version = selected.database_schema_version()
        records, source_token = selected.snapshot()
        if _digest(raw) != expected_selector_sha256:
            receipt_path = selected.path.parent / 'prepared-receipt.json'
            try:
                receipt = decode_json_object(_bounded_image(receipt_path, limit=16 * 1024), max_bytes=16 * 1024)
            except (OSError, ValueError):
                receipt = {}
            if (source_version == DATABASE_SCHEMA_VERSION
                    and receipt.get('source_selector_sha256') == expected_selector_sha256
                    and receipt.get('target_epoch') == payload.get('epoch')):
                return dict(valid=True, state='already_active', record_count=len(records),
                            current_generation=source_token,
                            selector_sha256=_digest(raw), source_selector_sha256=expected_selector_sha256)
            raise ValueError('resource selector changed before migration')
        if source_version == DATABASE_SCHEMA_VERSION:
            return dict(valid=True, state='already_active', record_count=len(records),
                        current_generation=source_token, selector_sha256=expected_selector_sha256)
        if source_version != 2:
            raise ValueError('unsupported source resource database schema')
        _require_quiescent(records)
        source_database = _bounded_image(selected.path, limit=256 * 1024**2)
        source_database_sha256 = _digest(source_database)
        if dry_run:
            return dict(valid=True, state='dry_run', source_schema=source_version,
                        target_schema=DATABASE_SCHEMA_VERSION, record_count=len(records),
                        selector_sha256=expected_selector_sha256,
                        source_database_sha256=source_database_sha256)

        storage_root = owner.path.parent / 'ledger-storage'
        reject_path_links(storage_root)
        if storage_root.exists():
            with os.scandir(storage_root) as entries:
                for index, _ in enumerate(entries):
                    if index >= 64:
                        raise ValueError('retained migration attempt limit reached')
        epoch = uuid4().hex
        generation = storage_root / epoch
        target = IndexedResourceStorage(generation / 'resources.sqlite', ResourceRecord, expected_epoch=epoch)
        target._encode_records(records)
        generation.mkdir(exist_ok=False)
        intent = dict(schema_version='px.resource-storage-migration/3.0', state='staging',
                      source_epoch=payload['epoch'], target_epoch=epoch,
                      source_selector_sha256=expected_selector_sha256,
                      source_database_sha256=source_database_sha256,
                      source_schema=source_version, target_schema=DATABASE_SCHEMA_VERSION,
                      record_count=len(records))
        _write_new(generation / 'intent.json', bounded_canonical_json_bytes(intent, max_bytes=8192))
        _write_new(generation / 'selector-v2.json', raw)
        boundary('intent_retained')
        target.create(records, epoch=epoch)
        boundary('database_created')
        with target.locked_snapshot() as (copied, target_token):
            if not _same_records(records, copied):
                raise ValueError('resource storage v3 migration lost record parity')
            receipt = {**intent, 'state': 'candidate_ready', 'source_generation': source_token,
                       'target_generation': target_token}
            _write_new(generation / 'prepared-receipt.json',
                       bounded_canonical_json_bytes(receipt, max_bytes=16 * 1024))
            boundary('receipt_written')
            selector = dict(schema_version=SELECTOR_SCHEMA, state='active', epoch=epoch,
                            database=f'ledger-storage/{epoch}/resources.sqlite',
                            legacy_sha256=payload['legacy_sha256'])
            selector['selector_sha256'] = _digest(bounded_canonical_json_bytes(selector, max_bytes=4096))
            encoded = bounded_canonical_json_bytes(selector, max_bytes=4096)
            boundary('before_activation')
            _require_quiescent(records)
            if _bounded_image(owner.path, limit=4096) != raw:
                raise ValueError('resource selector changed before activation')
            if _digest(_bounded_image(selected.path, limit=256 * 1024**2)) != source_database_sha256:
                raise ValueError('source resource database changed before activation')
            _atomic_replace(owner.path, encoded, label='selector-v3', fault_injector=fault_injector,
                            prepared_path=generation / 'selector-v3.prepared')
            boundary('activated')
        if _bounded_image(owner.path, limit=4096) != encoded:
            raise ValueError('activated v3 selector identity changed')
        return dict(valid=True, state='activated', source_schema=source_version,
                    target_schema=DATABASE_SCHEMA_VERSION, record_count=len(records),
                    current_generation=target_token, source_database_sha256=source_database_sha256,
                    retained_source_generation=str(selected.path.parent),
                    activated_generation=str(generation))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--expected-selector-sha256', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    result = migrate(args.ledger, expected_selector_sha256=args.expected_selector_sha256,
                     dry_run=args.dry_run)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
