"""Bounded generation authority for an explicitly activated JSON WAL.

The caller holds the existing journal lock for every mutation. Reading creates
no paths. This module supplies chronology within one declared writer domain;
activation and target ownership are separate, mandatory caller obligations.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import uuid

from .json_io import decode_json_object
from .wal_transaction import (
    WalConflictError, WalIntegrityError, _atomic_replace, _bounded_image,
    _canonical, _fsync_directory, _is_symlink_or_reparse, _write_new,
    _reject_nominal_link_chain,
)

SCHEMA = "px.wal-generation/1.0"
LIMIT = 16 * 1024
MAX_SEQUENCE = (1 << 63) - 1
SETTLED = frozenset({"settled_committed", "settled_aborted", "settled_initial"})
PHASES = SETTLED | {"allocated", "prepared_effects_possible"}
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


def seal(value):
    value = {key: item for key, item in value.items() if key != "sha256"}
    return {**value, "sha256": hashlib.sha256(_canonical(value, max_bytes=LIMIT)).hexdigest()}


def immutable_manifest_digest(manifest):
    """Bind all prepared images and generation fields, independent of phase."""
    return hashlib.sha256(_canonical({key: value for key, value in manifest.items()
                                     if key not in {"phase", "manifest_sha256"}})).hexdigest()


def _digest(value):
    return type(value) is str and HEX.fullmatch(value) is not None


class WalGeneration:
    def __init__(self, journal: Path):
        self.root = journal / "generation"

    def _read(self, name):
        _reject_nominal_link_chain(self.root, Path(self.root.anchor), label='generation authority')
        if _is_symlink_or_reparse(self.root):
            raise WalIntegrityError("generation authority is a linked path")
        try:
            value = decode_json_object(_bounded_image(self.root / name, limit=LIMIT), max_bytes=LIMIT)
        except (OSError, ValueError) as error:
            raise WalIntegrityError("generation authority is missing or invalid: " + name) from error
        if seal(value) != value:
            raise WalIntegrityError("generation authority digest mismatch")
        return value

    def read(self):
        marker = self._read("marker.json")
        journal = self.root.parent
        info = journal.stat()
        migrated = marker.get('schema_version') == 'px.wal-generation/2.0'
        marker_fields = {"schema_version", "epoch", "ownership_sha256", "journal_path", "journal_identity", "sha256"}
        if migrated:
            marker_fields.add('migration_sha256')
        if (set(marker) != marker_fields
                or marker["schema_version"] not in {SCHEMA, 'px.wal-generation/2.0'}
                or type(marker["epoch"]) is not str
                or re.fullmatch(r"[0-9a-f]{32}", marker["epoch"]) is None
                or not _digest(marker["ownership_sha256"])
                or marker['journal_path'] != os.path.normcase(str(journal.resolve()))
                or marker['journal_identity'] != {'device': info.st_dev, 'inode': info.st_ino}):
            raise WalIntegrityError("invalid generation marker")
        if migrated:
            binding = self._read('migration.json')
            if (set(binding) != {'schema_version', 'intent_sha256', 'inventory_sha256',
                                'epoch', 'ownership_sha256', 'scope', 'sha256'}
                    or binding['schema_version'] != 'px.wal-migration/1.0'
                    or binding['sha256'] != marker['migration_sha256']
                    or binding['epoch'] != marker['epoch']
                    or binding['ownership_sha256'] != marker['ownership_sha256']
                    or not _digest(binding['intent_sha256'])
                    or not _digest(binding['inventory_sha256'])
                    or binding['scope'] != 'current-state activation; historical payload contents unverified'):
                raise WalIntegrityError('generation migration binding is missing or invalid')
        header = self._read("head.json")
        fields = {"schema_version", "epoch", "ownership_sha256", "sequence", "phase",
                  "transaction_id", "intent_sha256", "manifest_binding", "previous_token", "sha256"}
        if (set(header) != fields or header["schema_version"] != SCHEMA
                or header["epoch"] != marker["epoch"]
                or header["ownership_sha256"] != marker["ownership_sha256"]
                or type(header["sequence"]) is not int
                or not 0 <= header["sequence"] <= MAX_SEQUENCE
                or type(header["phase"]) is not str or header["phase"] not in PHASES):
            raise WalIntegrityError("invalid generation header")
        if header["sequence"] == 0:
            if header["phase"] != "settled_initial" or any(header[k] is not None for k in
                    ("transaction_id", "intent_sha256", "manifest_binding", "previous_token")):
                raise WalIntegrityError("invalid initial generation")
        elif (header["phase"] == "settled_initial" or type(header["transaction_id"]) is not str
              or IDENTIFIER.fullmatch(header["transaction_id"]) is None
              or not all(_digest(header[k]) for k in ("intent_sha256", "manifest_binding", "previous_token"))):
            raise WalIntegrityError("invalid transaction generation")
        return header

    def initialize(self, ownership_sha256, *, fault_injector=None):
        """Explicit fresh-journal activation; never repair missing live authority."""
        if not _digest(ownership_sha256):
            raise ValueError("ownership identity must be an exact digest")
        if self.root.exists() or self.root.is_symlink():
            raise WalIntegrityError("generation authority already exists; activation is not recovery")
        journal = self.root.parent
        for name in ("transactions", "committed", "rolled-back", "archives"):
            directory = journal / name
            if directory.exists() and (not directory.is_dir() or _is_symlink_or_reparse(directory)
                                       or next(directory.iterdir(), None) is not None):
                raise WalIntegrityError("legacy journal requires explicit migration, not fresh activation")
        epoch = uuid.uuid4().hex
        info = journal.stat()
        marker = seal(dict(schema_version=SCHEMA, epoch=epoch, ownership_sha256=ownership_sha256,
                           journal_path=os.path.normcase(str(journal.resolve())),
                           journal_identity={'device': info.st_dev, 'inode': info.st_ino}))
        header = seal(dict(schema_version=SCHEMA, epoch=epoch, ownership_sha256=ownership_sha256,
                           sequence=0, phase="settled_initial", transaction_id=None,
                           intent_sha256=None, manifest_binding=None, previous_token=None))
        staging = journal / (".generation-" + epoch + ".prepared")
        staging.mkdir(parents=False)
        _write_new(staging / "marker.json", _canonical(marker))
        _write_new(staging / "head.json", _canonical(header))
        if fault_injector:
            fault_injector("generation:activation:staged")
        os.rename(staging, self.root)
        _fsync_directory(journal)
        if fault_injector:
            fault_injector("generation:activation:published")
        return header

    def _publish(self, header, phase, fault_injector=None):
        value = seal({**header, "phase": phase})
        _atomic_replace(self.root / "head.json", _canonical(value), label="generation:" + phase,
                        fault_injector=fault_injector)
        return value

    def check_expected(self, expected):
        if not _digest(expected):
            raise ValueError("expected generation must be an exact settled token")
        header = self.read()
        if header["phase"] not in SETTLED or header["sha256"] != expected:
            raise WalConflictError("validated WAL generation changed")
        return header

    def allocate(self, manifest, *, expected_token=None, fault_injector=None):
        header = self.read()
        if header["phase"] not in SETTLED:
            raise WalIntegrityError("generation requires recovery before allocation")
        if expected_token is not None:
            self.check_expected(expected_token)
        if header["sequence"] == MAX_SEQUENCE:
            raise WalIntegrityError("generation sequence exhausted")
        generation = dict(epoch=header["epoch"], sequence=header["sequence"] + 1,
                          previous_token=header["sha256"])
        if manifest.get("generation") != generation:
            raise WalIntegrityError("prepared manifest does not bind the next generation")
        if (type(manifest.get("transaction_id")) is not str
                or IDENTIFIER.fullmatch(manifest["transaction_id"]) is None
                or not _digest(manifest.get("intent_sha256"))):
            raise WalIntegrityError("invalid generation allocation identity")
        allocated = {**header, **generation, "transaction_id": manifest["transaction_id"],
                     "intent_sha256": manifest["intent_sha256"],
                     "manifest_binding": immutable_manifest_digest(manifest)}
        return self._publish(allocated, "allocated", fault_injector)

    def bind(self, manifest):
        header = self.read()
        expected = dict(epoch=header["epoch"], sequence=header["sequence"], previous_token=header["previous_token"])
        if (manifest.get("generation") != expected
                or manifest.get("transaction_id") != header["transaction_id"]
                or manifest.get("intent_sha256") != header["intent_sha256"]
                or immutable_manifest_digest(manifest) != header["manifest_binding"]):
            raise WalIntegrityError("manifest differs from allocated generation authority")
        return header

    def prepare_effects(self, manifest, *, fault_injector=None):
        header = self.bind(manifest)
        if header["phase"] not in {"allocated", "prepared_effects_possible"}:
            raise WalIntegrityError("generation cannot authorize target effects")
        return self._publish(header, "prepared_effects_possible", fault_injector)

    def settle_committed(self, manifest, *, fault_injector=None):
        header = self.bind(manifest)
        if header["phase"] not in {"prepared_effects_possible", "settled_committed"} or manifest.get("phase") != "committed":
            raise WalIntegrityError("unprepared generation cannot settle committed")
        return self._publish(header, "settled_committed", fault_injector)

    def settle_aborted(self, *, fault_injector=None):
        """Caller must prove no prepared manifest exists before using this path."""
        header = self.read()
        if header["phase"] != "allocated":
            raise WalIntegrityError("effects-possible generation cannot be aborted")
        disposition = seal({**header, "phase": "settled_aborted"})
        path = self.root / "aborted" / f"{header['sequence']:020d}.json"
        if path.exists():
            if self._read(path.relative_to(self.root).as_posix()) != disposition:
                raise WalIntegrityError("conflicting retained abort disposition")
        else:
            _write_new(path, _canonical(disposition))
        if fault_injector:
            fault_injector("generation:abort-disposition:published")
        return self._publish(header, "settled_aborted", fault_injector)
