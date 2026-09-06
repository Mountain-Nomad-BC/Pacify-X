"""Content-addressed custody for complete release-evidence ZIP bundles."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Iterable, Mapping
from uuid import uuid4
import zipfile


def _files(inputs: Iterable[Path]) -> list[tuple[Path, str]]:
    records: list[tuple[Path, str]] = []
    for supplied in inputs:
        if supplied.is_symlink() or (
            hasattr(supplied, "is_junction") and supplied.is_junction()
        ):
            raise ValueError("evidence custody input cannot be a link or junction")
        source = supplied.resolve(strict=True)
        if source.is_file():
            records.append((source, source.name))
        else:
            for path in sorted(source.rglob("*")):
                if path.is_symlink() or (
                    hasattr(path, "is_junction") and path.is_junction()
                ):
                    raise ValueError("evidence custody tree contains a link or junction")
                if not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                try:
                    resolved.relative_to(source)
                except ValueError as exc:
                    raise ValueError("evidence custody input escaped its root") from exc
                records.append(
                    (resolved, f"{source.name}/{resolved.relative_to(source).as_posix()}")
                )
    names = [name for _, name in records]
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("evidence inputs produce duplicate archive paths")
    return sorted(records, key=lambda item: item[1])


def build_evidence_custody(
    inputs: Iterable[Path],
    *,
    release: str,
    source_commit: str,
    output_dir: Path,
    work_dir: Path,
    locator_base: str,
    chunk_size: int = 90 * 1024 * 1024,
    certificate: Path | None = None,
    subjects: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Build one deterministic ZIP, then publishable byte-exact chunks and a receipt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    bundle_name = f"pacify-x-v{release}-complete-evidence.zip"
    bundle = work_dir / bundle_name
    records = _files(inputs)
    with zipfile.ZipFile(
        bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path, name in records:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    bundle_hash = hashlib.sha256()
    chunks: list[dict[str, Any]] = []
    with bundle.open("rb") as source:
        index = 0
        while data := source.read(chunk_size):
            index += 1
            bundle_hash.update(data)
            name = f"{bundle_name}.part-{index:04d}"
            target = output_dir / name
            target.write_bytes(data)
            chunks.append(
                {
                    "index": index,
                    "filename": name,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "uri": locator_base.rstrip("/") + "/" + name,
                }
            )
    certificate_binding: dict[str, Any] = {}
    if certificate is not None:
        certificate = certificate.resolve(strict=True)
        matches = [name for path, name in records if path == certificate]
        if len(matches) != 1:
            raise ValueError("certificate must occur exactly once in custody inputs")
        value = json.loads(certificate.read_text(encoding="utf-8"))
        certificate_binding = {
            "archive_path": matches[0],
            "certificate_sha256": hashlib.sha256(certificate.read_bytes()).hexdigest(),
            "release": value.get("release"),
            "product_digest": value.get("product_digest"),
            "harness_digest": value.get("harness_digest"),
            "release_commit": value.get("source_control", {}).get("commit_sha"),
        }
    subject_bindings: dict[str, Any] = {}
    for label, subject in (subjects or {}).items():
        subject = subject.resolve(strict=True)
        matches = [name for path, name in records if path == subject]
        if len(matches) != 1:
            raise ValueError(f"{label} must occur exactly once in custody inputs")
        subject_bindings[label] = {
            "archive_path": matches[0],
            "sha256": hashlib.sha256(subject.read_bytes()).hexdigest(),
            "size": subject.stat().st_size,
        }
    return {
        "schema_version": "1.1" if subject_bindings else "1.0",
        "receipt_type": "complete_release_evidence_custody",
        "release": release,
        "source_commit": source_commit,
        "bundle_filename": bundle_name,
        "bundle_format": "zip",
        "bundle_size": bundle.stat().st_size,
        "bundle_sha256": bundle_hash.hexdigest(),
        "chunk_size_limit": chunk_size,
        "chunks": chunks,
        "retention_policy": "GitHub Release assets retained with the immutable release",
        "reconstruction": "concatenate chunks by ascending index; verify each chunk and final SHA-256; open resulting ZIP",
        "temporary_ci_artifact_required": False,
        "certificate_binding": certificate_binding,
        "subjects": subject_bindings,
    }


def verify_evidence_custody(receipt: dict[str, Any], asset_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    digest = hashlib.sha256()
    size = 0
    chunks = receipt.get("chunks", ())
    if not isinstance(chunks, list) or not chunks:
        return {"valid": False, "errors": ["custody receipt has no chunks"]}
    expected_indexes = list(range(1, len(chunks) + 1))
    if [item.get("index") for item in chunks] != expected_indexes:
        errors.append("custody chunks are not a contiguous ordered sequence")
    seen: set[str] = set()
    for item in chunks:
        if not isinstance(item, dict):
            errors.append("custody chunk record is malformed")
            continue
        filename = str(item.get("filename", ""))
        path = asset_dir / filename
        if (
            not filename
            or Path(filename).name != filename
            or filename.casefold() in seen
        ):
            errors.append("custody chunk filename is unsafe or duplicated")
            continue
        seen.add(filename.casefold())
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing custody chunk: {path.name}")
            continue
        data = path.read_bytes()
        if (
            not isinstance(item.get("size"), int)
            or len(data) != item.get("size")
            or hashlib.sha256(data).hexdigest() != item.get("sha256")
        ):
            errors.append(f"custody chunk mismatch: {path.name}")
            continue
        digest.update(data)
        size += len(data)
    if size != receipt.get("bundle_size") or digest.hexdigest() != receipt.get(
        "bundle_sha256"
    ):
        errors.append("reconstructed evidence bundle digest or size mismatch")
    return {
        "valid": not errors,
        "chunks": len(chunks),
        "bundle_size": size,
        "bundle_sha256": digest.hexdigest(),
        "errors": errors,
    }


def reconstruct_evidence_custody(
    receipt: dict[str, Any], asset_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Verify, reconstruct, and safely extract one signed-custody ZIP."""

    verification = verify_evidence_custody(receipt, asset_dir)
    if verification["valid"] is not True:
        return {**verification, "extracted": False}
    bundle_name = str(receipt.get("bundle_filename") or "")
    if (
        not bundle_name
        or Path(bundle_name).name != bundle_name
        or not bundle_name.endswith(".zip")
        or receipt.get("bundle_format") != "zip"
    ):
        return {
            **verification,
            "valid": False,
            "extracted": False,
            "errors": ["custody bundle filename or format is unsafe"],
        }
    output_dir = output_dir.resolve()
    if output_dir.exists():
        return {
            **verification,
            "valid": False,
            "extracted": False,
            "errors": ["custody extraction output already exists"],
        }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    prepared = output_dir.parent / f".{output_dir.name}.{uuid4().hex}.new"
    bundle = prepared.with_suffix(".zip")
    errors: list[str] = []
    try:
        with bundle.open("xb") as stream:
            for chunk in receipt["chunks"]:
                stream.write((asset_dir / str(chunk["filename"])).read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        prepared.mkdir()
        with zipfile.ZipFile(bundle) as archive:
            rows = archive.infolist()
            names = [row.filename for row in rows]
            folded: set[str] = set()
            if len(rows) > 250_000:
                errors.append("custody archive entry bound exceeded")
            if sum(row.file_size for row in rows) > 20 * 1024 * 1024 * 1024:
                errors.append("custody archive extraction-size bound exceeded")
            for row in rows:
                normalized = row.filename.replace("\\", "/")
                parts = Path(normalized).parts
                mode = (row.external_attr >> 16) & 0o170000
                unsafe = (
                    not normalized
                    or normalized.startswith("/")
                    or Path(normalized).is_absolute()
                    or ".." in parts
                    or any(part.rstrip(" .") != part for part in parts)
                    or row.flag_bits & 1
                    or mode == stat.S_IFLNK
                    or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or normalized.casefold() in folded
                )
                folded.add(normalized.casefold())
                if unsafe:
                    errors.append(f"unsafe custody archive entry: {row.filename}")
            if len(names) != len(set(names)):
                errors.append("custody archive contains duplicate entries")
            if errors:
                return {
                    **verification,
                    "valid": False,
                    "extracted": False,
                    "errors": errors,
                }
            for row in rows:
                target = prepared / Path(row.filename.replace("\\", "/"))
                if row.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(row) as source, target.open("xb") as destination:
                    while data := source.read(1024 * 1024):
                        destination.write(data)
        os.replace(prepared, output_dir)
        return {
            **verification,
            "valid": True,
            "extracted": True,
            "output_dir": str(output_dir),
            "entry_count": len(names),
        }
    finally:
        if bundle.exists():
            bundle.unlink()
        if prepared.exists():
            shutil.rmtree(prepared)
