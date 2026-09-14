"""Immutable target-domain declarations shared by cooperating WAL owners.

Catalog activation is explicit and separate from ordinary transactions. The
catalog root is authority, while each JsonWal allowed_root is containment only.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

from .file_lock import FileLock
from .json_io import decode_json_object
from .wal_transaction import (
    WalIntegrityError, _bounded_image, _canonical, _fsync_directory,
    _is_symlink_or_reparse, _reject_nominal_link_chain, _write_new,
)

SCHEMA = "px.wal-ownership/1.0"
RELATIVE = Path(".engineering-bootstrap/wal-ownership.json")
ACTIVATION = Path(".engineering-bootstrap/wal-ownership-activation.json")
LIMIT = 1024 * 1024
MAX_OWNERS = 128
MAX_DOMAINS = 1024
MAX_ACTIVATION_DIRECTORIES = 30000


def _inside(path, root):
    return path == root or root in path.parents


def _canonical_path(root, value):
    if (type(value) is not str or not value or len(value.encode('utf-8')) > 4096
            or Path(value).is_absolute() or '..' in Path(value).parts
            or Path(value).as_posix() != value or value == '.'):
        raise WalIntegrityError("ownership paths must be canonical relative paths")
    nominal = root / value
    _reject_nominal_link_chain(nominal, root, label='ownership domain')
    result = nominal.resolve(strict=False)
    if not _inside(result, root) or result == root:
        raise WalIntegrityError("ownership path escapes authority root")
    return result


def _root(root):
    nominal = Path(os.path.abspath(root))
    _reject_nominal_link_chain(nominal, Path(nominal.anchor), label='ownership root')
    resolved = nominal.resolve(strict=True)
    if not resolved.is_dir():
        raise WalIntegrityError('ownership root must be a directory')
    return resolved


class WalOwnership:
    def __init__(self, root: Path, value):
        self.root = _root(root)
        info = self.root.stat()
        if (type(value) is not dict or set(value) != {'schema_version', 'root_identity', 'owners'}
                or value['schema_version'] != SCHEMA
                or value['root_identity'] != {'device': info.st_dev, 'inode': info.st_ino}
                or type(value['owners']) is not list or not 1 <= len(value['owners']) <= MAX_OWNERS):
            raise WalIntegrityError('invalid ownership catalog or physical root identity')
        owners = {}
        domains = []
        for owner in value['owners']:
            if (type(owner) is not dict or set(owner) != {'journal', 'domains'}
                    or type(owner['domains']) is not list or not owner['domains']):
                raise WalIntegrityError('invalid ownership declaration')
            journal = _canonical_path(self.root, owner['journal'])
            if journal in owners:
                raise WalIntegrityError('duplicate or aliased journal owner')
            declared = []
            for domain in owner['domains']:
                if (type(domain) is not dict or set(domain) != {'path', 'kind'}
                        or domain['kind'] not in ('exact', 'subtree')):
                    raise WalIntegrityError('invalid target domain')
                path = _canonical_path(self.root, domain['path'])
                if len(domains) >= MAX_DOMAINS:
                    raise WalIntegrityError('ownership domain budget exceeded')
                row = (path, domain['kind'], journal)
                # Redundant same-owner domains are rejected too: each target has
                # one unambiguous declaration, not an ordering-dependent match.
                for other, kind, _owner in domains:
                    if (path == other or (domain['kind'] == 'subtree' and _inside(other, path))
                            or (kind == 'subtree' and _inside(path, other))):
                        raise WalIntegrityError('overlapping target ownership')
                domains.append(row)
                declared.append(row)
            owners[journal] = tuple(declared)
        metadata = [self.root / RELATIVE, self.root / ACTIVATION, *owners]
        for path, kind, _owner in domains:
            for meta in metadata:
                if path == meta or _inside(path, meta) or (kind == 'subtree' and _inside(meta, path)):
                    raise WalIntegrityError('WAL authority cannot be an ordinary target domain')
        self._owners = owners
        self._domains = tuple(domains)
        self._raw = _canonical(value, max_bytes=LIMIT)
        self.sha256 = hashlib.sha256(self._raw).hexdigest()

    @classmethod
    def read(cls, root):
        root = _root(root)
        try:
            raw = _bounded_image(root / RELATIVE, limit=LIMIT)
            value = decode_json_object(raw, max_bytes=LIMIT)
        except (OSError, ValueError) as error:
            raise WalIntegrityError('ownership catalog is missing or invalid') from error
        result = cls(root, value)
        if result._raw != raw:
            raise WalIntegrityError('ownership catalog bytes are not canonical')
        try:
            receipt = decode_json_object(_bounded_image(root / ACTIVATION, limit=4096), max_bytes=4096)
        except (OSError, ValueError) as error:
            raise WalIntegrityError('ownership activation has not completed') from error
        if receipt != {'schema_version': SCHEMA, 'catalog_sha256': result.sha256}:
            raise WalIntegrityError('ownership activation receipt does not bind this catalog')
        result._reject_ancestor_catalog()
        return result

    def _reject_ancestor_catalog(self):
        for parent in self.root.parents:
            candidate = parent / RELATIVE
            if candidate.exists() or candidate.is_symlink():
                raise WalIntegrityError('nested ownership authority is not permitted')

    def _reject_descendant_catalog(self):
        pending = [self.root]
        visited = 0
        raw_entries = 0
        deadline = time.monotonic() + 60
        while pending:
            if time.monotonic() >= deadline:
                raise WalIntegrityError('ownership activation deadline exceeded')
            directory = pending.pop()
            visited += 1
            if visited > MAX_ACTIVATION_DIRECTORIES:
                raise WalIntegrityError('ownership activation directory budget exceeded')
            if directory != self.root and (directory / RELATIVE).exists():
                raise WalIntegrityError('nested ownership catalog already exists')
            with os.scandir(directory) as entries:
                for entry in entries:
                    raw_entries += 1
                    if raw_entries > 60000 or time.monotonic() >= deadline:
                        raise WalIntegrityError('ownership activation traversal budget exceeded')
                    if entry.is_dir(follow_symlinks=False):
                        child = Path(entry.path)
                        if _is_symlink_or_reparse(child):
                            raise WalIntegrityError('activation cannot survey linked directories')
                        if len(pending) + visited >= MAX_ACTIVATION_DIRECTORIES:
                            raise WalIntegrityError('ownership activation directory budget exceeded')
                        pending.append(child)

    @classmethod
    def activate(cls, root, owners):
        """Explicit quiescent catalog activation, not ordinary writer discovery.

        Caller admission must establish compatible quiescent writers. This
        method never upgrades legacy journals or permits catalog replacement.
        """
        root = _root(root)
        info = root.stat()
        catalog = cls(root, dict(schema_version=SCHEMA,
                                root_identity={'device': info.st_dev, 'inode': info.st_ino}, owners=owners))
        # A catalog is not usable until its separate activation receipt exists.
        # Postpublication ancestor/descendant checks prevent concurrent nested
        # activations from both acknowledging success. Failed catalogs remain
        # visible and unusable; no automatic deletion or adoption occurs.
        control = root / '.engineering-bootstrap'
        _reject_nominal_link_chain(control, root, label='ownership control')
        control.mkdir(exist_ok=True)
        with FileLock(control / '.wal-ownership-admission.lock', timeout_seconds=10):
            catalog._reject_ancestor_catalog()
            destination = root / RELATIVE
            if destination.exists() or destination.is_symlink():
                raise WalIntegrityError('ownership catalog already exists')
            # Refuse a parent catalog that would hide an existing nested one.
            # Only activation performs this bounded directory survey.
            catalog._reject_descendant_catalog()
            _write_new(destination, catalog._raw)
            _fsync_directory(control)
            catalog._reject_ancestor_catalog()
            catalog._reject_descendant_catalog()
            _write_new(root / ACTIVATION, _canonical({'schema_version': SCHEMA, 'catalog_sha256': catalog.sha256}))
        return catalog

    def revalidate(self):
        current = type(self).read(self.root)
        if current.sha256 != self.sha256:
            raise WalIntegrityError('ownership catalog generation changed')
        return current

    def require_owner(self, journal):
        journal = Path(journal).resolve(strict=False)
        if journal not in self._owners:
            raise WalIntegrityError('journal has no declared target ownership')
        return journal

    def require_target(self, journal, target):
        journal = self.require_owner(journal)
        nominal = Path(os.path.abspath(target))
        _reject_nominal_link_chain(nominal, self.root, label='owned target')
        target = nominal.resolve(strict=False)
        for path, kind, owner in self._domains:
            if target == path or (kind == 'subtree' and _inside(target, path)):
                if owner == journal:
                    # Hard-link aliases cannot be controlled by pathname
                    # domains. Refuse them instead of asserting exclusivity.
                    if target.exists() and target.is_file() and target.stat().st_nlink != 1:
                        raise WalIntegrityError('multiply linked target has ambiguous ownership')
                    return target
                break
        raise WalIntegrityError('target is outside the journal ownership domain')

    def owner_for_target(self, target):
        target = Path(target).resolve(strict=False)
        for path, kind, owner in self._domains:
            if target == path or (kind == 'subtree' and _inside(target, path)):
                self.require_target(owner, target)
                return owner
        raise WalIntegrityError('target has no declared producer')
