"""Content-addressed custody for complete release-evidence ZIP bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
import zipfile


def _files(inputs: Iterable[Path]) -> list[tuple[Path, str]]:
    records: list[tuple[Path, str]] = []
    for source in inputs:
        source = source.resolve(strict=True)
        if source.is_file():
            records.append((source, source.name))
        else:
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                records.append(
                    (path, f"{source.name}/{path.relative_to(source).as_posix()}")
                )
    names = [name for _, name in records]
    if len(names) != len(set(names)):
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
) -> dict[str, Any]:
    """Build one deterministic ZIP, then publishable byte-exact chunks and a receipt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    bundle_name = f"pacify-x-v{release}-complete-evidence.zip"
    bundle = work_dir / bundle_name
    with zipfile.ZipFile(
        bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path, name in _files(inputs):
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
        value = json.loads(certificate.read_text(encoding="utf-8"))
        certificate_binding = {
            "certificate_sha256": hashlib.sha256(certificate.read_bytes()).hexdigest(),
            "product_digest": value.get("product_digest"),
            "release_commit": value.get("source_control", {}).get("commit_sha"),
        }
    return {
        "schema_version": "1.0",
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
    for item in chunks:
        path = asset_dir / str(item.get("filename", ""))
        if not path.is_file():
            errors.append(f"missing custody chunk: {path.name}")
            continue
        data = path.read_bytes()
        if len(data) != item.get("size") or hashlib.sha256(
            data
        ).hexdigest() != item.get("sha256"):
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
