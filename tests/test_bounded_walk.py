from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import os
import tempfile

import pytest

from runtime.bounded_walk import FilesystemWalkError, WalkLimits, bounded_walk
from runtime.intake import inspect_existing_project


@pytest.mark.parametrize("name", ["max_files", "max_depth", "max_bytes", "max_entries", "max_directories"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, float("nan"), float("inf"), "8"])
def test_walk_limits_are_strict_positive_integers(name, value) -> None:
    with pytest.raises(ValueError, match=name):
        WalkLimits(**{name: value})


def test_walk_bounds_empty_directories_and_excluded_listing_work(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / str(index)).mkdir()
    with pytest.raises(FilesystemWalkError, match="max_directories_exceeded"):
        bounded_walk(tmp_path, limits=WalkLimits(max_directories=2))
    with pytest.raises(FilesystemWalkError, match="max_entries_exceeded"):
        bounded_walk(tmp_path, limits=WalkLimits(max_entries=2), exclude=lambda _: True)


def test_walk_stops_listing_before_materializing_oversized_directory(tmp_path: Path, monkeypatch) -> None:
    from runtime import bounded_walk as walker
    for index in range(20):
        (tmp_path / f"{index}.txt").write_text("x", encoding="utf-8")
    original = walker.os.scandir
    consumed = 0
    class ObservedScan:
        def __init__(self, path):
            self.iterator = original(path)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.iterator.close()
        def __iter__(self):
            return self
        def __next__(self):
            nonlocal consumed
            consumed += 1
            return next(self.iterator)
    monkeypatch.setattr(walker.os, "scandir", ObservedScan)
    with pytest.raises(FilesystemWalkError, match="max_files_exceeded"):
        bounded_walk(tmp_path, limits=WalkLimits(max_files=1))
    assert consumed <= 2


def test_walk_checks_cooperative_deadline_without_sleep(tmp_path: Path, monkeypatch) -> None:
    from runtime import bounded_walk as walker
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(walker, "monotonic", lambda: next(ticks), raising=False)
    with pytest.raises(FilesystemWalkError, match="max_duration_exceeded"):
        bounded_walk(tmp_path, limits=WalkLimits(max_duration_seconds=1))


def test_root_link_requires_explicit_follow_policy(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "data.txt").write_text("data", encoding="utf-8")
    link = tmp_path / "alias"
    _symlink_or_skip(target, link)
    for policy in ("reject", "skip"):
        with pytest.raises(FilesystemWalkError, match="symlink_disallowed"):
            bounded_walk(link, symlink_policy=policy)
    assert bounded_walk(link, symlink_policy="follow_within_root").file_count == 1


def test_directory_replacement_during_enumeration_fails_closed(tmp_path: Path, monkeypatch) -> None:
    from runtime import bounded_walk as walker
    root = tmp_path / "root"
    root.mkdir()
    original = walker.os.scandir
    class ReplacingScan:
        def __init__(self, path):
            self.iterator = original(path)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.iterator.close()
        def __iter__(self):
            return self
        def __next__(self):
            try:
                return next(self.iterator)
            except StopIteration:
                self.iterator.close()
                root.rename(tmp_path / "original")
                root.mkdir()
                raise
    monkeypatch.setattr(walker.os, "scandir", ReplacingScan)
    with pytest.raises(FilesystemWalkError, match="directory_identity_changed"):
        bounded_walk(root)


def test_queued_directory_cannot_become_a_link_with_the_same_target_identity(tmp_path: Path, monkeypatch) -> None:
    from runtime import bounded_walk as walker
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    original = walker.os.scandir
    @contextmanager
    def replace_after_listing(path):
        with original(path) as iterator:
            yield iterator
        if Path(path) == root:
            retained = root / "retained-child"
            child.rename(retained)
            _symlink_or_skip(retained, child)
    monkeypatch.setattr(walker.os, "scandir", replace_after_listing)
    with pytest.raises(FilesystemWalkError, match="symlink_disallowed"):
        bounded_walk(root)


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "8"])
def test_walk_duration_is_strict_positive_finite(value) -> None:
    with pytest.raises(ValueError, match="max_duration_seconds"):
        WalkLimits(max_duration_seconds=value)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_windows_junction_obeys_link_policy(tmp_path: Path) -> None:
    import _winapi
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "data.txt").write_text("owned fixture", encoding="utf-8")
    _winapi.CreateJunction(str(outside), str(root / "junction"))
    with pytest.raises(FilesystemWalkError, match="symlink_disallowed"):
        bounded_walk(root)
    assert bounded_walk(root, symlink_policy="skip").file_count == 0
    with pytest.raises(FilesystemWalkError, match="symlink_escape"):
        bounded_walk(root, symlink_policy="follow_within_root")


def _symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symbolic links unavailable: {error}")


def test_walk_is_deterministic_and_matches_intake_file_inventory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "z.py").write_text("z\n", encoding="utf-8")
        (root / "a").mkdir()
        (root / "a" / "B.txt").write_text("b\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "ignored.txt").write_text("ignored\n", encoding="utf-8")

        def excluded(relative: str) -> bool:
            return any(part.casefold() == ".git" for part in Path(relative).parts)

        first = bounded_walk(root, exclude=excluded)
        second = bounded_walk(root, exclude=excluded)
        assert first == second
        assert [item.relative for item in first.files] == ["a/B.txt", "z.py"]
        assert inspect_existing_project(root)["file_count"] == first.file_count


def test_walk_rejects_symlink_escape_and_cycle() -> None:
    with (
        tempfile.TemporaryDirectory() as directory,
        tempfile.TemporaryDirectory() as outside_directory,
    ):
        root = Path(directory)
        outside = Path(outside_directory)
        (outside / "secret.txt").write_text("nope", encoding="utf-8")
        _symlink_or_skip(outside / "secret.txt", root / "escape.txt")
        with pytest.raises(FilesystemWalkError, match="symlink_disallowed") as rejected:
            bounded_walk(root)
        assert rejected.value.as_dict()["code"] == "symlink_disallowed"
        with pytest.raises(FilesystemWalkError, match="symlink_escape") as escaped:
            bounded_walk(root, symlink_policy="follow_within_root")
        assert escaped.value.as_dict()["code"] == "symlink_escape"
        (root / "escape.txt").unlink()
        (root / "loop").mkdir()
        _symlink_or_skip(root, root / "loop" / "back")
        with pytest.raises(FilesystemWalkError, match="directory_cycle"):
            bounded_walk(root, symlink_policy="follow_within_root")


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        (WalkLimits(max_files=1, max_depth=8, max_bytes=20), "max_files_exceeded"),
        (WalkLimits(max_files=8, max_depth=1, max_bytes=20), "max_depth_exceeded"),
        (WalkLimits(max_files=8, max_depth=8, max_bytes=1), "max_bytes_exceeded"),
    ],
)
def test_walk_reports_structured_resource_limits(
    limits: WalkLimits, expected: str
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "one.txt").write_text("one", encoding="utf-8")
        (root / "two.txt").write_text("two", encoding="utf-8")
        (root / "nested").mkdir()
        (root / "nested" / "three.txt").write_text("three", encoding="utf-8")
        with pytest.raises(FilesystemWalkError) as raised:
            bounded_walk(root, limits=limits)
        assert raised.value.code == expected
        expected_limit = {
            "max_files_exceeded": limits.max_files,
            "max_depth_exceeded": limits.max_depth,
            "max_bytes_exceeded": limits.max_bytes,
        }[expected]
        assert raised.value.as_dict()["limit"] == expected_limit
