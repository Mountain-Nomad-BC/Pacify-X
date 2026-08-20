"""Deterministic, parameterized audit ZIPs with external checksums."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
import zipfile


LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)
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
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
        part in EXCLUDED_DIRECTORY_NAMES or part.startswith(".venv")
        for part in relative.parts[:-1]
    ):
        return "generated-or-dependency-directory"
    if relative.name == ".env" or relative.name.startswith(".env."):
        return "secret-bearing-environment-file"
    if any(relative.parts[: len(prefix)] == prefix for prefix in EXCLUDED_VOLATILE_PATHS):
        return "volatile-runtime-state"
    if relative.suffix.lower() in {".pyc", ".pyo"}:
        return "generated-bytecode"
    return None


def _inventory(
    inputs: Mapping[str, Path],
) -> tuple[list[dict[str, Any]], list[tuple[str, bytes]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    payloads: list[tuple[str, bytes]] = []
    exclusions: list[dict[str, str]] = []
    for label, supplied in sorted(inputs.items()):
        if LABEL.fullmatch(label) is None:
            raise ValueError(f"invalid audit input label: {label}")
        root = supplied.resolve(strict=True)
        paths = [root] if root.is_file() else sorted(
            path for path in root.rglob("*") if path.is_file()
        )
        for path in paths:
            if path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            ):
                raise ValueError(f"linked audit input refused: {path}")
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            relative_path = PurePosixPath(relative)
            reason = _exclusion_reason(relative_path)
            if reason is not None:
                exclusions.append({"label": label, "path": relative, "reason": reason})
                continue
            name = f"payload/{label}/{relative}"
            data = path.read_bytes()
            records.append(
                {
                    "label": label,
                    "path": relative,
                    "archive_path": name,
                    "bytes": len(data),
                    "sha256": _sha(data),
                }
            )
            payloads.append((name, data))
    names = [name for name, _ in payloads]
    if len(names) != len(set(names)):
        raise ValueError("audit inputs produce duplicate archive paths")
    return records, payloads, exclusions


def build_portable_audit_bundle(
    inputs: Mapping[str, Path],
    *,
    output_zip: Path,
    checksum_path: Path,
    prerequisites: Path,
    attestation: Path | None = None,
) -> dict[str, Any]:
    """Build deterministic audit bytes from explicit roots; never infer host paths."""
    if not inputs:
        raise ValueError("at least one labeled audit input is required")
    resolved_inputs = [path.resolve(strict=True) for path in inputs.values()]
    destination = output_zip.resolve()
    checksum = checksum_path.resolve()
    if destination == checksum:
        raise ValueError("ZIP and checksum paths must differ")
    for root in resolved_inputs:
        boundary = root if root.is_dir() else root.parent
        if _inside(destination, boundary) or _inside(checksum, boundary):
            raise ValueError("audit outputs must remain outside input roots")
    prerequisite_data = prerequisites.resolve(strict=True).read_bytes()
    prerequisite_json = json.loads(prerequisite_data)
    if not isinstance(prerequisite_json, dict):
        raise ValueError("prerequisite report must be a JSON object")
    records, payloads, exclusions = _inventory(inputs)
    manifest: dict[str, Any] = {
        "schema_version": "px.portable-audit-manifest/1.0",
        "files": records,
        "file_count": len(records),
        "payload_bytes": sum(int(item["bytes"]) for item in records),
        "excluded": exclusions,
        "excluded_count": len(exclusions),
        "prerequisites_sha256": _sha(prerequisite_data),
        "attestation_sha256": None,
    }
    extra = [("PREREQUISITES.json", prerequisite_data)]
    if attestation is not None:
        attestation_data = attestation.resolve(strict=True).read_bytes()
        json.loads(attestation_data)
        manifest["attestation_sha256"] = _sha(attestation_data)
        extra.append(("ATTESTATION.json", attestation_data))
    members = [("AUDIT_MANIFEST.json", _json_bytes(manifest)), *extra, *payloads]
    destination.parent.mkdir(parents=True, exist_ok=True)
    prepared = destination.with_name(f".{destination.name}.prepared")
    if prepared.exists():
        raise ValueError("prepared audit bundle already exists")
    with zipfile.ZipFile(
        prepared, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in members:
            info, content = _member(name, data)
            archive.writestr(info, content)
    os.replace(prepared, destination)
    bundle_sha256 = _sha(destination.read_bytes())
    checksum.parent.mkdir(parents=True, exist_ok=True)
    checksum_prepared = checksum.with_name(f".{checksum.name}.prepared")
    with checksum_prepared.open("x", encoding="ascii", newline="\n") as stream:
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
    bundle: Path, checksum_path: Path
) -> dict[str, Any]:
    """Verify outer identity and every manifest-bound member without source roots."""
    errors: list[str] = []
    bundle = bundle.resolve(strict=True)
    checksum_text = checksum_path.resolve(strict=True).read_text(encoding="ascii").strip()
    parts = checksum_text.split()
    actual_outer = _sha(bundle.read_bytes())
    if len(parts) != 2 or parts[1] != bundle.name or parts[0] != actual_outer:
        errors.append("external bundle checksum mismatch")
    try:
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                errors.append("duplicate archive member")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    errors.append(f"unsafe archive member: {name}")
            manifest = json.loads(archive.read("AUDIT_MANIFEST.json"))
            expected_names = {"AUDIT_MANIFEST.json", "PREREQUISITES.json"}
            if manifest.get("attestation_sha256") is not None:
                expected_names.add("ATTESTATION.json")
            for record in manifest.get("files", ()):
                name = str(record.get("archive_path", ""))
                expected_names.add(name)
                data = archive.read(name)
                if len(data) != record.get("bytes") or _sha(data) != record.get("sha256"):
                    errors.append(f"payload member mismatch: {name}")
            prerequisite_data = archive.read("PREREQUISITES.json")
            if _sha(prerequisite_data) != manifest.get("prerequisites_sha256"):
                errors.append("prerequisite report mismatch")
            if manifest.get("attestation_sha256") is not None and _sha(
                archive.read("ATTESTATION.json")
            ) != manifest.get("attestation_sha256"):
                errors.append("attestation mismatch")
            if set(names) != expected_names:
                errors.append("archive member set differs from manifest")
            if manifest.get("file_count") != len(manifest.get("files", ())):
                errors.append("manifest file count mismatch")
    except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        errors.append(f"audit bundle unreadable: {type(error).__name__}: {error}")
        manifest = {}
    return {
        "schema_version": "px.portable-audit-verification/1.0",
        "valid": not errors,
        "bundle_sha256": actual_outer,
        "file_count": manifest.get("file_count", 0),
        "errors": errors,
    }
