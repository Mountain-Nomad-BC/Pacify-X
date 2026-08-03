from __future__ import annotations

from pathlib import Path
import os
import tempfile

import pytest

from runtime.bounded_walk import FilesystemWalkError, WalkLimits, bounded_walk
from runtime.intake import inspect_existing_project


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
        excluded = lambda relative: any(part.casefold() == ".git" for part in Path(relative).parts)
        first = bounded_walk(root, exclude=excluded)
        second = bounded_walk(root, exclude=excluded)
        assert first == second
        assert [item.relative for item in first.files] == ["a/B.txt", "z.py"]
        assert inspect_existing_project(root)["file_count"] == first.file_count


def test_walk_rejects_symlink_escape_and_cycle() -> None:
    with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
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
def test_walk_reports_structured_resource_limits(limits: WalkLimits, expected: str) -> None:
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
