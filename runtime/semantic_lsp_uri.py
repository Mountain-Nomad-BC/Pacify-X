"""Project-contained file URI conversion for LSP."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from .semantic_code_paths import canonical_project_root, normalize_relative_path, resolve_project_path


class LspUriError(ValueError):
    pass


def path_to_file_uri(path: Path) -> str:
    return path.expanduser().resolve(strict=False).as_uri()


def relative_path_to_uri(root: Path, relative_path: str) -> str:
    root = canonical_project_root(root)
    path = resolve_project_path(root, normalize_relative_path(relative_path), must_exist=False)
    return path_to_file_uri(path)


def file_uri_to_path(uri: str) -> Path:
    if not isinstance(uri, str) or not uri:
        raise LspUriError("file URI must be non-empty text")
    parsed = urlparse(uri)
    if parsed.scheme.casefold() != "file":
        raise LspUriError("only file:// URIs are accepted for project source")
    if parsed.netloc not in ("", "localhost"):
        raise LspUriError("remote file URI authority is not accepted")
    raw = unquote(parsed.path)
    if not raw:
        raise LspUriError("empty file URI path")
    if os.name == "nt" and len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw).resolve(strict=False)


def uri_to_relative_path(root: Path, uri: str, *, allow_external: bool = False) -> str:
    root = canonical_project_root(root)
    path = file_uri_to_path(uri)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        if allow_external:
            return f"<external:{path.as_posix()}>"
        raise LspUriError("language-server URI escapes project root") from exc
    return normalize_relative_path(relative.as_posix())
