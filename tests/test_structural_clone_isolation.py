"""Mutation clones must never share source inodes with the real checkout."""
import os
from tests import test_structural_integrity as structural_tests

def test_structural_clone_cannot_alias_or_mutate_live_source(tmp_path, monkeypatch) -> None:
    source = tmp_path / "live"
    (source / "registry").mkdir(parents=True)
    original = source / "registry/test_profiles.json"
    original.write_bytes(b'{"original":true}\n')
    monkeypatch.setattr(structural_tests, "ROOT", source)
    destination = tmp_path / "owned-clone"
    clone = structural_tests._clone(destination)
    copied = clone / "registry/test_profiles.json"
    assert not os.path.samefile(original, copied)
    assert original.stat().st_nlink == copied.stat().st_nlink == 1
    copied.write_bytes(b'{"mutated":true}\n')
    assert original.read_bytes() == b'{"original":true}\n'
    assert original.stat().st_nlink == 1
