"""Confined, atomic caller-directed output.

These are the guarantees the six affected `scripts/` producers lacked when their writes
were first audited, and the reason a bare `reports/` grant could not be issued.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.confined_output import ConfinementError, confined_path, publish_json


def test_publication_preserves_an_existing_predictable_staging_file(tmp_path):
    target = tmp_path / "reports/result.json"
    target.parent.mkdir()
    unrelated = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    unrelated.write_bytes(b"retained unrelated data")
    publish_json(tmp_path, target, {"ok": True})
    assert unrelated.read_bytes() == b"retained unrelated data"
    assert json.loads(target.read_text()) == {"ok": True}


def test_move_uses_explicit_project_root_and_refuses_escaping_source_or_target(tmp_path):
    from runtime.confined_output import confined_move

    project = tmp_path / "project"
    project.mkdir()
    source = project / "cache.pyc"
    source.write_bytes(b"owned")
    outside = tmp_path / "outside.pyc"
    outside.write_bytes(b"external")
    with pytest.raises(ConfinementError):
        confined_move(source, outside, root=project)
    with pytest.raises(ConfinementError):
        confined_move(outside, project / "quarantine/external.pyc", root=project)
    assert source.read_bytes() == b"owned"
    assert outside.read_bytes() == b"external"
    target = confined_move(source, Path("quarantine/cache.pyc"), root=project)
    assert target.read_bytes() == b"owned"
    assert not source.exists()


def test_move_resolves_both_relative_paths_against_explicit_root(tmp_path, monkeypatch):
    from runtime.confined_output import confined_move
    project = tmp_path / "project"
    project.mkdir()
    (project / "cache.pyc").write_bytes(b"project-owned")
    (tmp_path / "cache.pyc").write_bytes(b"cwd-owned")
    monkeypatch.chdir(tmp_path)
    target = confined_move(Path("cache.pyc"), Path("quarantine/cache.pyc"), root=project)
    assert target.read_bytes() == b"project-owned"
    assert (tmp_path / "cache.pyc").read_bytes() == b"cwd-owned"


def test_a_relative_destination_is_published_under_the_root(tmp_path: Path) -> None:
    target = publish_json(tmp_path, Path("reports/audit.json"), {"ok": True})
    assert target == (tmp_path / "reports/audit.json").resolve()
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_traversal_out_of_the_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfinementError):
        confined_path(tmp_path, Path("../../escape.json"))


def test_an_absolute_destination_outside_the_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfinementError):
        confined_path(tmp_path, tmp_path.parent / "elsewhere.json")


def test_the_root_itself_is_not_a_valid_destination(tmp_path: Path) -> None:
    with pytest.raises(ConfinementError):
        confined_path(tmp_path, tmp_path)


def test_sibling_prefix_confusion_is_refused(tmp_path: Path) -> None:
    sibling = tmp_path.with_name(tmp_path.name + "-sibling")
    sibling.mkdir()
    with pytest.raises(ConfinementError):
        confined_path(tmp_path, sibling / "x.json")


def test_publication_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    publish_json(tmp_path, Path("reports/a.json"), {"ok": 1})
    leftovers = [p for p in (tmp_path / "reports").iterdir() if p.suffix == ".tmp" or p.name.startswith(".")]
    assert leftovers == []


def test_a_failed_publication_does_not_truncate_an_existing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "reports/a.json"
    publish_json(tmp_path, Path("reports/a.json"), {"version": 1})

    def boom(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        publish_json(tmp_path, Path("reports/a.json"), {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert [p for p in target.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_a_symlinked_destination_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "reports"
    link.mkdir()
    (link / "a.json").symlink_to(outside)
    with pytest.raises(ConfinementError):
        confined_path(tmp_path, Path("reports/a.json"))


@pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
def test_internal_links_are_refused_before_publication(tmp_path, kind):
    target = tmp_path / "retained.json"
    target.write_bytes(b"retained")
    link = tmp_path / "linked"
    if kind == "directory":
        directory = tmp_path / "retained"
        directory.mkdir()
        link.symlink_to(directory, target_is_directory=True)
        destination = link / "new.json"
    else:
        link.symlink_to(target if kind == "file" else tmp_path / "missing.json")
        destination = link
    with pytest.raises(ConfinementError):
        publish_json(tmp_path, destination, {"replacement": True})
    assert target.read_bytes() == b"retained"
    assert link.is_symlink()
    assert not (tmp_path / "missing.json").exists()
    assert not (tmp_path / "retained/new.json").exists()


@pytest.mark.parametrize("kind", ["file", "directory", "descendant", "cross_device"])
def test_move_refuses_unsafe_destination_or_copy_fallback(tmp_path, monkeypatch, kind):
    import errno
    from runtime.confined_output import confined_move

    source = tmp_path / "source"
    source.mkdir()
    (source / "owned.bin").write_bytes(b"owned source")
    destination = tmp_path / "quarantine/retained"
    if kind in {"file", "directory"}:
        # Use file sources for overwrite and directory-container move behavior.
        source = source / "owned.bin"
        destination.parent.mkdir()
        if kind == "file":
            destination.write_bytes(b"retained destination")
        else:
            destination.mkdir()
            (destination / "retained.bin").write_bytes(b"retained destination")
    elif kind == "descendant":
        destination = source / "nested/quarantine"
    else:
        def cross_device(*args, **kwargs):
            raise OSError(errno.EXDEV, "controlled cross-device rename")
        monkeypatch.setattr(os, "rename", cross_device)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, OSError)):
        confined_move(source, destination, root=tmp_path)
    assert source.exists()
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    if kind == "descendant":
        assert not (source / "nested").exists()


@pytest.mark.parametrize('payload', [
    {'value': float('nan')}, {'value': float('inf')}, {'value': -float('inf')},
    {1: 'numeric key', '1': 'string key'},
])
def test_publication_refuses_ambiguous_or_nonfinite_json_before_replacing(tmp_path, payload):
    target = tmp_path / 'report.json'
    target.write_bytes(b'{"previous":true}\n')
    with pytest.raises(ValueError):
        publish_json(tmp_path, target, payload)
    assert target.read_bytes() == b'{"previous":true}\n'
    assert list(tmp_path.glob('*.prepared')) == []


def test_publication_rejects_oversize_string_before_encoder_allocation(tmp_path, monkeypatch):
    import runtime.confined_output as owner
    monkeypatch.setattr(owner, 'MAX_PAYLOAD_BYTES', 128)
    def unexpected_encoder(*args, **kwargs):
        raise AssertionError('encoder reached before obvious payload budget rejection')
    monkeypatch.setattr(json.JSONEncoder, 'iterencode', unexpected_encoder)
    with pytest.raises(ValueError):
        publish_json(tmp_path, Path('report.json'), {'value': 'x' * 1000})
    assert not (tmp_path / 'report.json').exists()


def test_publication_refuses_excessive_json_depth_before_creating_output(tmp_path):
    payload = None
    for _ in range(256):
        payload = [payload]
    with pytest.raises(ValueError):
        publish_json(tmp_path, Path('reports/report.json'), payload)
    assert not (tmp_path / 'reports').exists()


def test_publication_preserves_valid_unicode_and_finite_json_values(tmp_path):
    payload = {'text': '\u03bb', 'values': [None, True, False, 1, -0.25, {'nested': 'ok'}]}
    target = publish_json(tmp_path, Path('report.json'), payload)
    assert json.loads(target.read_text(encoding='utf-8')) == payload
    assert target.read_bytes().endswith(b'\n')


def test_publication_byte_ceiling_includes_trailing_newline(tmp_path, monkeypatch):
    import runtime.confined_output as owner
    monkeypatch.setattr(owner, 'MAX_PAYLOAD_BYTES', 5)
    target = publish_json(tmp_path, Path('fits.json'), None)
    assert target.read_bytes() == b'null\n'
    monkeypatch.setattr(owner, 'MAX_PAYLOAD_BYTES', 4)
    with pytest.raises(ConfinementError):
        publish_json(tmp_path, Path('oversize.json'), None)
    assert not (tmp_path / 'oversize.json').exists()
