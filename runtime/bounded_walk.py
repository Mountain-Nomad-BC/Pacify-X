"""Deterministic, bounded filesystem traversal for read-only controls.

The walker makes resource ceilings and symlink handling explicit.  It never
follows a link unless the caller selects ``follow_within_root``; that mode
rejects both escapes and identity cycles before yielding a path.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, Literal


SymlinkPolicy = Literal["reject", "skip", "follow_within_root"]


@dataclass(frozen=True, slots=True)
class WalkLimits:
    """Hard traversal ceilings; all values must be positive."""

    max_files: int = 10_000
    max_depth: int = 64
    max_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in ("max_files", "max_depth", "max_bytes"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")


class FilesystemWalkError(ValueError):
    """A structured, fail-closed traversal failure."""

    def __init__(
        self,
        code: str,
        *,
        root: Path,
        path: Path | None = None,
        limit: int | None = None,
        observed: int | None = None,
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
    their directory subtrees) before resource limits are considered.
    """
    if symlink_policy not in {"reject", "skip", "follow_within_root"}:
        raise ValueError("unsupported symlink policy")
    canonical_root = root.resolve(strict=True)
    if not canonical_root.is_dir():
        raise ValueError("walk root must be a directory")

    entries: list[WalkEntry] = []
    file_count = 0
    total_bytes = 0
    visited_directories = {_identity(canonical_root)}
    pending: list[tuple[Path, Path, int]] = [(canonical_root, canonical_root, 0)]

    while pending:
        logical_directory, physical_directory, depth = pending.pop()
        try:
            children = sorted(
                os.scandir(physical_directory),
                key=lambda item: (item.name.casefold(), item.name),
            )
        except OSError as error:
            raise FilesystemWalkError(
                "directory_unreadable", root=canonical_root, path=logical_directory
            ) from error
        for child in reversed(children):
            logical_path = logical_directory / child.name
            relative_path = logical_path.relative_to(canonical_root)
            relative = relative_path.as_posix()
            if exclude is not None and exclude(relative):
                continue
            child_depth = depth + 1
            if child_depth > limits.max_depth:
                raise FilesystemWalkError(
                    "max_depth_exceeded",
                    root=canonical_root,
                    path=relative_path,
                    limit=limits.max_depth,
                    observed=child_depth,
                )
            is_link = child.is_symlink()
            if is_link:
                if symlink_policy == "reject":
                    raise FilesystemWalkError(
                        "symlink_disallowed", root=canonical_root, path=relative_path
                    )
                if symlink_policy == "skip":
                    continue
                try:
                    physical_path = Path(child.path).resolve(strict=True)
                except OSError as error:
                    raise FilesystemWalkError(
                        "symlink_unresolvable", root=canonical_root, path=relative_path
                    ) from error
                if not _inside(physical_path, canonical_root):
                    raise FilesystemWalkError(
                        "symlink_escape", root=canonical_root, path=relative_path
                    )
            else:
                physical_path = Path(child.path)

            try:
                if physical_path.is_dir():
                    identity = _identity(physical_path)
                    if identity in visited_directories:
                        raise FilesystemWalkError(
                            "directory_cycle", root=canonical_root, path=relative_path
                        )
                    visited_directories.add(identity)
                    entries.append(WalkEntry(logical_path, relative, "directory", None))
                    pending.append((logical_path, physical_path, child_depth))
                elif physical_path.is_file():
                    size = physical_path.stat().st_size
                    next_file_count = file_count + 1
                    next_total_bytes = total_bytes + size
                    if next_file_count > limits.max_files:
                        raise FilesystemWalkError(
                            "max_files_exceeded",
                            root=canonical_root,
                            path=relative_path,
                            limit=limits.max_files,
                            observed=next_file_count,
                        )
                    if next_total_bytes > limits.max_bytes:
                        raise FilesystemWalkError(
                            "max_bytes_exceeded",
                            root=canonical_root,
                            path=relative_path,
                            limit=limits.max_bytes,
                            observed=next_total_bytes,
                        )
                    file_count = next_file_count
                    total_bytes = next_total_bytes
                    entries.append(WalkEntry(logical_path, relative, "file", size))
            except OSError as error:
                raise FilesystemWalkError(
                    "path_unreadable", root=canonical_root, path=relative_path
                ) from error

    entries.sort(key=lambda entry: (entry.relative.casefold(), entry.relative))
    return WalkResult(canonical_root, tuple(entries), file_count, total_bytes)
