"""Versioned indexed storage behind the resource lifecycle owner.

Connections are short lived. The caller retains the existing ledger writer lock;
SQLite transactions bind each database read or mutation. Opening a reader never
initializes a database or performs rollback-journal recovery.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote
from uuid import uuid4

from .archive_io import reject_path_links
from .json_io import bounded_canonical_json_bytes, decode_json_value

MAX_RECORDS = 100_000
MAX_RECORD_BYTES = 65_536
MAX_ENCODED_BYTES = 64 * 1024**2
MAX_DATABASE_BYTES = 256 * 1024**2
SELECTOR_SCHEMA = 'px.resource-ledger-selector/2.0'
DATABASE_SCHEMA_VERSION = 3
BOOL_FIELDS = frozenset(('retention_required', 'active', 'evidence_validated', 'reclamation_approved'))
INT_FIELDS = frozenset(('files', 'directories', 'bytes', 'pid'))
JSON_FIELDS = frozenset(('promoted_outputs', 'path_identity', 'cleanup_intent'))


class ResourceStorageError(ValueError):
    """Storage is invalid, unavailable, or requires explicit writer recovery."""


def selected_storage(ledger_path, payload, record_type):
    """Resolve only an exact supported selector; legacy JSON remains separate."""
    if payload.get('schema_version') != SELECTOR_SCHEMA:
        if payload.get('schema_version') == '1.0':
            return None
        raise ResourceStorageError('unsupported resource ledger schema')
    fields = {'schema_version', 'state', 'epoch', 'database', 'legacy_sha256', 'selector_sha256'}
    if set(payload) != fields or payload['state'] != 'active':
        raise ResourceStorageError('resource migration is incomplete or selector is invalid')
    epoch = payload['epoch']
    if type(epoch) is not str or len(epoch) != 32 or any(c not in '0123456789abcdef' for c in epoch):
        raise ResourceStorageError('invalid resource selector epoch')
    for name in ('legacy_sha256', 'selector_sha256'):
        value = payload[name]
        if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ResourceStorageError('invalid resource selector digest')
    expected = f'ledger-storage/{epoch}/resources.sqlite'
    if payload['database'] != expected:
        raise ResourceStorageError('resource selector database escapes its generation')
    unsigned = {key: value for key, value in payload.items() if key != 'selector_sha256'}
    if hashlib.sha256(bounded_canonical_json_bytes(unsigned, max_bytes=4096)).hexdigest() != payload['selector_sha256']:
        raise ResourceStorageError('resource selector integrity mismatch')
    path = Path(ledger_path).parent / expected
    reject_path_links(path)
    return IndexedResourceStorage(path, record_type, expected_epoch=epoch)


class IndexedResourceStorage:
    def __init__(self, path: Path, record_type, *, expected_epoch=None):
        self.path = Path(path)
        self.record_type = record_type
        self.expected_epoch = expected_epoch
        self.fields = tuple(record_type.__dataclass_fields__)
        self.optional = frozenset(name for name, field in record_type.__dataclass_fields__.items()
                                  if field.default is None)
        self.legacy_fields = tuple(name for name in self.fields if name != 'host_boot_generation')
        self.schemas = self._schemas(self.fields, DATABASE_SCHEMA_VERSION)
        self.legacy_schemas = self._schemas(self.legacy_fields, 2)
        self.select = ','.join('"' + name + '"' for name in self.fields)

    def _schemas(self, fields, version):
        columns = ['ordinal INTEGER NOT NULL UNIQUE CHECK(ordinal >= 0)',
                   f'record_bytes INTEGER NOT NULL CHECK(record_bytes BETWEEN 1 AND {MAX_RECORD_BYTES})']
        for name in fields:
            kind = 'INTEGER' if name in BOOL_FIELDS | INT_FIELDS else 'TEXT'
            nullable = name in self.optional
            check = f'typeof("{name}") = \'{kind.lower()}\''
            if name in BOOL_FIELDS:
                check += f' AND "{name}" IN (0,1)'
            if name in JSON_FIELDS:
                check += f' AND json_valid("{name}")'
            if nullable:
                check = f'"{name}" IS NULL OR ({check})'
            suffix = ' PRIMARY KEY' if name == 'resource_id' else ''
            columns.append(f'"{name}" {kind}' + ('' if nullable else ' NOT NULL') + suffix + f' CHECK({check})')
        wire_fields = []
        for name in fields:
            expression = f'"{name}"'
            if name in BOOL_FIELDS:
                expression = f'json(CASE "{name}" WHEN 1 THEN \'true\' ELSE \'false\' END)'
            elif name in JSON_FIELDS:
                expression = f'json("{name}")'
            wire_fields.extend(("'" + name + "'", expression))
        # The size column is checked against the stored values, not trusted as
        # caller-supplied accounting. Object key order does not change byte size.
        columns.append('CHECK(record_bytes = length(CAST(json_object(' + ','.join(wire_fields) + ') AS BLOB))+1)')
        return {
            'resources': 'CREATE TABLE resources (' + ', '.join(columns) + ')',
            'metadata': f'CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL CHECK(schema_version={version}), epoch TEXT NOT NULL CHECK(length(epoch)=32), generation INTEGER NOT NULL CHECK(generation>=0), sorted_order INTEGER NOT NULL CHECK(sorted_order IN (0,1)))',
        }

    def _select_for(self, connection):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(resources)')}
        return ','.join('"' + name + '"' if name in columns else 'NULL AS "' + name + '"'
                        for name in self.fields)

    def _connect(self, *, write=False, initialize=False, epoch=None):
        reject_path_links(self.path)
        if not initialize and (not self.path.is_file() or self.path.stat().st_size > MAX_DATABASE_BYTES):
            raise ResourceStorageError('resource database is missing, oversized or not a regular file')
        mode = 'rwc' if initialize else 'rw' if write else 'ro'
        connection = None
        try:
            uri = 'file:' + quote(self.path.as_posix(), safe='/:') + '?mode=' + mode
            connection = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RECORD_BYTES * 2)
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA busy_timeout=30000')
            if write:
                connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if initialize:
                for sql in self.schemas.values():
                    connection.execute(sql)
                connection.execute('INSERT INTO metadata VALUES (1,?,?,0,0)',
                                   (DATABASE_SCHEMA_VERSION, epoch or uuid4().hex))
            else:
                expected = {**self.schemas, 'sqlite_autoindex_resources_1': None,
                            'sqlite_autoindex_resources_2': None}
                legacy_expected = {**self.legacy_schemas, 'sqlite_autoindex_resources_1': None,
                                   'sqlite_autoindex_resources_2': None}
                actual = dict(connection.execute('SELECT name,sql FROM sqlite_master'))
                database_version = DATABASE_SCHEMA_VERSION if actual == expected else 2 if actual == legacy_expected else None
                if database_version is None:
                    raise ResourceStorageError('resource database schema differs from its supported contract')
                if write and database_version != DATABASE_SCHEMA_VERSION:
                    raise ResourceStorageError('resource database requires explicit v3 migration')
                if connection.execute('PRAGMA quick_check(1)').fetchall() != [('ok',)]:
                    raise ResourceStorageError('resource database integrity check failed')
            if connection.execute('PRAGMA journal_mode').fetchone() != ('delete',):
                raise ResourceStorageError('unsupported resource database journal mode')
            metadata = connection.execute('SELECT singleton,schema_version,epoch,generation,sorted_order FROM metadata').fetchall()
            if (len(metadata) != 1 or metadata[0][:2] != (1, DATABASE_SCHEMA_VERSION if initialize else database_version)
                    or type(metadata[0][2]) is not str or len(metadata[0][2]) != 32
                    or any(c not in '0123456789abcdef' for c in metadata[0][2])
                    or type(metadata[0][3]) is not int or metadata[0][3] < 0
                    or metadata[0][4] not in (0, 1)):
                raise ResourceStorageError('invalid resource database generation')
            if self.expected_epoch is not None and metadata[0][2] != self.expected_epoch:
                raise ResourceStorageError('resource selector and database epochs differ')
            if write and metadata[0][3] >= 2**63 - 1:
                raise ResourceStorageError('resource generation is exhausted')
            count, total, largest = connection.execute('SELECT count(*),coalesce(sum(record_bytes),0),coalesce(max(record_bytes),0) FROM resources').fetchone()
            if count > MAX_RECORDS or total > MAX_ENCODED_BYTES or largest > MAX_RECORD_BYTES:
                raise ResourceStorageError('resource database acquisition budget exceeded')
            if write:
                page_size = connection.execute('PRAGMA page_size').fetchone()[0]
                connection.execute('PRAGMA max_page_count=' + str(MAX_DATABASE_BYTES // page_size))
            return connection
        except (sqlite3.Error, OSError) as error:
            if connection is not None:
                connection.close()
            raise ResourceStorageError('resource database unavailable or recovery required: ' + str(error)) from error
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    def _encode(self, record):
        if type(record) is not self.record_type:
            raise ResourceStorageError('resource record has the wrong type')
        data = asdict(record)
        if (type(record.resource_id) is not str or not 1 <= len(record.resource_id) <= 256
                or record.resource_type not in ('path', 'process')):
            raise ResourceStorageError('invalid resource identity or type')
        encoded = bounded_canonical_json_bytes(data, max_bytes=MAX_RECORD_BYTES)
        values = []
        for name in self.fields:
            value = data[name]
            if value is None and name in self.optional:
                values.append(None)
                continue
            if name in BOOL_FIELDS:
                if type(value) is not bool:
                    raise ResourceStorageError('resource boolean field has wrong type: ' + name)
                value = int(value)
            elif name in INT_FIELDS:
                if type(value) is not int or not 0 <= value <= 2**63 - 1:
                    raise ResourceStorageError('resource integer field is invalid: ' + name)
            elif name in JSON_FIELDS:
                expected = (dict,) if name == 'cleanup_intent' else (tuple, list)
                if type(value) not in expected:
                    raise ResourceStorageError('resource structured field has wrong type: ' + name)
                value = json.dumps(value, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            elif type(value) is not str:
                raise ResourceStorageError('resource text field has wrong type: ' + name)
            values.append(value)
        return len(encoded), tuple(values)

    def _decode(self, values):
        data = dict(zip(self.fields, values, strict=True))
        for name in BOOL_FIELDS:
            if type(data[name]) is not int or data[name] not in (0, 1):
                raise ResourceStorageError('invalid stored resource boolean')
            data[name] = bool(data[name])
        for name in JSON_FIELDS:
            if data[name] is not None:
                data[name] = decode_json_value(data[name].encode('utf-8'), max_bytes=MAX_RECORD_BYTES)
        record = self.record_type(**data)
        if (type(record.resource_id) is not str or not 1 <= len(record.resource_id) <= 256
                or record.resource_type not in ('path', 'process')):
            raise ResourceStorageError('invalid stored resource identity')
        return record

    def _rows(self, connection):
        sorted_order = connection.execute('SELECT sorted_order FROM metadata').fetchone()[0]
        order = 'resource_id' if sorted_order else 'ordinal'
        return tuple(self._decode(row) for row in connection.execute(
            'SELECT ' + self._select_for(connection) + ' FROM resources ORDER BY ' + order + ' LIMIT ?', (MAX_RECORDS + 1,)))

    def load(self):
        connection = self._connect()
        try:
            return self._rows(connection)
        finally:
            connection.close()

    def database_schema_version(self):
        """Return the exact validated backend schema without changing it."""
        connection = self._connect()
        try:
            return connection.execute('SELECT schema_version FROM metadata WHERE singleton=1').fetchone()[0]
        finally:
            connection.close()

    def get(self, resource_id):
        self._identity(resource_id)
        connection = self._connect()
        try:
            row = connection.execute('SELECT ' + self._select_for(connection) + ' FROM resources WHERE resource_id=?', (resource_id,)).fetchone()
            if row is None:
                raise KeyError(resource_id)
            return self._decode(row)
        finally:
            connection.close()

    def _put(self, connection, record):
        size, values = self._encode(record)
        old = connection.execute('SELECT ordinal,record_bytes FROM resources WHERE resource_id=?', (record.resource_id,)).fetchone()
        count, total, largest = connection.execute('SELECT count(*),coalesce(sum(record_bytes),0),coalesce(max(ordinal),-1) FROM resources').fetchone()
        if count + int(old is None) > MAX_RECORDS or total - (old[1] if old else 0) + size > MAX_ENCODED_BYTES:
            raise ResourceStorageError('resource mutation exceeds aggregate budget')
        if old is None:
            connection.execute('INSERT INTO resources VALUES (' + ','.join('?' for _ in range(len(values) + 2)) + ')',
                               (largest + 1, size, *values))
        else:
            assignments = ','.join('"' + name + '"=?' for name in self.fields)
            connection.execute('UPDATE resources SET record_bytes=?,' + assignments + ' WHERE resource_id=?',
                               (size, *values, record.resource_id))

    def upsert(self, record):
        connection = self._connect(write=True)
        try:
            self._put(connection, record)
            connection.execute('UPDATE metadata SET generation=generation+1,sorted_order=1')
            connection.execute('COMMIT')
        finally:
            connection.close()

    def update(self, resource_id, **changes):
        self._identity(resource_id)
        if len(changes) > len(self.fields) or set(changes) - set(self.fields):
            raise ResourceStorageError('unsupported resource update fields')
        connection = self._connect(write=True)
        try:
            row = connection.execute('SELECT ' + self._select_for(connection) + ' FROM resources WHERE resource_id=?', (resource_id,)).fetchone()
            if row is None:
                raise KeyError(resource_id)
            record = replace(self._decode(row), **changes)
            if record.resource_id != resource_id:
                raise ResourceStorageError('resource updates cannot rekey an identity')
            self._put(connection, record)
            connection.execute('UPDATE metadata SET generation=generation+1,sorted_order=1')
            connection.execute('COMMIT')
            return record
        finally:
            connection.close()

    def _encode_records(self, records):
        if type(records) not in (list, tuple) or len(records) > MAX_RECORDS:
            raise ResourceStorageError('resource replacement requires a bounded list or tuple')
        encoded, identities, total = [], set(), 0
        for record in records:
            row = self._encode(record)
            if record.resource_id in identities:
                raise ResourceStorageError('duplicate resource identity')
            identities.add(record.resource_id)
            total += row[0]
            if total > MAX_ENCODED_BYTES:
                raise ResourceStorageError('resource replacement exceeds byte budget')
            encoded.append(row)
        return encoded

    def _replace_rows(self, connection, encoded):
        connection.execute('DELETE FROM resources')
        for ordinal, (size, values) in enumerate(encoded):
            connection.execute('INSERT INTO resources VALUES (' + ','.join('?' for _ in range(len(values) + 2)) + ')',
                               (ordinal, size, *values))
        connection.execute('UPDATE metadata SET generation=generation+1,sorted_order=0')

    def write(self, records):
        encoded = self._encode_records(records)
        connection = self._connect(write=True)
        try:
            self._replace_rows(connection, encoded)
            connection.execute('COMMIT')
        finally:
            connection.close()

    @staticmethod
    def _identity(resource_id):
        if type(resource_id) is not str or not 1 <= len(resource_id) <= 256:
            raise ResourceStorageError('resource identity must be bounded text')

    @contextmanager
    def locked_snapshot(self):
        """Keep one SQLite read generation held through a caller's validation."""
        connection = self._connect()
        try:
            records = self._rows(connection)
            epoch, generation = connection.execute('SELECT epoch,generation FROM metadata').fetchone()
            size = connection.execute('PRAGMA page_count').fetchone()[0] * connection.execute('PRAGMA page_size').fetchone()[0]
            if size > MAX_DATABASE_BYTES:
                raise ResourceStorageError('resource snapshot exceeds byte budget')
            # Serialize the held database view, not a second pathname read that
            # could describe a different file generation.
            image = connection.serialize()
            if len(image) > MAX_DATABASE_BYTES:
                raise ResourceStorageError('resource snapshot exceeds byte budget')
            yield records, {'epoch': epoch, 'generation': generation, 'sha256': hashlib.sha256(image).hexdigest()}
        finally:
            connection.close()

    def snapshot(self):
        with self.locked_snapshot() as snapshot:
            return snapshot

    def create(self, records, *, epoch=None):
        """Initialize only a new caller-owned generation; never replace a database."""
        encoded = self._encode_records(records)
        if epoch is not None and (type(epoch) is not str or len(epoch) != 32
                                  or any(c not in '0123456789abcdef' for c in epoch)):
            raise ResourceStorageError('invalid resource creation epoch')
        reject_path_links(self.path)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        connection = self._connect(write=True, initialize=True, epoch=epoch)
        try:
            self._replace_rows(connection, encoded)
            connection.execute('COMMIT')
        finally:
            connection.close()
