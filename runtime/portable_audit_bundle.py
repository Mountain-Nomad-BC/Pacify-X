"""Deterministic, parameterized audit ZIPs with external checksums."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
import zipfile
import zlib

from .archive_io import (
    ArchiveLimits,
    BoundedArchiveWriter,
    DEFAULT_LIMITS,
    member_identity,
    portable_member_name,
    read_archive_bytes,
    read_stream_bytes,
    reject_path_links,
    validated_zip,
)
from .bounded_walk import WalkLimits, bounded_walk
from .json_io import bounded_json_text, decode_json_object, read_bounded_bytes


LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)
MAX_METADATA_BYTES = 4 * 1024 * 1024
CONTENT_POLICY = (
    "portable-path-exclusions-and-private-key-markers; not a complete secret scan"
)
PRIVATE_KEY = re.compile(rb"(?m)^[ \t]*-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----\r?$")
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "Python",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
)
EXCLUDED_VOLATILE_PATHS = (
    (".engineering-bootstrap", "operation-bus"),
    (".engineering-bootstrap", "runtime"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    bounded_json_text(value, max_bytes=MAX_METADATA_BYTES - 1)
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _member(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, ARCHIVE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info, data


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _exclusion_reason(relative: PurePosixPath) -> str | None:
    """Return a stable reason for content that must not enter a clean audit ZIP."""
    if any(
        part.casefold() in {name.casefold() for name in EXCLUDED_DIRECTORY_NAMES}
        or part.casefold().startswith(".venv")
        for part in relative.parts[:-1]
    ):
        return "generated-or-dependency-directory"
    if any("quarantine" in part.casefold() for part in relative.parts[:-1]):
        return "quarantine-content-excluded"
    name = relative.name.casefold()
    if name == ".env" or name.startswith(".env."):
        return "secret-bearing-environment-file"
    if relative.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"} or name in {
        "credentials.json",
        "secrets.json",
    }:
        return "secret-bearing-key-file"
    parts = tuple(part.casefold() for part in relative.parts)
    if any(parts[: len(prefix)] == prefix for prefix in EXCLUDED_VOLATILE_PATHS):
        return "volatile-runtime-state"
    if relative.suffix.lower() in {".pyc", ".pyo"}:
        return "generated-bytecode"
    return None


def _validate_inputs(inputs: Mapping[str, Path]) -> None:
    if not isinstance(inputs, Mapping) or not 1 <= len(inputs) <= 64:
        raise ValueError("audit inputs require 1..64 labeled roots")
    for label, supplied in inputs.items():
        if (
            type(label) is not str
            or LABEL.fullmatch(label) is None
            or not isinstance(supplied, Path)
        ):
            raise ValueError("invalid audit input label or path")


def _inventory(
    inputs: Mapping[str, Path],
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
    metadata_bytes: int = 0,
    attestation_included: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[str, bytes]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    exclusions: list[dict[str, str]] = []
    _validate_inputs(inputs)
    planned = []
    total_bytes = 0
    examined_entries = 0
    names = set()
    for label, supplied in sorted(inputs.items()):
        reject_path_links(supplied)
        if any("quarantine" in part.casefold() for part in supplied.parts):
            raise ValueError("quarantine audit roots are excluded")
        root = supplied.resolve(strict=True)

        def excluded(relative):
            is_dir = (root / relative).is_dir()
            candidate = (
                PurePosixPath(relative) / "__entry__"
                if is_dir
                else PurePosixPath(relative)
            )
            reason = _exclusion_reason(candidate)
            if reason is not None:
                if len(exclusions) >= limits.max_members:
                    raise ValueError("audit exclusion record budget exceeded")
                exclusions.append(
                    {
                        "label": label,
                        "path": relative + ("/" if is_dir else ""),
                        "reason": reason,
                    }
                )
            return reason is not None

        if root.is_file():
            if excluded(root.name):
                continue
            candidates = [(root, root.name, root.stat().st_size)]
        else:
            tree = bounded_walk(
                root,
                limits=WalkLimits(
                    max_files=max(1, limits.max_members - len(planned)),
                    max_depth=64,
                    max_bytes=max(1, limits.max_expanded_bytes - total_bytes),
                    max_entries=max(1, limits.max_members * 8 - examined_entries),
                    max_directories=limits.max_members,
                ),
                exclude=excluded,
            )
            examined_entries += tree.scanned_entries
            candidates = [
                (entry.path, entry.relative, entry.size) for entry in tree.files
            ]
        for path, relative, size in candidates:
            portable_member_name(relative, allow_directory=False)
            name = f"payload/{label}/{relative}"
            identity = member_identity(name)
            if identity in names:
                raise ValueError("audit inputs produce duplicate archive paths")
            names.add(identity)
            total_bytes += size
            if (
                size > limits.max_member_bytes
                or total_bytes > limits.max_expanded_bytes
                or len(planned) >= limits.max_members
            ):
                raise ValueError("audit source file or aggregate byte budget exceeded")
            planned.append((label, path, relative, name, size, root))
            records.append(
                {
                    "label": label,
                    "path": relative,
                    "archive_path": name,
                    "bytes": size,
                    "sha256": "0" * 64,
                }
            )
    if not planned:
        raise ValueError("audit payload must contain at least one included file")
    projected_manifest = _make_manifest(
        records, exclusions, "0" * 64, "0" * 64 if attestation_included else None
    )
    manifest_bytes = len(_json_bytes(projected_manifest))
    if (
        len(records) + 2 + int(attestation_included) > limits.max_members
        or total_bytes + metadata_bytes + manifest_bytes > limits.max_expanded_bytes
    ):
        raise ValueError(
            "audit complete archive member or byte budget exceeded before payload acquisition"
        )
    remaining = limits.max_expanded_bytes - metadata_bytes - manifest_bytes
    for record, (label, path, relative, name, size, root) in zip(records, planned):
        reject_path_links(path)
        if not path.resolve().is_relative_to(root if root.is_dir() else root.parent):
            raise ValueError("audit source escaped its root")
        with path.open("rb") as stream:
            data = read_stream_bytes(
                stream,
                max_bytes=min(limits.max_member_bytes, remaining),
                expected_size=size,
            )
        if len(data) != size or len(data) > remaining:
            raise ValueError("audit input size changed during acquisition")
        if PRIVATE_KEY.search(data):
            raise ValueError(f"private-key content refused in audit input: {name}")
        remaining -= len(data)
        record["sha256"] = _sha(data)
        payloads.append((name, data))
    return records, payloads, exclusions


def _make_manifest(records, exclusions, prerequisite_hash, attestation_hash):
    return {
        "schema_version": "px.portable-audit-manifest/1.0",
        "files": records,
        "file_count": len(records),
        "payload_bytes": sum(item["bytes"] for item in records),
        "excluded": exclusions,
        "excluded_count": len(exclusions),
        "prerequisites_sha256": prerequisite_hash,
        "attestation_sha256": attestation_hash,
        "content_policy": CONTENT_POLICY,
    }


def _validate_manifest(manifest: dict[str, Any], limits: ArchiveLimits) -> None:
    fields = {
        "schema_version",
        "files",
        "file_count",
        "payload_bytes",
        "excluded",
        "excluded_count",
        "prerequisites_sha256",
        "attestation_sha256",
    }
    if not fields <= manifest.keys() or manifest.keys() - fields - {"content_policy"}:
        raise ValueError("audit manifest fields are incomplete or unknown")
    if manifest["schema_version"] != "px.portable-audit-manifest/1.0":
        raise ValueError("audit manifest schema is unsupported")
    if "content_policy" in manifest and manifest["content_policy"] != CONTENT_POLICY:
        raise ValueError("unsupported audit content policy")

    def digest(value):
        return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None

    if (
        not digest(manifest["prerequisites_sha256"])
        or manifest["attestation_sha256"] is not None
        and not digest(manifest["attestation_sha256"])
    ):
        raise ValueError("audit metadata digest is malformed")
    files = manifest["files"]
    if type(files) is not list or not 1 <= len(files) <= limits.max_members:
        raise ValueError("audit manifest requires a bounded nonempty file denominator")
    seen = set()
    total = 0
    for record in files:
        if type(record) is not dict or set(record) != {
            "label",
            "path",
            "archive_path",
            "bytes",
            "sha256",
        }:
            raise ValueError("audit file record is malformed")
        if type(record["label"]) is not str or LABEL.fullmatch(record["label"]) is None:
            raise ValueError("audit file label is malformed")
        portable_member_name(record["path"], allow_directory=False)
        name = f"payload/{record['label']}/{record['path']}"
        if (
            record["archive_path"] != name
            or _exclusion_reason(PurePosixPath(record["path"])) is not None
        ):
            raise ValueError(
                "audit manifest includes an excluded or misidentified path"
            )
        identity = member_identity(name)
        if identity in seen:
            raise ValueError("duplicate audit manifest file identity")
        seen.add(identity)
        if (
            type(record["bytes"]) is not int
            or not 0 <= record["bytes"] <= limits.max_member_bytes
            or not digest(record["sha256"])
        ):
            raise ValueError("audit file size or digest is malformed")
        total += record["bytes"]
    if type(manifest["file_count"]) is not int or manifest["file_count"] != len(files):
        raise ValueError("manifest file count mismatch")
    if (
        type(manifest["payload_bytes"]) is not int
        or manifest["payload_bytes"] != total
        or total > limits.max_expanded_bytes
    ):
        raise ValueError("manifest payload byte denominator mismatch")
    excluded = manifest["excluded"]
    if type(excluded) is not list or len(excluded) > limits.max_members:
        raise ValueError("audit exclusions require a bounded list")
    excluded_ids = set()
    for record in excluded:
        if type(record) is not dict or set(record) != {"label", "path", "reason"}:
            raise ValueError("audit exclusion record is malformed")
        if type(record["label"]) is not str or LABEL.fullmatch(record["label"]) is None:
            raise ValueError("audit exclusion label is malformed")
        portable_member_name(record["path"])
        path = PurePosixPath(record["path"])
        if record["path"].endswith("/"):
            path = path / "__entry__"
        if not record["reason"] or _exclusion_reason(path) != record["reason"]:
            raise ValueError("audit exclusion reason does not match its path")
        identity = member_identity(record["label"] + "/" + record["path"])
        if identity in excluded_ids:
            raise ValueError("duplicate audit exclusion record")
        excluded_ids.add(identity)
    if type(manifest["excluded_count"]) is not int or manifest["excluded_count"] != len(
        excluded
    ):
        raise ValueError("manifest exclusion count mismatch")


def build_portable_audit_bundle(
    inputs: Mapping[str, Path],
    *,
    output_zip: Path,
    checksum_path: Path,
    prerequisites: Path,
    attestation: Path | None = None,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Build deterministic audit bytes from explicit roots; never infer host paths."""
    _validate_inputs(inputs)
    if (
        any(
            not isinstance(path, Path)
            for path in (output_zip, checksum_path, prerequisites)
        )
        or attestation is not None
        and not isinstance(attestation, Path)
    ):
        raise ValueError("audit output and metadata paths must be Path values")
    for path in [
        *inputs.values(),
        prerequisites,
        *([attestation] if attestation is not None else []),
    ]:
        reject_path_links(path)
    resolved_inputs = [path.resolve(strict=True) for path in inputs.values()]
    destination = output_zip.resolve()
    checksum = checksum_path.resolve()
    portable_member_name(destination.name, allow_directory=False)
    portable_member_name(checksum.name, allow_directory=False)
    if destination == checksum:
        raise ValueError("ZIP and checksum paths must differ")
    for root in resolved_inputs:
        boundary = root if root.is_dir() else root.parent
        if _inside(destination, boundary) or _inside(checksum, boundary):
            raise ValueError("audit outputs must remain outside input roots")
    prepared = destination.with_name(f".{destination.name}.prepared")
    checksum_prepared = checksum.with_name(f".{checksum.name}.prepared")
    outputs = [destination, checksum, prepared, checksum_prepared]
    source_metadata = {
        prerequisites.resolve(),
        *([attestation.resolve()] if attestation is not None else []),
    }
    if len(set(outputs)) != 4 or source_metadata.intersection(outputs):
        raise ValueError("audit output or prerequisite paths collide")
    if prepared.exists() or checksum_prepared.exists():
        raise ValueError("prepared audit output already exists")
    prerequisite_data = read_bounded_bytes(
        prerequisites, max_bytes=min(MAX_METADATA_BYTES, limits.max_expanded_bytes)
    )
    decode_json_object(prerequisite_data, max_bytes=MAX_METADATA_BYTES)
    if PRIVATE_KEY.search(prerequisite_data):
        raise ValueError("private-key content refused in prerequisite report")
    extra = [("PREREQUISITES.json", prerequisite_data)]
    attestation_hash = None
    if attestation is not None:
        remaining_metadata = limits.max_expanded_bytes - len(prerequisite_data)
        if remaining_metadata < 1:
            raise ValueError("audit metadata byte budget exhausted")
        attestation_data = read_bounded_bytes(
            attestation, max_bytes=min(MAX_METADATA_BYTES, remaining_metadata)
        )
        decode_json_object(attestation_data, max_bytes=MAX_METADATA_BYTES)
        if PRIVATE_KEY.search(attestation_data):
            raise ValueError("private-key content refused in attestation report")
        attestation_hash = _sha(attestation_data)
        extra.append(("ATTESTATION.json", attestation_data))
    records, payloads, exclusions = _inventory(
        inputs,
        limits=limits,
        metadata_bytes=sum(len(data) for _, data in extra),
        attestation_included=attestation is not None,
    )
    manifest = _make_manifest(
        records, exclusions, _sha(prerequisite_data), attestation_hash
    )
    _validate_manifest(manifest, limits)
    members = [("AUDIT_MANIFEST.json", _json_bytes(manifest)), *extra, *payloads]
    if (
        len(members) > limits.max_members
        or sum(len(data) for _, data in members) > limits.max_expanded_bytes
    ):
        raise ValueError("audit complete archive member or byte budget exceeded")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        prepared.open("xb") as stream,
        zipfile.ZipFile(
            BoundedArchiveWriter(stream, limits.max_archive_bytes),
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=False,
        ) as archive,
    ):
        for name, data in members:
            info, content = _member(name, data)
            archive.writestr(info, content)
    bundle_sha256 = _sha(read_archive_bytes(prepared, limits))
    os.replace(prepared, destination)
    checksum.parent.mkdir(parents=True, exist_ok=True)
    with checksum_prepared.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{bundle_sha256}  {destination.name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(checksum_prepared, checksum)
    return {
        "schema_version": "px.portable-audit-bundle/1.0",
        "bundle": destination.as_posix(),
        "checksum": checksum.as_posix(),
        "bundle_sha256": bundle_sha256,
        "file_count": len(records),
        "payload_bytes": manifest["payload_bytes"],
        "attestation_included": attestation is not None,
    }


def verify_portable_audit_bundle(
    bundle: Path,
    checksum_path: Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Verify bounded internal identity and exact members; not authenticated origin."""
    errors: list[str] = []
    actual_outer = None
    manifest = {}
    try:
        reject_path_links(checksum_path)
        checksum_text = read_bounded_bytes(checksum_path, max_bytes=8192).decode(
            "utf-8"
        )
        raw = read_archive_bytes(bundle, limits)
        actual_outer = _sha(raw)
        expected_line = f"{actual_outer}  {bundle.name}"
        if checksum_text not in (
            expected_line,
            expected_line + "\n",
            expected_line + "\r\n",
        ):
            raise ValueError("external bundle checksum mismatch")
        with validated_zip(raw, limits) as (archive, infos):
            by_name = {info.filename: info for info in infos}

            def member(name, limit):
                info = by_name[name]
                if info.is_dir() or info.file_size > limit:
                    raise ValueError("audit member byte budget or file type violated")
                with archive.open(info) as stream:
                    data = read_stream_bytes(
                        stream, max_bytes=limit, expected_size=info.file_size
                    )
                if PRIVATE_KEY.search(data):
                    raise ValueError(
                        "private-key content refused in audit member: " + name
                    )
                return data

            manifest = decode_json_object(
                member("AUDIT_MANIFEST.json", MAX_METADATA_BYTES),
                max_bytes=MAX_METADATA_BYTES,
            )
            _validate_manifest(manifest, limits)
            expected_names = {"AUDIT_MANIFEST.json", "PREREQUISITES.json"}
            expected_names.update(
                record["archive_path"] for record in manifest["files"]
            )
            if manifest["attestation_sha256"] is not None:
                expected_names.add("ATTESTATION.json")
            if set(by_name) != expected_names:
                raise ValueError("archive member set differs from manifest")
            prerequisite_data = member("PREREQUISITES.json", MAX_METADATA_BYTES)
            decode_json_object(prerequisite_data, max_bytes=MAX_METADATA_BYTES)
            if _sha(prerequisite_data) != manifest["prerequisites_sha256"]:
                raise ValueError("prerequisite report mismatch")
            if manifest["attestation_sha256"] is not None:
                attestation_data = member("ATTESTATION.json", MAX_METADATA_BYTES)
                decode_json_object(attestation_data, max_bytes=MAX_METADATA_BYTES)
                if _sha(attestation_data) != manifest["attestation_sha256"]:
                    raise ValueError("attestation mismatch")
            for record in manifest["files"]:
                info = by_name[record["archive_path"]]
                if info.file_size != record["bytes"]:
                    raise ValueError("payload member size differs from manifest")
                data = member(record["archive_path"], record["bytes"])
                if _sha(data) != record["sha256"]:
                    raise ValueError(
                        "payload member mismatch: " + record["archive_path"]
                    )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        EOFError,
        zipfile.BadZipFile,
        zlib.error,
    ) as error:
        if "duplicate archive member" in str(error):
            errors.append("duplicate archive member")
        errors.append(str(error))
    return {
        "schema_version": "px.portable-audit-verification/1.0",
        "valid": not errors,
        "bundle_sha256": actual_outer,
        "file_count": manifest.get("file_count", 0) if not errors else 0,
        "verification_scope": "bounded internal checksums and declared members; origin not authenticated",
        "errors": errors,
    }
