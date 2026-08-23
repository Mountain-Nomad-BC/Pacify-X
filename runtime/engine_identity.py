"""Deterministic source-engine identity for installed-host evidence binding."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .repository_scope import is_external_environment_relative


EXCLUDED_DIRECTORIES = {
    ".git",
    ".engineering-bootstrap",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode-test",
    "__pycache__",
    "build",
    "dist",
    "evidence",
    "node_modules",
    "preserved-extension-installations",
    "preserved-skills",
    "python",
}
EXCLUDED_PATHS = {
    "AUDIT_BUNDLE_README.md",
    "AUDIT_REPLAY_CONTRACT.json",
    "registry/completion_status.json",
    "registry/current_evidence_index.json",
    "registry/engine_identity.json",
    "registry/test_group_index.json",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".vsix"}


def _files(root: Path) -> list[Path]:
    values: list[Path] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        relative_current = Path(current).relative_to(root)
        dirs[:] = sorted(
            (
                name
                for name in dirs
                if name.casefold() not in EXCLUDED_DIRECTORIES
                and not name.casefold().startswith(".venv")
                and not (
                    relative_current.as_posix() == "extension"
                    and name.casefold() == "evidence"
                )
                and not (
                    relative_current.as_posix() == ".px"
                    and name.casefold() == "preserved-skills"
                )
            ),
            key=str.casefold,
        )
        for name in sorted(files, key=str.casefold):
            path = Path(current, name)
            relative = path.relative_to(root).as_posix()
            if (
                path.is_symlink()
                or is_external_environment_relative(relative)
                or relative.startswith("AUDIT_ARTIFACTS/")
                or relative in EXCLUDED_PATHS
                or path.suffix.casefold() in EXCLUDED_SUFFIXES
                or path.name == "SHA256SUMS.txt"
                or path.name == "AUDIT_EXPORT_MANIFEST.json"
                or path.name.startswith(".env")
            ):
                continue
            values.append(path)
    return sorted(values, key=lambda item: item.relative_to(root).as_posix().casefold())


def build_engine_identity(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    records = []
    tree = hashlib.sha256()
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        sha256 = hashlib.sha256(payload).hexdigest()
        record = {"path": relative, "bytes": len(payload), "sha256": sha256}
        records.append(record)
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(bytes.fromhex(sha256))
        tree.update(b"\0")
    return {
        "schema_version": "px.engine-identity/1.0",
        "authority": "CPU-authoritative exact file bytes; mutable evidence and runtime state excluded.",
        "file_total": len(records),
        "tree_sha256": tree.hexdigest(),
        "records": records,
    }


def write_engine_identity(root: Path) -> tuple[Path, dict[str, Any]]:
    root = root.resolve(strict=True)
    target = root / "registry/engine_identity.json"
    value = build_engine_identity(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    prepared = target.with_name(f".{target.name}.{os.getpid()}.prepared")
    prepared.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(prepared, target)
    return target, value


def validate_engine_identity(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = root / "registry/engine_identity.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = None
    current = build_engine_identity(root)
    return {
        "schema_version": "px.engine-identity-validation/1.0",
        "valid": stored == current,
        "manifest_path": "registry/engine_identity.json",
        "manifest_sha256": (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        ),
        "tree_sha256": current["tree_sha256"],
        "file_total": current["file_total"],
    }
