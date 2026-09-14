"""Explicit, retained-before-image resource storage migration.

Activation is the last atomic publication. Interrupted pre-activation attempts
leave legacy authority intact and are retained; a retry builds a fresh generation.
An already activated ledger is never rolled back over subsequent indexed writes.
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
from runtime.file_lock import FileLock, _process_exists, _process_start_fingerprint  # noqa: E402
from runtime.json_io import bounded_canonical_json_bytes, decode_json_object  # noqa: E402
from runtime.resource_lifecycle import ResourceLedger, ResourceRecord, _resource_records_from_image  # noqa: E402
from runtime.resource_storage import IndexedResourceStorage, SELECTOR_SCHEMA, selected_storage  # noqa: E402
from runtime.wal_transaction import _atomic_replace, _bounded_image, _write_new  # noqa: E402


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _same_records(left, right):
    # Legacy JSON converts tuple metadata to lists; compare the wire semantics.
    return json.loads(json.dumps([asdict(row) for row in left])) == json.loads(json.dumps([asdict(row) for row in right]))


def _require_quiescent(records):
    # Historical active flags remain historical obligations. Migration does not
    # clear them or infer descendant closure from a dead recorded parent PID.
    for row in records:
        if row.resource_type == 'process' and row.active:
            if type(row.pid) is int and row.pid > 0:
                if not _process_exists(row.pid):
                    continue
                current = _process_start_fingerprint(row.pid)
                identity = row.process_identity
                if (current is not None and type(identity) is str
                        and identity.startswith('process-start:') and len(identity) == 78
                        and all(c in '0123456789abcdef' for c in identity[14:])
                        and identity != 'process-start:' + current):
                    continue  # A reused PID is not the recorded writer.
            raise ValueError('migration requires quiescent recorded process ownership')


def migrate(ledger_path, *, expected_legacy_sha256, fault_injector=None):
    if (type(expected_legacy_sha256) is not str or len(expected_legacy_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_legacy_sha256)):
        raise ValueError('migration requires an exact legacy SHA-256')
    ledger_path = Path(ledger_path)
    reject_path_links(ledger_path)
    owner = ResourceLedger(ledger_path)

    def boundary(label):
        if fault_injector is not None:
            fault_injector(label)

    with owner._lock, FileLock(owner.lock_path, timeout_seconds=30):
        raw = _bounded_image(owner.path, limit=64 * 1024**2)
        payload = decode_json_object(raw, max_bytes=64 * 1024**2)
        selected = selected_storage(owner.path, payload, ResourceRecord)
        if selected is not None:
            if payload['legacy_sha256'] != expected_legacy_sha256:
                raise ValueError('activated ledger belongs to a different migration')
            retained = _bounded_image(selected.path.parent / 'legacy.json', limit=64 * 1024**2)
            if _digest(retained) != expected_legacy_sha256:
                raise ValueError('migration legacy custody is unavailable')
            records, token = selected.snapshot()
            return dict(valid=True, state='already_active', record_count=len(records),
                        current_generation=token, legacy_sha256=expected_legacy_sha256)
        if _digest(raw) != expected_legacy_sha256:
            raise ValueError('legacy ledger changed before migration')
        records = _resource_records_from_image(raw)
        _require_quiescent(records)
        storage_root = owner.path.parent / 'ledger-storage'
        reject_path_links(storage_root)
        if storage_root.exists():
            # Never adopt or delete older/unclassified attempt contents.
            with os.scandir(storage_root) as entries:
                for index, _ in enumerate(entries):
                    if index >= 64:
                        raise ValueError('retained migration attempt limit reached')
        epoch = uuid4().hex
        generation = storage_root / epoch
        storage = IndexedResourceStorage(generation / 'resources.sqlite', ResourceRecord, expected_epoch=epoch)
        storage._encode_records(records)  # All representation checks precede effects.
        storage_root.mkdir(exist_ok=True)
        generation.mkdir(exist_ok=False)
        intent = dict(schema_version='px.resource-ledger-migration/1.0', epoch=epoch,
                      ledger_name=owner.path.name, legacy_sha256=expected_legacy_sha256,
                      record_count=len(records), state='staging')
        _write_new(generation / 'intent.json', bounded_canonical_json_bytes(intent, max_bytes=4096))
        boundary('intent_written')
        _write_new(generation / 'legacy.json', raw)
        boundary('legacy_retained')
        storage.create(records, epoch=epoch)
        boundary('database_created')
        with storage.locked_snapshot() as (copied, token):
            if not _same_records(records, copied):
                raise ValueError('indexed migration does not preserve every legacy record')
            if _bounded_image(generation / 'legacy.json', limit=len(raw)) != raw:
                raise ValueError('retained legacy image changed')
            receipt = {**intent, 'state': 'candidate_ready', 'database_generation': token}
            _write_new(generation / 'prepared-receipt.json', bounded_canonical_json_bytes(receipt, max_bytes=8192))
            boundary('receipt_written')
            selector = dict(schema_version=SELECTOR_SCHEMA, state='active', epoch=epoch,
                            database=f'ledger-storage/{epoch}/resources.sqlite',
                            legacy_sha256=expected_legacy_sha256)
            selector['selector_sha256'] = _digest(bounded_canonical_json_bytes(selector, max_bytes=4096))
            encoded = bounded_canonical_json_bytes(selector, max_bytes=4096)
            boundary('before_activation')
            _require_quiescent(records)
            if _bounded_image(owner.path, limit=len(raw)) != raw:
                raise ValueError('legacy authority changed before activation')
            _atomic_replace(owner.path, encoded, label='selector', fault_injector=fault_injector,
                            prepared_path=generation / 'selector.prepared')
            boundary('activated')
        if _bounded_image(owner.path, limit=4096) != encoded:
            raise ValueError('activated selector identity changed')
        return dict(valid=True, state='activated', record_count=len(records),
                    current_generation=token, legacy_sha256=expected_legacy_sha256,
                    retained_generation=str(generation))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--expected-legacy-sha256', required=True)
    args = parser.parse_args(argv)
    result = migrate(args.ledger, expected_legacy_sha256=args.expected_legacy_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
