"""Physical, bounded filesystem primitives shared by Studio publishers."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import stat
import sys
from typing import Callable, TypeVar


E = TypeVar("E", bound=Exception)


def is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0))
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def bounded_directory_entries(
    directory: Path,
    maximum: int,
    error_factory: Callable[[], E],
) -> list[Path]:
    """Enumerate no more than ``maximum`` children before sorting them."""

    entries: list[Path] = []
    with os.scandir(directory) as scanner:
        for entry in scanner:
            if len(entries) >= maximum:
                raise error_factory()
            entries.append(Path(entry.path))
    entries.sort(key=lambda item: item.name.encode("utf-8"))
    return entries


def read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    error_factory: Callable[[], E],
) -> bytes:
    """Read one physical regular file through one descriptor and a hard cap."""

    if maximum_bytes < 0:
        raise error_factory()
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0)) | int(
        getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise error_factory() from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum_bytes:
            raise error_factory()
        chunks: list[bytes] = []
        remaining = info.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size:
            raise error_factory()
        return payload
    finally:
        os.close(descriptor)


def assert_exact_tree(
    root: Path,
    expected_files: set[str],
    expected_directories: set[str],
    maximum_entries: int,
    error_factory: Callable[[], E],
) -> None:
    """Reject links, special files, missing entries, and undeclared topology."""

    try:
        if is_link_or_reparse(root) or not root.is_dir():
            raise error_factory()
    except OSError as error:
        raise error_factory() from error
    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    pending = [(root, "")]
    entry_count = 0
    while pending:
        directory, prefix = pending.pop()
        try:
            entries = bounded_directory_entries(
                directory, maximum_entries - entry_count, error_factory
            )
        except OSError as error:
            raise error_factory() from error
        entry_count += len(entries)
        for entry in reversed(entries):
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                if is_link_or_reparse(entry):
                    raise error_factory()
                if entry.is_dir():
                    if relative not in expected_directories:
                        raise error_factory()
                    observed_directories.add(relative)
                    pending.append((entry, relative))
                elif entry.is_file():
                    if relative not in expected_files:
                        raise error_factory()
                    observed_files.add(relative)
                else:
                    raise error_factory()
            except OSError as error:
                raise error_factory() from error
    if observed_files != expected_files or observed_directories != expected_directories:
        raise error_factory()


def publish_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing an occupied target.

    Python's POSIX ``rename`` may replace an empty destination directory.  Use
    the host's no-replace primitive and fail closed when none is available.
    """

    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if os.name == "nt":
        os.rename(source, destination)  # MoveFile semantics reject occupancy.
        return
    if sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(library, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP, "atomic no-replace directory publication unavailable"
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, source_bytes, -100, destination_bytes, 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))
        return
    if sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        renamex_np = getattr(library, "renamex_np", None)
        if renamex_np is None:
            raise OSError(
                errno.ENOTSUP, "atomic no-replace directory publication unavailable"
            )
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        if renamex_np(source_bytes, destination_bytes, 0x00000004) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))
        return
    raise OSError(
        errno.ENOTSUP, "atomic no-replace directory publication unavailable"
    )
