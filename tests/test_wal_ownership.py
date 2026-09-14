from __future__ import annotations

import json
import os

import pytest

from runtime.wal_ownership import RELATIVE, SCHEMA, WalOwnership
from runtime.wal_transaction import WalIntegrityError


def _catalog(root, owners):
    info = root.stat()
    return WalOwnership(root, dict(schema_version=SCHEMA, root_identity=dict(device=info.st_dev, inode=info.st_ino), owners=owners))


def _owner(journal, path, kind='subtree'):
    return dict(journal=journal, domains=[dict(path=path, kind=kind)])


def test_disjoint_domains_bind_same_owner_across_containment_aliases(tmp_path):
    catalog = _catalog(tmp_path, [_owner('journals/a', 'state/a'), _owner('journals/b', 'state/b')])
    assert catalog.require_target(tmp_path / 'journals/a', tmp_path / 'state/a/value.json') == tmp_path / 'state/a/value.json'
    with pytest.raises(WalIntegrityError):
        catalog.require_target(tmp_path / 'journals/b', tmp_path / 'state/a/value.json')


@pytest.mark.parametrize('left,right', [('state', 'state/x'), ('state/x', 'state'), ('state', 'state')])
@pytest.mark.parametrize('kind', ['exact', 'subtree'])
def test_nested_and_exact_cross_owner_overlap_refuses(tmp_path, left, right, kind):
    # At least the enclosing declaration is a subtree.
    left_kind = 'subtree' if left == 'state' else kind
    right_kind = 'subtree' if right == 'state' else kind
    with pytest.raises(WalIntegrityError):
        _catalog(tmp_path, [_owner('journals/a', left, left_kind), _owner('journals/b', right, right_kind)])


def test_windows_case_alias_cannot_create_another_owner(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows physical path comparison')
    with pytest.raises(WalIntegrityError):
        _catalog(tmp_path, [_owner('journals/a', 'State'), _owner('journals/b', 'state')])


@pytest.mark.parametrize('path', ['journals', 'journals/a/head', '.engineering-bootstrap/wal-ownership.json'])
def test_metadata_cannot_be_claimed_as_target(tmp_path, path):
    with pytest.raises(WalIntegrityError):
        _catalog(tmp_path, [_owner('journals/a', path)])


@pytest.mark.parametrize('path', ['../escape', '.', 'state/../other', '/absolute'])
def test_invalid_domain_is_refused_without_effect(tmp_path, path):
    with pytest.raises((ValueError, WalIntegrityError)):
        _catalog(tmp_path, [_owner('journals/a', path)])
    assert list(tmp_path.iterdir()) == []


def test_catalog_activation_is_explicit_immutable_and_current(tmp_path):
    owners = [_owner('journals/a', 'state')]
    catalog = WalOwnership.activate(tmp_path, owners)
    assert WalOwnership.read(tmp_path).sha256 == catalog.sha256
    with pytest.raises(WalIntegrityError):
        WalOwnership.activate(tmp_path, owners)
    value = json.loads((tmp_path / RELATIVE).read_bytes())
    value['owners'][0]['domains'][0]['path'] = 'other'
    from runtime.wal_transaction import _canonical
    (tmp_path / RELATIVE).write_bytes(_canonical(value))
    with pytest.raises(WalIntegrityError):
        catalog.revalidate()


@pytest.mark.parametrize('parent_first', [True, False])
def test_nested_catalog_cannot_replace_authority_root(tmp_path, parent_first):
    child = tmp_path / 'child'
    child.mkdir()
    first, second = (tmp_path, child) if parent_first else (child, tmp_path)
    WalOwnership.activate(first, [_owner('journals/a', 'state')])
    with pytest.raises(WalIntegrityError):
        WalOwnership.activate(second, [_owner('journals/b', 'state')])


def test_hardlink_alias_is_not_exclusive_target_ownership(tmp_path):
    target = tmp_path / 'state'
    target.write_bytes(b'original')
    os.link(target, tmp_path / 'alias')
    catalog = _catalog(tmp_path, [_owner('journal', 'state', 'exact')])
    with pytest.raises(WalIntegrityError):
        catalog.require_target(tmp_path / 'journal', target)


def test_concurrent_nested_activations_cannot_both_complete(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import runtime.wal_ownership as module
    child = tmp_path / 'child'
    child.mkdir()
    barrier = threading.Barrier(2)
    write = module._write_new
    def concurrent_publication(path, raw):
        if path.name == 'wal-ownership.json':
            barrier.wait(timeout=10)
            write(path, raw)
            barrier.wait(timeout=10)
        else:
            write(path, raw)
    monkeypatch.setattr(module, '_write_new', concurrent_publication)
    def activate(root):
        try:
            WalOwnership.activate(root, [_owner('journal', 'state')])
            return True
        except WalIntegrityError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate, [tmp_path, child]))
    assert results != [True, True]
    assert sum(results) == 0  # both catalogs are published before either check
    for root in (tmp_path, child):
        with pytest.raises(WalIntegrityError):
            WalOwnership.read(root)
