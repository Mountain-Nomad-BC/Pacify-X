"""Governed skill draft, validation, preservation, promotion, and rollback."""

from __future__ import annotations

import ast
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tomllib
from typing import Mapping
import unicodedata
from uuid import uuid4

import yaml

from .file_lock import FileLock
from .studio_filesystem import assert_exact_tree, publish_directory_no_replace
from .resource_lifecycle import ResourceManager, RunState
from .native_skills import build_skill_index, validate_skill_index
from .studio_authority import StudioAuthorityStore
from .studio_models import (
    SkillPackage,
    digest,
    revalidate_studio_version_allocation,
    studio_revision_lock,
    StudioVersionConflict,
    verify_safe_ancestors,
    write_json_atomic,
)


CONTROL_FILES = frozenset(
    {
        "package-record.json",
        "validation-receipt.json",
        "admission-receipt.json",
        "promotion-receipt.json",
    }
)
IGNORED_PARTS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_+/=-]{12,}"
)
MAX_SKILL_FILES = 128
MAX_SKILL_BYTES = 2 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 512 * 1024
MAX_SKILL_DEPTH = 12
MAX_SKILL_DIRECTORIES = 256
MAX_SKILL_ENTRIES = MAX_SKILL_FILES + MAX_SKILL_DIRECTORIES
MAX_SKILL_PATH_BYTES = 4096
MAX_LIFECYCLE_ARTIFACTS = 24
MAX_LIFECYCLE_ARTIFACT_BYTES = 16 * 1024 * 1024
LIFECYCLE_TRANSACTION_SCHEMA = "px.skill-lifecycle-transaction/1.0"
WINDOWS_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.I)
WINDOWS_ALIAS_CHARACTERS = frozenset('<>:"|?*')
TREE_COMMITMENT_DOMAIN = b"px.skill-tree/2\0"
PRESERVED_ORIGINAL_SCHEMA = "px.preserved-skill-provenance/1.0"
PRESERVED_PROVENANCE_FIELDS = {
    "schema_version": "preserved_original_schema_version",
    "skill_id": "preserved_original_skill_id",
    "source_version": "preserved_original_source_version",
    "origin": "preserved_original_origin",
    "package_relative": "preserved_original_package_relative",
    "tree_sha256": "preserved_original_tree_sha256",
    "body_sha256": "preserved_original_body_sha256",
    "file_count": "preserved_original_file_count",
}
_SHA256 = re.compile(r"[a-f0-9]{64}")
_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:[-.][a-z0-9][a-z0-9.-]{0,63})?"
)


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


_MAX_CREATE_CLEANUP_WARNINGS = 8
_MAX_CREATE_CLEANUP_WARNING_CHARS = 240


def _bounded_cleanup_warnings(errors: list[object]) -> list[str]:
    """Return bounded diagnostics without reclassifying an immutable publication."""

    warnings: list[str] = []
    for error in errors[:_MAX_CREATE_CLEANUP_WARNINGS]:
        warning = str(error).strip()
        if warning:
            warnings.append(warning[:_MAX_CREATE_CLEANUP_WARNING_CHARS])
    return warnings


def _component(value: str) -> str:
    return f"{re.sub(r'[^a-z0-9._-]+', '-', value).strip('-')}-{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def _canonical_name(value: str) -> str:
    candidate = value.removeprefix("skill:").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", candidate):
        raise ValueError("skill ID cannot be compiled to a canonical package directory")
    return candidate


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0))
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _portable_relative_path(relative: Path) -> str:
    canonical = relative.as_posix()
    parts = canonical.split("/")
    if (
        not canonical
        or canonical.startswith("/")
        or len(canonical.encode("utf-8")) > MAX_SKILL_PATH_BYTES
        or len(parts) > MAX_SKILL_DEPTH
    ):
        raise ValueError("skill package contains a nonportable path")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or unicodedata.normalize("NFC", part) != part
            or len(part.encode("utf-8")) > 255
            or part.endswith((".", " "))
            or "\\" in part
            or any(character in WINDOWS_ALIAS_CHARACTERS or ord(character) < 32 for character in part)
            or WINDOWS_DEVICE.fullmatch(part) is not None
        ):
            raise ValueError("skill package contains a nonportable path")
    return canonical


def _read_bounded_regular_file(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0)) | int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("skill package contains a non-regular file")
        if info.st_size > limit:
            raise ValueError("skill package contains an oversized file")
        chunks: list[bytes] = []
        remaining = info.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != info.st_size:
            raise ValueError("skill source changed during admission")
        return data
    finally:
        os.close(descriptor)


def _framed_tree_commitment(materialized: list[tuple[str, bytes]]) -> str:
    ordered = sorted(materialized, key=lambda item: item[0].encode("utf-8"))
    tree_hash = hashlib.sha256()
    tree_hash.update(TREE_COMMITMENT_DOMAIN)
    tree_hash.update(struct.pack(">Q", len(ordered)))
    for relative_path, data in ordered:
        encoded_path = relative_path.encode("utf-8")
        tree_hash.update(struct.pack(">Q", len(encoded_path)))
        tree_hash.update(encoded_path)
        tree_hash.update(struct.pack(">Q", len(data)))
        tree_hash.update(data)
    return tree_hash.hexdigest()


def _tree_attestation(
    root: Path,
) -> tuple[list[dict[str, object]], str]:
    """Inventory once and derive the exact editor-materialization tree digest."""
    if _is_link_or_reparse(root):
        raise ValueError("skill package links or reparse points are not admitted")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("skill package root must be a directory")
    rows: list[dict[str, object]] = []
    materialized: list[tuple[str, bytes]] = []
    observed_directories: set[str] = set()
    physical_paths: dict[str, tuple[str, str]] = {}
    total_bytes = 0
    directory_count = 0
    entry_count = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        if _is_link_or_reparse(directory):
            raise ValueError("skill package links or reparse points are not admitted")
        entries: list[Path] = []
        with os.scandir(directory) as scanner:
            for entry in scanner:
                entry_count += 1
                if entry_count > MAX_SKILL_ENTRIES:
                    raise ValueError("skill package exceeds the maximum entry count")
                entries.append(Path(entry.path))
        for path in sorted(entries, key=lambda item: item.name.encode("utf-8"), reverse=True):
            relative = path.relative_to(root)
            relative_path = _portable_relative_path(relative)
            if IGNORED_PARTS.intersection(relative.parts) or path.name in CONTROL_FILES:
                raise ValueError("skill package contains an injected control or cache entry")
            if _is_link_or_reparse(path):
                raise ValueError(
                    "skill package links or reparse points are not admitted"
                )
            kind = "directory" if path.is_dir() else "file"
            alias = relative_path.lower()
            existing = physical_paths.get(alias)
            if existing is not None and existing != (relative_path, kind):
                raise ValueError("skill package contains duplicate canonical path aliases")
            if existing is not None:
                raise ValueError("skill package contains a duplicate canonical path")
            physical_paths[alias] = (relative_path, kind)
            if path.is_dir():
                directory_count += 1
                if directory_count > MAX_SKILL_DIRECTORIES:
                    raise ValueError("skill package exceeds the maximum directory count")
                observed_directories.add(relative_path)
                pending.append(path)
                continue
            if not path.is_file():
                raise ValueError("skill package contains a non-regular entry")
            if len(rows) >= MAX_SKILL_FILES:
                raise ValueError("skill package exceeds the maximum file count")
            data = _read_bounded_regular_file(
                path, min(MAX_SKILL_FILE_BYTES, MAX_SKILL_BYTES - total_bytes)
            )
            total_bytes += len(data)
            rows.append(
                {
                    "path": relative_path,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            materialized.append((relative_path, data))
    rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    expected_directories = {
        "/".join(str(row["path"]).split("/")[:index])
        for row in rows
        for index in range(1, len(str(row["path"]).split("/")))
    }
    if observed_directories != expected_directories:
        raise ValueError("skill package contains an empty or unowned directory")
    return rows, _framed_tree_commitment(materialized)


def _tree(root: Path) -> list[dict[str, object]]:
    """Inventory without ever following a link/reparse directory."""
    return _tree_attestation(root)[0]


def _preserved_original_provenance(
    project_root: Path, package: SkillPackage
) -> dict[str, object] | None:
    """Independently revalidate a host-bound immutable original.

    Reserved provenance is all-or-nothing.  The caller-supplied values are never
    admission evidence by themselves: the preserved package is bounded beneath
    PX custody and its complete tree plus body are rehashed here.
    """

    supplied = dict(package.provenance)
    present = {
        field for field in PRESERVED_PROVENANCE_FIELDS.values() if field in supplied
    }
    if not present:
        return None
    if present != set(PRESERVED_PROVENANCE_FIELDS.values()):
        raise ValueError("preserved-original provenance is incomplete")
    values = {
        key: str(supplied[field])
        for key, field in PRESERVED_PROVENANCE_FIELDS.items()
    }
    if (
        values["schema_version"] != PRESERVED_ORIGINAL_SCHEMA
        or values["skill_id"] != package.skill_id
        or _VERSION.fullmatch(values["source_version"]) is None
        or not values["origin"]
        or len(values["origin"]) > 200
        or _SHA256.fullmatch(values["tree_sha256"]) is None
        or _SHA256.fullmatch(values["body_sha256"]) is None
        or not values["file_count"].isdigit()
    ):
        raise ValueError("preserved-original provenance is invalid")
    file_count = int(values["file_count"])
    if not 1 <= file_count <= MAX_SKILL_FILES:
        raise ValueError("preserved-original file count is invalid")
    relative_text = values["package_relative"]
    relative = Path(relative_text)
    if (
        not relative_text.startswith(".px/preserved-skills/")
        or "\\" in relative_text
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != relative_text
    ):
        raise ValueError("preserved-original package path is outside PX custody")
    project = project_root.resolve(strict=True)
    preserved_root = (project / ".px" / "preserved-skills").resolve(strict=True)
    target = (project / relative).resolve(strict=True)
    if target == preserved_root or preserved_root not in target.parents:
        raise ValueError("preserved-original package path is outside PX custody")
    verify_safe_ancestors(project, target, include_target=True)
    rows, tree_sha256 = _tree_attestation(target)
    body = target / "SKILL.md"
    if (
        len(rows) != file_count
        or tree_sha256 != values["tree_sha256"]
        or not body.is_file()
        or hashlib.sha256(_read_bounded_regular_file(body, MAX_SKILL_FILE_BYTES)).hexdigest()
        != values["body_sha256"]
    ):
        raise PermissionError("preserved-original package identity changed")
    return {
        "schema_version": PRESERVED_ORIGINAL_SCHEMA,
        "skill_id": values["skill_id"],
        "source_version": values["source_version"],
        "origin": values["origin"],
        "package_relative": relative_text,
        "tree_sha256": tree_sha256,
        "body_sha256": values["body_sha256"],
        "file_count": file_count,
    }


def _run_declarative_test(value: object, files: set[str], payload: Path) -> tuple[bool, str]:
    if not isinstance(value, Mapping) or value.get("schema_version") != "px.skill-test/1.1":
        return False, "unsupported_test_contract"
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 64:
        return False, "invalid_test_cases"
    for case in cases:
        assertion = case.get("assertion") if isinstance(case, Mapping) else None
        if not isinstance(assertion, Mapping):
            return False, "caller_assertion_is_not_executable"
        kind = assertion.get("kind")
        if kind == "required-files":
            paths = assertion.get("paths")
            if not isinstance(paths, list) or not paths or any(str(path) not in files for path in paths):
                return False, "required_files_missing"
        elif kind in {"json-object", "yaml-object"}:
            relative = Path(str(assertion.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() not in files:
                return False, "asserted_file_missing"
            try:
                text = (payload / relative).read_text(encoding="utf-8")
                parsed = json.loads(text) if kind == "json-object" else yaml.safe_load(text)
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                return False, "asserted_file_did_not_parse"
            if not isinstance(parsed, Mapping):
                return False, "asserted_file_is_not_an_object"
        elif kind == "text-contains":
            relative = Path(str(assertion.get("path") or ""))
            needle = str(assertion.get("text") or "")
            if (
                not needle
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.as_posix() not in files
                or needle not in (payload / relative).read_text(encoding="utf-8")
            ):
                return False, "required_text_missing"
        else:
            return False, "unsupported_assertion_kind"
    return True, "trusted_declarative_runner"


def _python_effects(text: str) -> set[str]:
    def constant_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = constant_string(node.left)
            right = constant_string(node.right)
            return left + right if left is not None and right is not None else None
        return None

    tree = ast.parse(text)
    effects: set[str] = set()
    network_modules = {"requests", "urllib", "http", "socket", "httpx", "aiohttp"}
    process_modules = {"subprocess", "multiprocessing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
            if roots & network_modules:
                effects.add("network")
            if roots & process_modules:
                effects.add("process")
        elif isinstance(node, ast.ImportFrom):
            root = str(node.module or "").split(".", 1)[0]
            if root in network_modules:
                effects.add("network")
            if root in process_modules:
                effects.add("process")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "__import__" and node.args and constant_string(node.args[0]) is not None:
                root = str(constant_string(node.args[0])).split(".", 1)[0]
                if root in network_modules:
                    effects.add("network")
                if root in process_modules:
                    effects.add("process")
            leaf = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
            if leaf in {"urlopen", "request", "get", "post", "put", "delete", "connect", "create_connection"}:
                effects.add("network")
            if leaf in {"Popen", "run", "call", "check_call", "check_output", "system"}:
                effects.add("process")
            if leaf in {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace"}:
                effects.add("filesystem-write")
            if leaf == "open" or (isinstance(node.func, ast.Name) and node.func.id == "open"):
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
                mode = next((item.value.value for item in node.keywords if item.arg == "mode" and isinstance(item.value, ast.Constant)), mode)
                if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
                    effects.add("filesystem-write")
    return effects


def _copy_verified(
    source: Path, target: Path, expected: list[dict[str, object]]
) -> None:
    if target.exists():
        raise FileExistsError(f"verified copy target already exists: {target}")
    target.mkdir(parents=True)
    total_bytes = 0
    for row in expected:
        relative = Path(str(row["path"]))
        source_file = source / relative
        if _is_link_or_reparse(source_file) or not source_file.is_file():
            raise ValueError("skill source changed or introduced a link during copy")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = _read_bounded_regular_file(
            source_file, min(MAX_SKILL_FILE_BYTES, MAX_SKILL_BYTES - total_bytes)
        )
        total_bytes += len(data)
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("skill source changed during verified copy")
        _atomic_bytes(destination, data)
    if _tree(target) != expected or _tree(source) != expected:
        raise ValueError("skill copy did not preserve the admitted tree identity")


def _fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    """Durably publish exact bytes through a same-directory replacement."""
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_BINARY", 0))
    descriptor = os.open(prepared, flags, 0o600)
    try:
        position = 0
        while position < len(payload):
            written = os.write(descriptor, payload[position:])
            if written <= 0:
                raise OSError("skill lifecycle durable write made no progress")
            position += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(prepared, path)
        _fsync_directory(path.parent)
    finally:
        if prepared.exists():
            prepared.unlink()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class SkillStudio:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve(strict=True)
        if self.root == Path(self.root.anchor):
            raise ValueError("skill studio root must be bounded")
        self.drafts = self.root / ".engineering-bootstrap" / "studios" / "skills"
        self.canonical = self.root / ".px" / "skills"
        self.preserved = self.root / ".px" / "preserved-skills"
        self.authority = StudioAuthorityStore(self.root)
        self.manager = ResourceManager(self.drafts / "resources.json")
        self.lifecycle_lock = self.drafts / ".skill-lifecycle.lock"
        with FileLock(self.lifecycle_lock, timeout_seconds=30):
            self._recover_lifecycle_transactions_locked()

    def admit_source(
        self,
        source: Path,
        *,
        approved_by: str,
        expected_tree_sha256: str | None = None,
        expected_file_count: int | None = None,
    ) -> str | dict[str, object]:
        if _is_link_or_reparse(source):
            raise ValueError("skill package links or reparse points are not admitted")
        source = source.resolve(strict=True)
        rows, source_tree_sha256 = _tree_attestation(source)
        attested = expected_tree_sha256 is not None or expected_file_count is not None
        if attested:
            if (
                not isinstance(expected_tree_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_tree_sha256) is None
                or isinstance(expected_file_count, bool)
                or not isinstance(expected_file_count, int)
                or expected_file_count < 1
                or expected_file_count > MAX_SKILL_FILES
            ):
                raise ValueError("skill source materialization attestation is invalid")
            if (
                source_tree_sha256 != expected_tree_sha256
                or len(rows) != expected_file_count
            ):
                raise PermissionError(
                    "selected skill source does not match the host materialization attestation"
                )
        token = self.authority.admit_source(
            source, approved_by=approved_by, tree_sha256=source_tree_sha256
        )
        if not attested:
            return token
        return {
            "schema_version": "px.skill-source-admission/1.0",
            "source_token": token,
            "source_directory": str(source),
            "source_tree_sha256": source_tree_sha256,
            "file_count": len(rows),
        }

    def preserve_originals(self, sources: Mapping[str, Path]) -> dict[str, object]:
        records = []
        for label, supplied in sorted(sources.items()):
            if _is_link_or_reparse(supplied):
                raise ValueError("original skill source links or reparse points are not admitted")
            source = supplied.resolve(strict=True)
            if not source.is_dir() or source == Path(source.anchor):
                raise ValueError("original skill source must be a bounded directory")
            rows, tree_sha = _tree_attestation(source)
            destination = self.preserved / "initial" / _component(label) / tree_sha
            verify_safe_ancestors(self.root, destination)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                _copy_verified(source, destination, rows)
            if _tree(destination) != rows:
                raise OSError(
                    "preserved original skill backup failed identity verification"
                )
            records.append(
                {
                    "label": label,
                    "source_tree_sha256": tree_sha,
                    "backup_relative": destination.relative_to(self.root).as_posix(),
                    "file_count": len(rows),
                    "preserved_utc": _now(),
                }
            )
        manifest_path = self.preserved / "initial" / "manifest.json"
        prior_records: list[dict[str, object]] = []
        if manifest_path.exists():
            prior_records = list(
                json.loads(manifest_path.read_text(encoding="utf-8")).get("records", [])
            )
        keyed = {
            (str(row["label"]), str(row["source_tree_sha256"])): row
            for row in [*prior_records, *records]
        }
        manifest = {
            "schema_version": "px.original-skill-backup/1.1",
            "updated_utc": _now(),
            "immutable": True,
            "records": [keyed[key] for key in sorted(keyed)],
        }
        write_json_atomic(manifest_path, manifest)
        return manifest

    def stage_draft(
        self,
        package: SkillPackage,
        source: Path,
        *,
        source_token: str,
        version_allocation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        lock_path = studio_revision_lock(self.root, "skill", package.skill_id)
        destination = (
            self.drafts / _component(package.skill_id) / "revisions" / package.version
        )
        verify_safe_ancestors(self.root, lock_path)
        verify_safe_ancestors(
            self.root,
            destination,
            include_target=os.path.lexists(destination),
        )
        with FileLock(
            lock_path,
            timeout_seconds=10,
        ):
            verify_safe_ancestors(self.root, lock_path)
            verify_safe_ancestors(
                self.root,
                destination,
                include_target=os.path.lexists(destination),
            )
            if version_allocation is not None and not destination.exists():
                revalidate_studio_version_allocation(
                    self.root,
                    "skill",
                    package.skill_id,
                    package.version,
                    version_allocation,
                )
            return self._stage_draft_locked(
                package,
                source,
                source_token=source_token,
            )

    def _stage_draft_locked(
        self,
        package: SkillPackage,
        source: Path,
        *,
        source_token: str,
    ) -> dict[str, object]:
        if _is_link_or_reparse(source):
            raise ValueError("skill package links or reparse points are not admitted")
        source = source.resolve(strict=True)
        admitted = self.authority.resolve_source(source_token, source)
        rows, tree_sha = _tree_attestation(source)
        if admitted.get("tree_sha256") != tree_sha:
            raise PermissionError(
                "selected skill source changed after source admission"
            )
        component = _component(package.skill_id)
        destination = self.drafts / component / "revisions" / package.version
        manifest_sha = digest(asdict(package))
        preserved_original = _preserved_original_provenance(self.root, package)
        record = json.loads(
            json.dumps(
                {
                    "schema_version": "px.skill-draft/1.1",
                    "manifest": asdict(package),
                    "manifest_sha256": manifest_sha,
                    "source_tree_sha256": tree_sha,
                    "source_authority_token": source_token,
                    "files": rows,
                    "file_count": len(rows),
                    "payload_root": "payload",
                    "draft_state": "saved",
                    "admission_state": "unadmitted",
                    "promotion_state": "not_promoted",
                    "created": True,
                    **(
                        {"preserved_original": preserved_original}
                        if preserved_original is not None
                        else {}
                    ),
                },
                sort_keys=True,
            )
        )
        if destination.exists():
            allowed_controls = {
                name for name in CONTROL_FILES if (destination / name).exists()
            }
            expected_files = {
                "package-record.json",
                *(f"payload/{row['path']}" for row in rows),
                *allowed_controls,
            }
            expected_directories = {"payload"}
            for row in rows:
                parts = str(row["path"]).split("/")
                expected_directories.update(
                    f"payload/{'/'.join(parts[:index])}"
                    for index in range(1, len(parts))
                )
            try:
                assert_exact_tree(
                    destination,
                    expected_files,
                    expected_directories,
                    MAX_SKILL_ENTRIES + len(CONTROL_FILES) + 1,
                    lambda: StudioVersionConflict(
                        "immutable-skill-revision-differs"
                    ),
                )
                existing = json.loads(
                    _read_bounded_regular_file(
                        destination / "package-record.json", MAX_SKILL_FILE_BYTES
                    ).decode("utf-8")
                )
                current_rows, current_tree = _tree_attestation(
                    destination / "payload"
                )
            except StudioVersionConflict:
                raise
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise StudioVersionConflict(
                    "immutable-skill-revision-differs"
                ) from error
            if existing != record or current_rows != rows or current_tree != tree_sha:
                raise StudioVersionConflict("immutable-skill-revision-differs")
            return {**existing, "created": False, "idempotent_replay": True}
        prepared_root = self.drafts / "prepared"
        verify_safe_ancestors(self.root, prepared_root)
        prepared_root.mkdir(parents=True, exist_ok=True)
        run_id = f"skill-stage-{uuid4().hex}"
        resource = self.manager.create_workspace(
            prepared_root,
            project_id=package.skill_id,
            run_id=run_id,
            lane_id=package.version,
            creator=package.owner,
            prefix=f"{component}-{package.version}-",
        )
        prepared = Path(str(resource.path))
        try:
            _copy_verified(source, prepared / "payload", rows)
            write_json_atomic(prepared / "package-record.json", record)
            verify_safe_ancestors(self.root, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            verify_safe_ancestors(self.root, destination)
            try:
                publish_directory_no_replace(prepared, destination)
            except OSError as error:
                if os.path.lexists(destination):
                    raise StudioVersionConflict("publication-collision") from error
                raise
        except Exception as publish_error:
            try:
                self.manager.mark_run_ended(run_id, RunState.FAILED)
            except Exception as cleanup_error:
                publish_error.add_note(
                    f"run failure closure degraded: {str(cleanup_error)[:240]}"
                )
            try:
                self.manager.reclaim(
                    resource.resource_id, reason="skill_stage_failed", apply=True
                )
            except Exception as cleanup_error:
                publish_error.add_note(
                    f"failed resource reclaim degraded: {str(cleanup_error)[:240]}"
                )
            raise
        post_publish_errors: list[object] = []
        try:
            self.manager.mark_run_ended(run_id, RunState.COMPLETED)
        except Exception as error:  # The immutable revision is already published.
            post_publish_errors.append(f"run closure degraded: {error}")
        try:
            cleanup = self.manager.reclaim(
                resource.resource_id, reason="skill_stage_published", apply=True
            )
        except Exception as error:  # Preserve committed-create truth in the response.
            post_publish_errors.append(f"resource reclaim degraded: {error}")
        else:
            post_publish_errors.extend(cleanup.errors)
        cleanup_warnings = _bounded_cleanup_warnings(post_publish_errors)
        return {
            **record,
            **({"cleanup_warnings": cleanup_warnings} if cleanup_warnings else {}),
        }

    def validate(self, package: SkillPackage) -> dict[str, object]:
        root = (
            self.drafts / _component(package.skill_id) / "revisions" / package.version
        )
        payload = root / "payload"
        record_path = root / "package-record.json"
        if not record_path.is_file():
            raise FileNotFoundError("skill draft revision is missing")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        current, current_tree_sha256 = _tree_attestation(payload)
        preserved_original_error = None
        try:
            current_preserved_original = _preserved_original_provenance(
                self.root, package
            )
        except (OSError, PermissionError, ValueError) as error:
            current_preserved_original = None
            preserved_original_error = type(error).__name__
        recorded_preserved_original = record.get("preserved_original")
        files = {str(row["path"]) for row in current}
        declared = set(package.resources + package.contracts + package.tests)
        parse_errors: list[str] = []
        try:
            capability = json.loads(
                (payload / "capability.json").read_text(encoding="utf-8")
            )
            if not isinstance(capability, dict):
                raise ValueError("capability manifest is not an object")
        except Exception as error:
            parse_errors.append(f"capability.json:{type(error).__name__}")
        try:
            skill_yaml = yaml.safe_load(
                (payload / "skill.yaml").read_text(encoding="utf-8")
            )
            if not isinstance(skill_yaml, dict):
                raise ValueError("skill YAML is not an object")
        except Exception as error:
            parse_errors.append(f"skill.yaml:{type(error).__name__}")
        behavioral_tests = []
        for test_path in package.tests:
            try:
                if not test_path.endswith(".json"):
                    raise ValueError(
                        "only declarative governed skill tests are admitted"
                    )
                value = json.loads((payload / test_path).read_text(encoding="utf-8"))
                passed, runner = _run_declarative_test(value, files, payload)
                behavioral_tests.append(
                    {
                        "path": test_path,
                        "executed": passed,
                        "passed": passed,
                        "runner": runner,
                    }
                )
            except Exception as error:
                behavioral_tests.append(
                    {
                        "path": test_path,
                        "executed": False,
                        "passed": False,
                        "reason": type(error).__name__,
                    }
                )
        secrets = []
        script_effects = []
        scan_errors = []
        for row in current:
            path = payload / str(row["path"])
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                scan_errors.append(f"unscannable_text:{row['path']}")
                continue
            if SECRET_PATTERN.search(text):
                secrets.append(str(row["path"]))
            effects: set[str] = set()
            suffix = path.suffix.casefold()
            if suffix == ".py":
                try:
                    effects.update(_python_effects(text))
                except SyntaxError:
                    scan_errors.append(f"unparseable_python:{row['path']}")
            elif suffix in {".ps1", ".sh", ".js", ".mjs"}:
                compact = re.sub(r"[\s'\"`+]+", "", text.casefold())
                markers = {
                    "network": ("requests.", "fetch(", "curl", "invoke-webrequest", "urllib", "http.request", "socket."),
                    "process": ("subprocess", "child_process", "start-process", "spawn(", "exec("),
                    "filesystem-write": ("write_text", "write_bytes", "set-content", "writefile", "appendfile"),
                }
                for effect, tokens in markers.items():
                    if any(re.sub(r"[\s'\"`+]+", "", token.casefold()) in compact for token in tokens):
                        effects.add(effect)
            for effect in sorted(effects):
                script_effects.append(
                    {
                        "path": str(row["path"]),
                        "effect": effect,
                        "declared": effect in package.effects
                        or effect in package.permissions,
                    }
                )
        checks = {
            "manifest_current": record["manifest_sha256"] == digest(asdict(package)),
            "tree_current": record["source_tree_sha256"] == current_tree_sha256,
            "skill_body_present": "SKILL.md" in files,
            "native_manifest_present": {"capability.json", "skill.yaml"}.issubset(
                files
            ),
            "declared_resources_present": declared.issubset(files),
            "schemas_parse": not parse_errors,
            "tests_executed": bool(behavioral_tests)
            and all(item["passed"] for item in behavioral_tests),
            "secret_scan_clear": not secrets,
            "script_effects_declared": all(item["declared"] for item in script_effects),
            "all_content_scannable": not scan_errors,
            "preserved_original_current": preserved_original_error is None
            and recorded_preserved_original == current_preserved_original,
        }
        receipt = self.authority.sign_receipt(
            {
                "schema_version": "px.skill-validation-receipt/1.1",
                "skill_id": package.skill_id,
                "version": package.version,
                "manifest_sha256": record["manifest_sha256"],
                "source_tree_sha256": record["source_tree_sha256"],
                "checks": checks,
                "parse_errors": parse_errors,
                "behavioral_tests": behavioral_tests,
                "secret_findings": secrets,
                "script_effect_findings": script_effects,
                "scan_errors": scan_errors,
                "preserved_original": recorded_preserved_original,
                "preserved_original_errors": (
                    [preserved_original_error] if preserved_original_error else []
                ),
                "passed": all(checks.values()),
                "independently_derived": True,
                "validated_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        write_json_atomic(root / "validation-receipt.json", receipt)
        return receipt

    def admit(
        self, package: SkillPackage, *, approved: bool, approver: str
    ) -> dict[str, object]:
        root = (
            self.drafts / _component(package.skill_id) / "revisions" / package.version
        )
        raw = (
            json.loads((root / "validation-receipt.json").read_text(encoding="utf-8"))
            if (root / "validation-receipt.json").is_file()
            else {}
        )
        validation = self.authority.verify_receipt(raw) if raw else {}
        reasons = []
        if not validation.get("passed"):
            reasons.append("current_validation_missing")
        if not approved or not approver.strip():
            reasons.append("explicit_approval_missing")
        receipt = self.authority.sign_receipt(
            {
                "schema_version": "px.skill-admission-receipt/1.1",
                "skill_id": package.skill_id,
                "version": package.version,
                "decision": "admitted" if not reasons else "rejected",
                "reasons": reasons,
                "manifest_sha256": validation.get("manifest_sha256"),
                "source_tree_sha256": validation.get("source_tree_sha256"),
                "preserved_original": validation.get("preserved_original"),
                "approved_by": approver if approved else None,
                "admitted_utc": _now(),
                "nonce": uuid4().hex,
            }
        )
        write_json_atomic(root / "admission-receipt.json", receipt)
        return receipt

    def _projection_updates(
        self,
        package: SkillPackage,
        staged_target: Path,
        *,
        preserved_original: Mapping[str, object] | None,
    ) -> dict[Path, bytes]:
        """Calculate every projection from an unpublished canonical after-tree."""
        updates: dict[Path, bytes] = {}
        name = _canonical_name(package.skill_id)
        package_record_path = self.root / "registry" / "skill_packages" / f"{name}.json"
        if package_record_path.parent.exists():
            package_record = {
                "schema_version": "px.skill-package/1.1",
                "id": name,
                "version": package.version,
                "status": "admitted",
                "body": f".px/skills/{name}/SKILL.md",
                "manifest": asdict(package),
                "tree_sha256": _tree_attestation(staged_target)[1],
                "preserved_original": preserved_original,
            }
            updates[package_record_path] = (
                json.dumps(package_record, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        catalog_path = self.root / "registry" / "skill_catalog.toml"
        if catalog_path.is_file():
            text = catalog_path.read_text(encoding="utf-8")
            tags = ", ".join(json.dumps(item) for item in package.triggers[:8])
            blocks = list(
                re.finditer(
                    r"(?ms)^\[\[skills\]\]\r?\n.*?(?=^\[\[skills\]\]|\Z)",
                    text,
                )
            )
            matching = [
                match
                for match in blocks
                if re.search(rf'(?m)^id = "{re.escape(name)}"$', match.group(0))
            ]
            if len(matching) > 1:
                raise ValueError("skill catalog contains duplicate canonical skill IDs")
            if not matching:
                text += f'\n[[skills]]\nid = "{name}"\nversion = "{package.version}"\nstatus = "active"\nbody = ".px/skills/{name}/SKILL.md"\ncontract = "registry/skill_packages/{name}.json"\nadmission_record = "{name}"\ntags = [{tags}]\n'
                updates[catalog_path] = text.encode("utf-8")
            else:
                match = matching[0]
                block = match.group(0)
                revised = re.sub(
                    r'(?m)^version = "[^"]*"$',
                    f'version = "{package.version}"',
                    block,
                    count=1,
                )
                revised = re.sub(
                    r"(?m)^tags = \[[^\r\n]*\]$",
                    f"tags = [{tags}]",
                    revised,
                    count=1,
                )
                if revised == block and not (
                    re.search(rf'(?m)^version = "{re.escape(package.version)}"$', block)
                    and re.search(rf"(?m)^tags = \[{re.escape(tags)}\]$", block)
                ):
                    raise ValueError("skill catalog entry lacks mutable projection fields")
                if revised != block:
                    text = text[: match.start()] + revised + text[match.end() :]
                    updates[catalog_path] = text.encode("utf-8")
        index_path = self.root / ".px" / "skill-index.json"
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            validate_skill_index(index, require_derived=True)
            records = [row for row in index.get("records", []) if row.get("id") != name]
            body_sha = hashlib.sha256((staged_target / "SKILL.md").read_bytes()).hexdigest()
            records.append(
                {
                    "id": name,
                    "version": package.version,
                    "status": "active",
                    "description": "",
                    "tags": list(package.triggers),
                    "domain": "px-standard",
                    "origin": "skill-studio",
                    "native": True,
                    "adapted": True,
                    "default_eligible": True,
                    "body_available": True,
                    "package_root": f".px/skills/{name}",
                    "body": f".px/skills/{name}/SKILL.md",
                    "body_sha256": body_sha,
                    "backup": (
                        preserved_original.get("package_relative")
                        if preserved_original is not None
                        else None
                    ),
                    "admission": "admitted",
                }
            )
            index = build_skill_index(records, template=index)
            updates[index_path] = (
                json.dumps(index, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            catalog_after = updates.get(catalog_path)
            catalog_text = (
                catalog_after.decode("utf-8")
                if catalog_after is not None
                else catalog_path.read_text(encoding="utf-8")
            )
            catalog_ids = {
                str(row["id"])
                for row in tomllib.loads(catalog_text).get("skills", ())
            }
            record_ids = {
                str(row["id"])
                for row in index["records"]
                if row.get("domain") == "px-standard" and row.get("native")
            }
            if catalog_ids != record_ids:
                raise ValueError(
                    "skill catalog/index denominator drift: "
                    f"catalog-only={sorted(catalog_ids - record_ids)} "
                    f"index-only={sorted(record_ids - catalog_ids)}"
                )
            skills_root = self.root / ".px" / "skills"
            package_ids = {
                path.name
                for path in skills_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            } if skills_root.is_dir() else set()
            package_ids.add(name)
            if package_ids != record_ids:
                raise ValueError(
                    "skill package/index denominator drift: "
                    f"package-only={sorted(package_ids - record_ids)} "
                    f"index-only={sorted(record_ids - package_ids)}"
                )
        pyproject = self.root / "pyproject.toml"
        if pyproject.is_file():
            from scripts.migration.sync_skill_packaging import render

            rendered = render(
                pyproject.read_text(encoding="utf-8"),
                self.root,
                skill_overlays={name: staged_target},
            )
            tomllib.loads(rendered)
            updates[pyproject] = rendered.encode("utf-8")
        return updates

    def _validate_projection_denominators(self) -> None:
        """Fail before canonical mutation when existing skill views disagree."""
        index_path = self.root / ".px" / "skill-index.json"
        catalog_path = self.root / "registry" / "skill_catalog.toml"
        skills_root = self.root / ".px" / "skills"
        if not (index_path.is_file() and catalog_path.is_file()):
            return
        index = json.loads(index_path.read_text(encoding="utf-8"))
        validate_skill_index(index, require_derived=True)
        record_ids = {
            str(row["id"])
            for row in index["records"]
            if row.get("domain") == "px-standard" and row.get("native")
        }
        catalog_ids = {
            str(row["id"])
            for row in tomllib.loads(catalog_path.read_text(encoding="utf-8")).get(
                "skills", ()
            )
        }
        package_ids = (
            {path.name for path in skills_root.iterdir() if path.is_dir()}
            if skills_root.is_dir()
            else set()
        )
        if not (record_ids == catalog_ids == package_ids):
            raise ValueError(
                "skill projections disagree before promotion: "
                f"index={len(record_ids)} catalog={len(catalog_ids)} packages={len(package_ids)}"
            )

    def _commit_projection_transaction(
        self, package: SkillPackage, updates: Mapping[Path, bytes]
    ) -> dict[str, object]:
        """Publish related projections through a recoverable exact-byte WAL."""
        if not updates:
            return {"updated_paths": [], "transaction_relative": None}
        journal_root = self.drafts / "projection-transactions"
        journal_root.mkdir(parents=True, exist_ok=True)
        transaction_id = f"promotion-{_component(package.skill_id)}-{uuid4().hex}"
        transaction = journal_root / transaction_id
        transaction.mkdir()
        artifacts = []
        for index, (path, after) in enumerate(
            sorted(updates.items(), key=lambda item: item[0].as_posix())
        ):
            verify_safe_ancestors(self.root, path)
            relative = path.relative_to(self.root).as_posix()
            before = path.read_bytes() if path.is_file() else None
            before_name = f"before-{index}.bin" if before is not None else None
            after_name = f"after-{index}.bin"
            if before is not None:
                (transaction / before_name).write_bytes(before)
            (transaction / after_name).write_bytes(after)
            artifacts.append(
                {
                    "path": relative,
                    "before_exists": before is not None,
                    "before_sha256": hashlib.sha256(before).hexdigest()
                    if before is not None
                    else None,
                    "before_image": before_name,
                    "after_sha256": hashlib.sha256(after).hexdigest(),
                    "after_image": after_name,
                }
            )
        manifest = {
            "schema_version": "px.skill-projection-transaction/1.0",
            "transaction_id": transaction_id,
            "skill_id": package.skill_id,
            "version": package.version,
            "state": "prepared",
            "artifacts": artifacts,
            "created_utc": _now(),
        }
        write_json_atomic(
            transaction / "manifest.json", self.authority.sign_receipt(manifest)
        )
        manifest["state"] = "applying"
        write_json_atomic(
            transaction / "manifest.json", self.authority.sign_receipt(manifest)
        )
        self._roll_projection_transaction_forward(transaction, manifest)
        manifest["state"] = "committed"
        manifest["committed_utc"] = _now()
        write_json_atomic(
            transaction / "manifest.json", self.authority.sign_receipt(manifest)
        )
        return {
            "updated_paths": [str(item["path"]) for item in artifacts],
            "transaction_relative": transaction.relative_to(self.root).as_posix(),
        }

    def _roll_projection_transaction_forward(
        self, transaction: Path, manifest: Mapping[str, object]
    ) -> None:
        for item in manifest.get("artifacts", []):
            if not isinstance(item, Mapping):
                raise ValueError("skill projection transaction artifact is invalid")
            relative = Path(str(item.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("skill projection transaction target escapes custody")
            target = self.root / relative
            verify_safe_ancestors(self.root, target)
            after = transaction / str(item.get("after_image") or "")
            payload = after.read_bytes()
            if hashlib.sha256(payload).hexdigest() != item.get("after_sha256"):
                raise ValueError("skill projection transaction after-image changed")
            current = target.read_bytes() if target.is_file() else None
            current_sha = (
                hashlib.sha256(current).hexdigest() if current is not None else None
            )
            if current_sha == item.get("after_sha256"):
                continue
            if current_sha != item.get("before_sha256"):
                raise PermissionError(
                    f"skill projection changed outside transaction: {relative.as_posix()}"
                )
            _atomic_bytes(target, payload)

    def _restore_projection_transaction(
        self, transaction_relative: str, expected_paths: list[str]
    ) -> list[str]:
        """Restore exact pre-promotion projection bytes, allowing safe retry."""
        relative = Path(transaction_relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("skill projection rollback transaction escapes custody")
        transaction = (self.root / relative).resolve(strict=True)
        journal_root = (self.drafts / "projection-transactions").resolve(strict=True)
        if transaction.parent != journal_root or transaction.is_symlink():
            raise PermissionError("skill projection rollback transaction escapes Studio custody")
        manifest_path = transaction / "manifest.json"
        manifest = self.authority.verify_receipt(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        if manifest.get("state") != "committed":
            raise PermissionError("skill projection transaction is not committed")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("skill projection rollback artifacts are invalid")
        paths = [str(item.get("path") or "") for item in artifacts if isinstance(item, Mapping)]
        if paths != expected_paths or len(paths) != len(artifacts):
            raise PermissionError("skill projection rollback denominator changed")
        prepared: list[tuple[Path, bytes | None, Mapping[str, object]]] = []
        for item in artifacts:
            assert isinstance(item, Mapping)
            item_relative = Path(str(item.get("path") or ""))
            if item_relative.is_absolute() or ".." in item_relative.parts:
                raise ValueError("skill projection rollback target escapes custody")
            target = self.root / item_relative
            verify_safe_ancestors(self.root, target, include_target=os.path.lexists(target))
            before: bytes | None = None
            if item.get("before_exists") is True:
                before_path = transaction / str(item.get("before_image") or "")
                before = before_path.read_bytes()
                if hashlib.sha256(before).hexdigest() != item.get("before_sha256"):
                    raise ValueError("skill projection transaction before-image changed")
            current = target.read_bytes() if target.is_file() else None
            current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_sha not in {item.get("after_sha256"), item.get("before_sha256")}:
                raise PermissionError(
                    f"skill projection changed after promotion: {item_relative.as_posix()}"
                )
            prepared.append((target, before, item))
        restored: list[str] = []
        for target, before, item in prepared:
            current = target.read_bytes() if target.is_file() else None
            current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
            if before is None:
                if current_sha == item.get("after_sha256"):
                    target.unlink()
            elif current_sha != item.get("before_sha256"):
                _atomic_bytes(target, before)
            restored.append(target.relative_to(self.root).as_posix())
        return restored

    def recover_projection_transactions(self) -> dict[str, object]:
        """Roll admitted applying transactions forward; never overwrite drift."""
        journal_root = self.drafts / "projection-transactions"
        completed = []
        if not journal_root.is_dir():
            return {"valid": True, "completed": completed}
        for transaction in sorted(journal_root.iterdir(), key=lambda path: path.name):
            manifest_path = transaction / "manifest.json"
            if not transaction.is_dir() or not manifest_path.is_file():
                raise ValueError("invalid skill projection transaction custody")
            manifest = self.authority.verify_receipt(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            if manifest.get("state") == "applying":
                self._roll_projection_transaction_forward(transaction, manifest)
                manifest["state"] = "committed"
                manifest["committed_utc"] = _now()
                write_json_atomic(manifest_path, self.authority.sign_receipt(manifest))
                completed.append(transaction.name)
            elif manifest.get("state") == "prepared":
                manifest["state"] = "rolled-back-before-apply"
                manifest["rolled_back_utc"] = _now()
                write_json_atomic(manifest_path, self.authority.sign_receipt(manifest))
            elif manifest.get("state") not in {
                "committed",
                "rolled-back-before-apply",
            }:
                raise ValueError("unknown skill projection transaction state")
        return {"valid": True, "completed": completed}

    def _write_lifecycle_manifest(
        self, transaction: Path, manifest: Mapping[str, object]
    ) -> None:
        _atomic_bytes(
            transaction / "manifest.json",
            _json_bytes(self.authority.sign_receipt(dict(manifest))),
        )

    def _read_lifecycle_manifest(self, transaction: Path) -> dict[str, object]:
        journal_root = self.drafts / "lifecycle-transactions"
        resolved_root = journal_root.resolve(strict=True)
        resolved = transaction.resolve(strict=True)
        if (
            resolved.parent != resolved_root
            or transaction.is_symlink()
            or not transaction.is_dir()
        ):
            raise PermissionError("skill lifecycle transaction escapes Studio custody")
        manifest_path = transaction / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("skill lifecycle transaction manifest is invalid")
        raw = json.loads(
            _read_bounded_regular_file(
                manifest_path, MAX_LIFECYCLE_ARTIFACT_BYTES
            ).decode("utf-8")
        )
        manifest = self.authority.verify_receipt(raw)
        if manifest.get("schema_version") != LIFECYCLE_TRANSACTION_SCHEMA:
            raise ValueError("skill lifecycle transaction schema is invalid")
        if manifest.get("transaction_id") != transaction.name:
            raise PermissionError("skill lifecycle transaction identity changed")
        return dict(manifest)

    def _prepare_lifecycle_transaction(
        self,
        package: SkillPackage,
        *,
        operation: str,
        canonical_source: Path,
        target: Path,
        displaced: Path,
        backup: Path | None,
        updates: Mapping[Path, bytes | None],
        receipt_path: Path,
        receipt_payload: Mapping[str, object],
    ) -> tuple[Path, dict[str, object], dict[str, object]]:
        if operation not in {"promotion", "rollback"}:
            raise ValueError("skill lifecycle operation is invalid")
        journal_root = self.drafts / "lifecycle-transactions"
        journal_root.mkdir(parents=True, exist_ok=True)
        transaction_id = f"{operation}-{_component(package.skill_id)}-{uuid4().hex}"
        transaction = journal_root / transaction_id
        preparing = journal_root / f".{transaction_id}.preparing"
        preparing.mkdir()
        transaction_relative = transaction.relative_to(self.root).as_posix()
        canonical_after = preparing / "canonical-after"
        after_rows, after_tree_sha256 = _tree_attestation(canonical_source)
        _copy_verified(canonical_source, canonical_after, after_rows)
        before_tree_sha256 = (
            _tree_attestation(target)[1] if target.is_dir() else None
        )
        bound_receipt = {
            **dict(receipt_payload),
            "lifecycle_transaction_relative": transaction_relative,
        }
        if operation == "promotion":
            bound_receipt["projection_transaction_relative"] = transaction_relative
        signed_receipt = self.authority.sign_receipt(bound_receipt)
        materialized_updates: dict[Path, bytes | None] = dict(updates)
        materialized_updates[receipt_path] = _json_bytes(signed_receipt)
        if len(materialized_updates) > MAX_LIFECYCLE_ARTIFACTS:
            raise ValueError("skill lifecycle transaction artifact bound exceeded")
        artifacts: list[dict[str, object]] = []
        total_bytes = 0
        for index, (path, after) in enumerate(
            sorted(materialized_updates.items(), key=lambda item: item[0].as_posix())
        ):
            verify_safe_ancestors(
                self.root, path, include_target=os.path.lexists(path)
            )
            try:
                relative = path.relative_to(self.root).as_posix()
            except ValueError as error:
                raise ValueError("skill lifecycle artifact escapes project root") from error
            if path.exists() and (path.is_symlink() or not path.is_file()):
                raise ValueError("skill lifecycle artifact target is not a physical file")
            before = path.read_bytes() if path.is_file() else None
            total_bytes += len(before or b"") + len(after or b"")
            if total_bytes > MAX_LIFECYCLE_ARTIFACT_BYTES:
                raise ValueError("skill lifecycle transaction byte bound exceeded")
            before_name = f"before-{index}.bin" if before is not None else None
            after_name = f"after-{index}.bin" if after is not None else None
            if before is not None:
                _atomic_bytes(preparing / str(before_name), before)
            if after is not None:
                _atomic_bytes(preparing / str(after_name), after)
            artifacts.append(
                {
                    "role": "receipt" if path == receipt_path else "projection",
                    "path": relative,
                    "before_exists": before is not None,
                    "before_sha256": hashlib.sha256(before).hexdigest()
                    if before is not None
                    else None,
                    "before_image": before_name,
                    "after_exists": after is not None,
                    "after_sha256": hashlib.sha256(after).hexdigest()
                    if after is not None
                    else None,
                    "after_image": after_name,
                }
            )
        manifest: dict[str, object] = {
            "schema_version": LIFECYCLE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "operation": operation,
            "skill_id": package.skill_id,
            "version": package.version,
            "state": "prepared",
            "canonical": {
                "target_relative": target.relative_to(self.root).as_posix(),
                "before_tree_sha256": before_tree_sha256,
                "after_tree_sha256": after_tree_sha256,
                "after_image": "canonical-after",
                "displaced_relative": displaced.relative_to(self.root).as_posix(),
                "backup_relative": backup.relative_to(self.root).as_posix()
                if backup is not None
                else None,
            },
            "artifacts": artifacts,
            "receipt_relative": receipt_path.relative_to(self.root).as_posix(),
            "created_utc": _now(),
        }
        self._write_lifecycle_manifest(preparing, manifest)
        os.replace(preparing, transaction)
        _fsync_directory(journal_root)
        return transaction, manifest, signed_receipt

    def _bounded_lifecycle_artifacts(
        self, transaction: Path, manifest: Mapping[str, object]
    ) -> list[Mapping[str, object]]:
        artifacts = manifest.get("artifacts")
        if (
            not isinstance(artifacts, list)
            or len(artifacts) > MAX_LIFECYCLE_ARTIFACTS
            or any(not isinstance(item, Mapping) for item in artifacts)
        ):
            raise ValueError("skill lifecycle artifacts are invalid")
        paths: set[str] = set()
        total_bytes = 0
        for item in artifacts:
            assert isinstance(item, Mapping)
            relative_text = str(item.get("path") or "")
            relative = Path(relative_text)
            if (
                not relative_text
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.as_posix() != relative_text
                or relative_text in paths
            ):
                raise ValueError("skill lifecycle artifact path is invalid")
            paths.add(relative_text)
            for prefix in ("before", "after"):
                exists = item.get(f"{prefix}_exists") is True
                image_name = item.get(f"{prefix}_image")
                expected_sha = item.get(f"{prefix}_sha256")
                if not exists:
                    if image_name is not None or expected_sha is not None:
                        raise ValueError("skill lifecycle absent image has custody data")
                    continue
                if (
                    not isinstance(image_name, str)
                    or not re.fullmatch(rf"{prefix}-[0-9]+\.bin", image_name)
                    or not isinstance(expected_sha, str)
                    or _SHA256.fullmatch(expected_sha) is None
                ):
                    raise ValueError("skill lifecycle image custody is invalid")
                image = transaction / image_name
                if not image.is_file() or image.is_symlink():
                    raise ValueError("skill lifecycle image is not a physical file")
                payload = _read_bounded_regular_file(
                    image, MAX_LIFECYCLE_ARTIFACT_BYTES - total_bytes
                )
                total_bytes += len(payload)
                if hashlib.sha256(payload).hexdigest() != expected_sha:
                    raise PermissionError("skill lifecycle image changed")
        return list(artifacts)

    def _roll_lifecycle_transaction_forward(
        self, transaction: Path, manifest: Mapping[str, object]
    ) -> None:
        canonical = manifest.get("canonical")
        if not isinstance(canonical, Mapping):
            raise ValueError("skill lifecycle canonical custody is invalid")
        target_relative = Path(str(canonical.get("target_relative") or ""))
        displaced_relative = Path(str(canonical.get("displaced_relative") or ""))
        if (
            target_relative.is_absolute()
            or displaced_relative.is_absolute()
            or ".." in target_relative.parts
            or ".." in displaced_relative.parts
        ):
            raise ValueError("skill lifecycle canonical path escapes custody")
        target = self.root / target_relative
        displaced = self.root / displaced_relative
        canonical_root = self.canonical.resolve(strict=False)
        preserved_root = self.preserved.resolve(strict=False)
        if target.parent.resolve(strict=False) != canonical_root or preserved_root not in displaced.resolve(strict=False).parents:
            raise PermissionError("skill lifecycle canonical path is outside owned roots")
        verify_safe_ancestors(
            self.root, target, include_target=os.path.lexists(target)
        )
        verify_safe_ancestors(
            self.root, displaced, include_target=os.path.lexists(displaced)
        )
        after_image = transaction / str(canonical.get("after_image") or "")
        after_rows, after_sha = _tree_attestation(after_image)
        if after_sha != canonical.get("after_tree_sha256"):
            raise PermissionError("skill lifecycle canonical after-image changed")
        before_sha = canonical.get("before_tree_sha256")
        current_sha = _tree_attestation(target)[1] if target.is_dir() else None
        if current_sha != after_sha:
            if current_sha == before_sha:
                if current_sha is not None:
                    if displaced.exists():
                        raise PermissionError("skill lifecycle displaced custody already exists")
                    displaced.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, displaced)
                    _fsync_directory(displaced.parent)
                    _fsync_directory(target.parent)
                current_sha = None
            if current_sha is None and before_sha is not None:
                if not displaced.is_dir() or _tree_attestation(displaced)[1] != before_sha:
                    raise PermissionError("skill lifecycle missing target lacks exact displaced custody")
            if current_sha is not None:
                raise PermissionError("canonical skill changed outside lifecycle transaction")
            prepared = target.with_name(f".{target.name}.{uuid4().hex}.lifecycle")
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_verified(after_image, prepared, after_rows)
            os.replace(prepared, target)
            _fsync_directory(target.parent)
        if _tree_attestation(target)[1] != after_sha:
            raise OSError("skill lifecycle canonical publication did not verify")

        for item in self._bounded_lifecycle_artifacts(transaction, manifest):
            relative = Path(str(item["path"]))
            artifact_target = self.root / relative
            verify_safe_ancestors(
                self.root,
                artifact_target,
                include_target=os.path.lexists(artifact_target),
            )
            if artifact_target.exists() and (
                artifact_target.is_symlink() or not artifact_target.is_file()
            ):
                raise ValueError("skill lifecycle artifact target is not a physical file")
            current = artifact_target.read_bytes() if artifact_target.is_file() else None
            current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
            before_sha = item.get("before_sha256")
            after_sha = item.get("after_sha256")
            if current_sha == after_sha:
                continue
            if current_sha != before_sha:
                raise PermissionError(
                    f"skill lifecycle artifact changed outside transaction: {relative.as_posix()}"
                )
            if item.get("after_exists") is True:
                payload = _read_bounded_regular_file(
                    transaction / str(item["after_image"]),
                    MAX_LIFECYCLE_ARTIFACT_BYTES,
                )
                _atomic_bytes(artifact_target, payload)
            elif artifact_target.is_file():
                artifact_target.unlink()
                _fsync_directory(artifact_target.parent)
        for item in self._bounded_lifecycle_artifacts(transaction, manifest):
            artifact_target = self.root / str(item["path"])
            current = artifact_target.read_bytes() if artifact_target.is_file() else None
            current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_sha != item.get("after_sha256"):
                raise OSError("skill lifecycle artifact publication did not verify")

    def _recover_lifecycle_transactions_locked(self) -> dict[str, object]:
        journal_root = self.drafts / "lifecycle-transactions"
        completed: list[str] = []
        retained: list[str] = []
        if not journal_root.is_dir():
            return {"valid": True, "completed": completed, "retained": retained}
        transactions = sorted(journal_root.iterdir(), key=lambda path: path.name)
        if len(transactions) > 1000:
            raise ValueError("skill lifecycle transaction count bound exceeded")
        for transaction in transactions:
            if transaction.name.startswith(".") and transaction.name.endswith(".preparing"):
                retained.append(transaction.name)
                continue
            manifest = self._read_lifecycle_manifest(transaction)
            state = manifest.get("state")
            if state == "applying":
                self._roll_lifecycle_transaction_forward(transaction, manifest)
                manifest["state"] = "committed"
                manifest["committed_utc"] = _now()
                self._write_lifecycle_manifest(transaction, manifest)
                completed.append(transaction.name)
            elif state == "prepared":
                manifest["state"] = "retained-before-apply"
                manifest["retained_utc"] = _now()
                self._write_lifecycle_manifest(transaction, manifest)
                retained.append(transaction.name)
            elif state not in {"committed", "retained-before-apply"}:
                raise ValueError("unknown skill lifecycle transaction state")
        return {"valid": True, "completed": completed, "retained": retained}

    def recover_lifecycle_transactions(self) -> dict[str, object]:
        with FileLock(self.lifecycle_lock, timeout_seconds=30):
            return self._recover_lifecycle_transactions_locked()

    def promote(self, package: SkillPackage, *, approved: bool) -> dict[str, object]:
        with FileLock(self.lifecycle_lock, timeout_seconds=30):
            self._recover_lifecycle_transactions_locked()
            self.recover_projection_transactions()
            self._validate_projection_denominators()
            draft = (
                self.drafts / _component(package.skill_id) / "revisions" / package.version
            )
            payload = draft / "payload"
            raw = (
                json.loads((draft / "admission-receipt.json").read_text(encoding="utf-8"))
                if (draft / "admission-receipt.json").is_file()
                else {}
            )
            admission = self.authority.verify_receipt(raw) if raw else {}
            package_record = json.loads(
                (draft / "package-record.json").read_text(encoding="utf-8")
            )
            current_rows, current_tree_sha256 = _tree_attestation(payload)
            preserved_original = _preserved_original_provenance(self.root, package)
            if not approved or admission.get("decision") != "admitted":
                raise PermissionError(
                    "skill promotion requires current admission and explicit approval"
                )
            if admission.get("manifest_sha256") != digest(asdict(package)) or admission.get(
                "source_tree_sha256"
            ) != current_tree_sha256:
                raise PermissionError("skill draft changed after admission")
            if (
                package_record.get("preserved_original") != preserved_original
                or admission.get("preserved_original") != preserved_original
            ):
                raise PermissionError(
                    "preserved-original provenance changed after admission"
                )
            target = self.canonical / _canonical_name(package.skill_id)
            backup = None
            if target.exists():
                old_rows, old_sha = _tree_attestation(target)
                backup = (
                    self.preserved
                    / "pre-promotion"
                    / _component(package.skill_id)
                    / old_sha
                )
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _copy_verified(target, backup, old_rows)
                elif _tree_attestation(backup)[1] != old_sha:
                    raise PermissionError("skill promotion backup custody changed")
            retired = (
                self.preserved
                / "replaced"
                / _component(package.skill_id)
                / f"{_now().replace(':', '-')}-{uuid4().hex}"
            )
            projection_updates = self._projection_updates(
                package, payload, preserved_original=preserved_original
            )
            projection_paths = [
                path.relative_to(self.root).as_posix()
                for path in sorted(projection_updates, key=lambda item: item.as_posix())
            ]
            receipt_path = draft / "promotion-receipt.json"
            transaction, manifest, receipt = self._prepare_lifecycle_transaction(
                package,
                operation="promotion",
                canonical_source=payload,
                target=target,
                displaced=retired,
                backup=backup,
                updates=projection_updates,
                receipt_path=receipt_path,
                receipt_payload={
                    "schema_version": "px.skill-promotion-receipt/1.3",
                    "skill_id": package.skill_id,
                    "version": package.version,
                    "target_relative": target.relative_to(self.root).as_posix(),
                    "backup_relative": backup.relative_to(self.root).as_posix()
                    if backup
                    else None,
                    "retired_relative": retired.relative_to(self.root).as_posix(),
                    "promoted_tree_sha256": current_tree_sha256,
                    "preserved_original": preserved_original,
                    "projection_updates": projection_paths,
                    "projection_after_sha256": {
                        path.relative_to(self.root).as_posix(): hashlib.sha256(data).hexdigest()
                        for path, data in projection_updates.items()
                        if data is not None
                    },
                    "rollback_available": bool(backup),
                    "promoted_utc": _now(),
                    "nonce": uuid4().hex,
                },
            )
            manifest["state"] = "applying"
            manifest["applying_utc"] = _now()
            self._write_lifecycle_manifest(transaction, manifest)
            self._roll_lifecycle_transaction_forward(transaction, manifest)
            manifest["state"] = "committed"
            manifest["committed_utc"] = _now()
            self._write_lifecycle_manifest(transaction, manifest)
            return receipt

    def rollback(
        self, promotion_receipt: Path, *, approved: bool, approver: str
    ) -> dict[str, object]:
        if not approved or not approver.strip():
            raise PermissionError(
                "skill rollback requires explicit identified approval"
            )
        with FileLock(self.lifecycle_lock, timeout_seconds=30):
            self._recover_lifecycle_transactions_locked()
            raw = json.loads(promotion_receipt.read_text(encoding="utf-8"))
            promotion = self.authority.verify_receipt(raw)
            backup_relative = promotion.get("backup_relative")
            if not backup_relative:
                raise ValueError("promotion has no rollback target")
            backup = (self.root / str(backup_relative)).resolve(strict=True)
            target = (self.root / str(promotion["target_relative"])).resolve(strict=True)
            if _tree_attestation(target)[1] != promotion.get("promoted_tree_sha256"):
                raise PermissionError(
                    "canonical skill changed after promotion; rollback conflict requires reconciliation"
                )
            transaction_relative = promotion.get("lifecycle_transaction_relative")
            if not isinstance(transaction_relative, str) or not transaction_relative:
                raise ValueError("promotion lifecycle rollback custody is unavailable")
            promotion_transaction = (self.root / transaction_relative).resolve(strict=True)
            promotion_manifest = self._read_lifecycle_manifest(promotion_transaction)
            if (
                promotion_manifest.get("state") != "committed"
                or promotion_manifest.get("operation") != "promotion"
                or promotion_manifest.get("skill_id") != promotion.get("skill_id")
                or promotion_manifest.get("version") != promotion.get("version")
            ):
                raise PermissionError("promotion lifecycle transaction is not rollback eligible")
            projection_paths = promotion.get("projection_updates")
            if not isinstance(projection_paths, list) or not all(
                isinstance(item, str) for item in projection_paths
            ):
                raise ValueError("promotion projection denominator is invalid")
            projection_artifacts = {
                str(item.get("path") or ""): item
                for item in self._bounded_lifecycle_artifacts(
                    promotion_transaction, promotion_manifest
                )
                if item.get("role") == "projection"
            }
            if set(projection_artifacts) != set(projection_paths):
                raise PermissionError("promotion projection rollback denominator changed")
            rollback_updates: dict[Path, bytes | None] = {}
            for path_text in projection_paths:
                item = projection_artifacts[path_text]
                before = None
                if item.get("before_exists") is True:
                    before = _read_bounded_regular_file(
                        promotion_transaction / str(item["before_image"]),
                        MAX_LIFECYCLE_ARTIFACT_BYTES,
                    )
                rollback_updates[self.root / path_text] = before
            restored_sha = _tree_attestation(backup)[1]
            displaced = (
                self.preserved
                / "rollback-displaced"
                / _component(str(promotion["skill_id"]))
                / f"{_now().replace(':', '-')}-{uuid4().hex}"
            )
            bound_package = SkillPackage(
                str(promotion["skill_id"]),
                str(promotion["version"]),
                "lifecycle-rollback",
                ("rollback authenticated lifecycle",),
                ("unrelated lifecycle",),
                ("read",),
                (),
                ("canonical backup",),
                ("promotion receipt",),
                ("lifecycle transaction",),
                {"source": "authenticated-promotion"},
            )
            rollback_path = promotion_receipt.with_name("rollback-receipt.json")
            transaction, manifest, receipt = self._prepare_lifecycle_transaction(
                bound_package,
                operation="rollback",
                canonical_source=backup,
                target=target,
                displaced=displaced,
                backup=backup,
                updates=rollback_updates,
                receipt_path=rollback_path,
                receipt_payload={
                    "schema_version": "px.skill-rollback-receipt/1.2",
                    "skill_id": promotion["skill_id"],
                    "version": promotion["version"],
                    "restored_tree_sha256": restored_sha,
                    "displaced_relative": displaced.relative_to(self.root).as_posix(),
                    "projection_restorations": projection_paths,
                    "projection_after_sha256": {
                        path.relative_to(self.root).as_posix(): hashlib.sha256(data).hexdigest()
                        if data is not None else None
                        for path, data in rollback_updates.items()
                    },
                    "promotion_lifecycle_transaction_relative": transaction_relative,
                    "approved_by": approver,
                    "rolled_back_utc": _now(),
                    "nonce": uuid4().hex,
                },
            )
            manifest["state"] = "applying"
            manifest["applying_utc"] = _now()
            self._write_lifecycle_manifest(transaction, manifest)
            self._roll_lifecycle_transaction_forward(transaction, manifest)
            manifest["state"] = "committed"
            manifest["committed_utc"] = _now()
            self._write_lifecycle_manifest(transaction, manifest)
            return receipt
