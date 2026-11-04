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
