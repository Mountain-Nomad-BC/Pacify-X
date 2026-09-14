"""Shared contained source images; metadata checks do not grant authority."""

from __future__ import annotations
import math
import os
from pathlib import Path
import stat
import time

from .archive_io import portable_member_name, reject_path_links
from .numeric_inputs import bounded_text


def relative_source_path(value: object) -> str:
    result = portable_member_name(
        bounded_text(value, "source path", maximum=4096, strip=False),
        allow_directory=False,
    )
    if any(
        part.casefold() in {"quarantine", ".quarantine", "_quarantine"}
        for part in result.split("/")[:-1]
    ):
        raise ValueError("source path is excluded from acquisition")
    return result


def check_deadline(deadline: float) -> None:
    if (
        type(deadline) not in (int, float)
        or not 0 < deadline < 1e100
        or not math.isfinite(deadline)
    ):
        raise ValueError("source deadline must be finite and positive")
    if time.monotonic() >= deadline:
        raise ValueError("source acquisition exceeded its cooperative duration budget")


def cooperative_deadline(deadline: float | None = None) -> float:
    now = time.monotonic()
    if deadline is None:
        return now + 60.0
    if (
        type(deadline) not in (int, float)
        or not 0 < deadline < 1e100
        or not math.isfinite(deadline)
    ):
        raise ValueError("metadata deadline must be finite and positive")
    return min(float(deadline), now + 60.0)


def contained_file(root: Path, relative: str):
    reject_path_links(root)
    path = root / relative_source_path(relative)
    reject_path_links(path)
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("source path escapes trusted root")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("source input must be a regular file")
    return path, info


def read_file_image(
    path: Path,
    info,
    *,
    limit: int,
    deadline: float,
    links_checked: bool = False,
) -> bytearray:
    """Read one complete image, preserving the existing64MiB materialization cap."""
    check_deadline(deadline)
    if type(limit) is not int or not 0 <= limit <= 64 * 1024 * 1024:
        raise ValueError("source byte budget must be a bounded nonnegative integer")
    from contextlib import closing

    raw = bytearray()
    with closing(
        iter_file_image(
            path,
            info,
            limit=limit,
            deadline=deadline,
            links_checked=links_checked,
        )
    ) as chunks:
        for chunk in chunks:
            raw.extend(chunk)
    return raw


def read_file_prefix(
    path: Path, info, *, limit: int, deadline: float
) -> tuple[bytes, bool]:
    """Read at most a bounded prefix plus one byte proving truncation.

    The caller supplies contained-file metadata. This checks the original path
    and opened regular-file identity, but does not pin ancestors or interrupt OS
    calls. A prefix never claims to hash or validate the whole file.
    """
    check_deadline(deadline)
    if type(limit) is not int or not 1 <= limit <= 65536:
        raise ValueError("prefix budget must be an integer in 1..65536")
    if info.st_size < 0:
        raise ValueError("invalid source size")
    reject_path_links(path)
    raw = bytearray()
    expected = min(info.st_size, limit + 1)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise ValueError("prefix source changed before acquisition")
        # For short files, the extra EOF witness also detects growth.
        wanted = min(info.st_size + 1, limit + 1)
        while len(raw) < wanted:
            check_deadline(deadline)
            chunk = stream.read(min(65536, wanted - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(stream.fileno())
    check_deadline(deadline)
    if len(raw) != expected or (after.st_size, after.st_mtime_ns) != (
        info.st_size,
        info.st_mtime_ns,
    ):
        raise ValueError("prefix source changed during acquisition")
    return bytes(raw[:limit]), len(raw) > limit


def _input_path(value: Path) -> Path:
    """Validate an original native path; this never grants filesystem authority."""
    if type(value) is not type(Path()):
        raise ValueError("input must be an actual filesystem path")
    bounded_text(str(value), "input path", maximum=4096, strip=False)
    if any(
        p == ".." or p.casefold() in {"quarantine", ".quarantine", "_quarantine"}
        for p in value.parts
    ):
        raise ValueError("input path is outside the admitted corpus")
    reject_path_links(value)
    absolute = value.absolute()
    bounded_text(str(absolute), "absolute input path", maximum=4096, strip=False)
    if any(
        p.casefold() in {"quarantine", ".quarantine", "_quarantine"}
        for p in absolute.parts
    ):
        raise ValueError("input path is outside the admitted corpus")
    reject_path_links(absolute)
    return absolute


def directory_root(value: Path) -> Path:
    """Check an original physical directory without granting source authority."""
    result = _input_path(value).resolve(strict=True)
    if not result.is_dir():
        raise ValueError("input root must be a directory")
    return result


def independent_file(value: Path):
    """Check an explicitly supplied file without assigning source-root authority.

    The caller owns admission of this independent input. Original components are
    checked before normalization; checks do not pin ancestor handles.
    """
    absolute = _input_path(value)
    return contained_file(absolute.parent, absolute.name)


def iter_file_image(
    path: Path,
    info,
    *,
    limit: int,
    deadline: float,
    links_checked: bool = False,
):
    """Yield bounded chunks from one checked handle; exhaust before claiming validity.

    Closing early releases the handle but does not establish complete-image
    verification. Consumers which can stop or raise must close this iterator.
    The streaming ceiling does not increase read_file_image's materialization cap.
    Path checks do not pin ancestors or interrupt blocked operating-system calls.
    """
    check_deadline(deadline)
    if type(links_checked) is not bool:
        raise ValueError("links-checked state must be an actual boolean")
    if type(limit) is not int or not 0 <= limit <= 256 * 1024 * 1024:
        raise ValueError("stream byte budget must be a bounded nonnegative integer")
    if not 0 <= info.st_size <= limit:
        raise ValueError("source byte budget exhausted before acquisition")
    if not links_checked:
        reject_path_links(path)
    expected = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    received = 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != expected
        ):
            raise ValueError("source input changed before acquisition")
        while received <= info.st_size:
            check_deadline(deadline)
            chunk = stream.read(min(65536, info.st_size + 1 - received))
            if not chunk:
                break
            received += len(chunk)
            if received > info.st_size:
                raise ValueError("source input changed during acquisition")
            yield chunk
        after = os.fstat(stream.fileno())
        check_deadline(deadline)
        if (
            received != info.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != expected
        ):
            raise ValueError("source input changed during acquisition")
