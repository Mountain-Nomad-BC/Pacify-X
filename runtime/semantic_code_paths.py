"""Containment-safe path handling for semantic code operations."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class SemanticPathError(ValueError):
    pass


def canonical_project_root(root: Path) -> Path:
    resolved = root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise SemanticPathError("project root must be a directory")
    return resolved


def normalize_relative_path(relative_path: str) -> str:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise SemanticPathError("relative path must be non-empty text")
    candidate = relative_path.replace("\\", "/")
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SemanticPathError("path must be a normalized project-relative path")
    return pure.as_posix()


def resolve_project_path(
    root: Path,
    relative_path: str,
    *,
    must_exist: bool = True,
    require_file: bool = False,
) -> Path:
    root = canonical_project_root(root)
    relative = normalize_relative_path(relative_path)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except OSError as error:
        raise SemanticPathError(f"path is unavailable: {relative}") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise SemanticPathError(f"path escapes project root: {relative}") from error
    if require_file and (not resolved.exists() or not resolved.is_file()):
        raise SemanticPathError(f"path is not a file: {relative}")
    return resolved


def project_relative(root: Path, path: Path) -> str:
    root = canonical_project_root(root)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise SemanticPathError("path is outside project root") from error
