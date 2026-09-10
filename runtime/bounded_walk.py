"""Deterministic, bounded filesystem traversal for read-only controls.

The walker makes resource ceilings and symlink handling explicit.  It never
follows a link unless the caller selects ``follow_within_root``; that mode
rejects both escapes and identity cycles before yielding a path.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import stat
from time import monotonic
from typing import Callable, Literal


SymlinkPolicy = Literal["reject", "skip", "follow_within_root"]


@dataclass(frozen=True, slots=True)
class WalkLimits:
    """Hard traversal ceilings; all values must be positive."""

    max_files: int = 10_000
    max_depth: int = 64
    max_bytes: int = 256 * 1024 * 1024
    max_entries: int = 200_000
    max_directories: int = 100_000
    max_duration_seconds: float = 300.0

    def __post_init__(self) -> None:
        for name in ("max_files", "max_depth", "max_bytes", "max_entries", "max_directories"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        value = self.max_duration_seconds
        if (type(value) not in (int, float) or value <= 0
                or type(value) is float and not math.isfinite(value)):
            raise ValueError("max_duration_seconds must be positive and finite")


class FilesystemWalkError(ValueError):
    """A structured, fail-closed traversal failure."""

    def __init__(
        self,
        code: str,
        *,
        root: Path,
        path: Path | None = None,
        limit: int | float | None = None,
        observed: int | float | None = None,
    ) -> None:
        self.code = code
        self.root = root
        self.path = path
        self.limit = limit
        self.observed = observed
        details = [code]
        if path is not None:
            details.append(f"path={path.as_posix()}")
        if limit is not None:
            details.append(f"limit={limit}")
        if observed is not None:
            details.append(f"observed={observed}")
        super().__init__("; ".join(details))

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "root": self.root.as_posix(),
            "path": self.path.as_posix() if self.path is not None else None,
            "limit": self.limit,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class WalkEntry:
    """A root-relative filesystem object accepted by :func:`bounded_walk`."""

    path: Path
    relative: str
    kind: Literal["file", "directory"]
    size: int | None


@dataclass(frozen=True, slots=True)
class WalkResult:
    root: Path
    entries: tuple[WalkEntry, ...]
    file_count: int
    total_bytes: int
    directory_count: int = 0
    scanned_entries: int = 0

    @property
    def files(self) -> tuple[WalkEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == "file")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def bounded_walk(
    root: Path,
    *,
    limits: WalkLimits = WalkLimits(),
    symlink_policy: SymlinkPolicy = "reject",
    exclude: Callable[[str], bool] | None = None,
) -> WalkResult:
    """Return a deterministic root-relative tree subject to hard limits.

    ``reject`` fails when any symbolic link is encountered. ``skip`` ignores
    links. ``follow_within_root`` follows links only after containment and
    inode/device cycle checks.  Files are sorted case-insensitively with a
    case-sensitive tie-breaker so the result is stable across runs. ``exclude``
    receives a POSIX root-relative path and prunes matching entries (including
    their directory subtrees) before accepted-file, directory and byte limits
    are considered. All enumerated entries, including excluded ones, count
    toward max_entries. Enumeration streams through these limits before any
    sorting. Duration is a cooperative deadline checked around filesystem
    operations; it cannot interrupt a blocked operating-system call.

    Returned paths are metadata snapshots, not pinned handles or authority.
    Consumers must validate identity and bounds again when opening content.
    """
    if symlink_policy not in {"reject", "skip", "follow_within_root"}:
        raise ValueError("unsupported symlink policy")
    started = monotonic()
    root_info = root.lstat()
    root_is_link = stat.S_ISLNK(root_info.st_mode) or bool(
        getattr(root_info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if root_is_link and symlink_policy != "follow_within_root":
        raise FilesystemWalkError("symlink_disallowed", root=root, path=root)
    if root_is_link and not (
        root.is_symlink() or getattr(root, "is_junction", lambda: False)()
    ):
        raise FilesystemWalkError("unsupported_reparse_point", root=root, path=root)
    canonical_root = root.resolve(strict=True)
    if not canonical_root.is_dir():
        raise ValueError("walk root must be a directory")

    def check_deadline(path: Path) -> None:
        elapsed = monotonic() - started
        if elapsed >= limits.max_duration_seconds:
            raise FilesystemWalkError("max_duration_exceeded", root=canonical_root,
                                      path=path, limit=limits.max_duration_seconds,
                                      observed=elapsed)

    def check_limit(code: str, observed: int, limit: int, path: Path) -> None:
        if observed > limit:
            raise FilesystemWalkError(code, root=canonical_root, path=path,
                                      limit=limit, observed=observed)

    def check_directory(physical: Path, logical: Path, expected: tuple[int, int]) -> None:
        info = physical.lstat()
        linked = stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if linked and symlink_policy != "follow_within_root":
            raise FilesystemWalkError("symlink_disallowed", root=canonical_root, path=logical)
        if linked and not (
            physical.is_symlink() or getattr(physical, "is_junction", lambda: False)()
        ):
            raise FilesystemWalkError("unsupported_reparse_point", root=canonical_root, path=logical)
        if _identity(physical) != expected or not _inside(
            physical.resolve(strict=True), canonical_root
        ):
            raise FilesystemWalkError("directory_identity_changed", root=canonical_root, path=logical)

    entries: list[WalkEntry] = []
    file_count = total_bytes = directory_count = scanned_entries = 0
    root_identity = _identity(canonical_root)
    visited_directories = {root_identity}
    pending = [(canonical_root, canonical_root, 0, root_identity)]
    while pending:
        logical_directory, physical_directory, depth, expected_identity = pending.pop()
        check_deadline(logical_directory)
        queued = []
        try:
            check_directory(physical_directory, logical_directory, expected_identity)
            with os.scandir(physical_directory) as children:
                for child in children:
                    check_deadline(logical_directory)
                    scanned_entries += 1
                    logical_path = logical_directory / child.name
                    relative_path = logical_path.relative_to(canonical_root)
                    relative = relative_path.as_posix()
                    check_limit("max_entries_exceeded", scanned_entries, limits.max_entries, relative_path)
                    if exclude is not None and exclude(relative):
                        continue
                    child_depth = depth + 1
                    check_limit("max_depth_exceeded", child_depth, limits.max_depth, relative_path)
                    physical_path = Path(child.path)
                    try:
                        link_stat = physical_path.lstat()
                    except OSError as error:
                        raise FilesystemWalkError(
                            "path_unreadable", root=canonical_root, path=relative_path
                        ) from error
                    is_link = stat.S_ISLNK(link_stat.st_mode) or bool(
                        getattr(link_stat, "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                    )
                    if is_link:
                        if symlink_policy == "reject":
                            raise FilesystemWalkError("symlink_disallowed", root=canonical_root, path=relative_path)
                        if symlink_policy == "skip":
                            continue
                        if not (physical_path.is_symlink() or getattr(physical_path, "is_junction", lambda: False)()):
                            raise FilesystemWalkError("unsupported_reparse_point", root=canonical_root, path=relative_path)
                        try:
                            physical_path = physical_path.resolve(strict=True)
                        except (OSError, RuntimeError) as error:
                            raise FilesystemWalkError("symlink_unresolvable", root=canonical_root, path=relative_path) from error
                        if not _inside(physical_path, canonical_root):
                            raise FilesystemWalkError("symlink_escape", root=canonical_root, path=relative_path)
                    try:
                        info = physical_path.stat() if is_link else link_stat
                    except OSError as error:
                        raise FilesystemWalkError(
                            "path_unreadable", root=canonical_root, path=relative_path
                        ) from error
                    if stat.S_ISDIR(info.st_mode):
                        identity = (info.st_dev, info.st_ino)
                        if identity in visited_directories:
                            raise FilesystemWalkError("directory_cycle", root=canonical_root, path=relative_path)
                        directory_count += 1
                        check_limit("max_directories_exceeded", directory_count, limits.max_directories, relative_path)
                        visited_directories.add(identity)
                        entries.append(WalkEntry(logical_path, relative, "directory", None))
                        queued.append((logical_path, physical_path, child_depth, identity))
                    elif stat.S_ISREG(info.st_mode):
                        check_limit("max_files_exceeded", file_count + 1, limits.max_files, relative_path)
                        check_limit("max_bytes_exceeded", total_bytes + info.st_size, limits.max_bytes, relative_path)
                        file_count += 1
                        total_bytes += info.st_size
                        entries.append(WalkEntry(logical_path, relative, "file", info.st_size))
                    else:
                        raise FilesystemWalkError("unsupported_file_type", root=canonical_root, path=relative_path)
            check_deadline(logical_directory)
            check_directory(physical_directory, logical_directory, expected_identity)
        except OSError as error:
            raise FilesystemWalkError("directory_unreadable", root=canonical_root,
                                      path=logical_directory) from error
        pending.extend(sorted(queued, key=lambda row: (str(row[0]).casefold(), str(row[0])), reverse=True))
    entries.sort(key=lambda entry: (entry.relative.casefold(), entry.relative))
    return WalkResult(canonical_root, tuple(entries), file_count, total_bytes,
                      directory_count, scanned_entries)
