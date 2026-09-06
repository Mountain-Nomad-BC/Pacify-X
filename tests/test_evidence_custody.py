from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

from runtime.evidence_custody import (
    build_evidence_custody,
    reconstruct_evidence_custody,
    verify_evidence_custody,
)


def test_complete_evidence_is_chunked_reconstructable_and_content_addressed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.json").write_text('{"a":1}\n', encoding="utf-8")
    (source / "b.log").write_bytes(b"evidence" * 100)
    output = tmp_path / "assets"
    receipt = build_evidence_custody(
        [source],
        release="1.2.3",
        source_commit="a" * 40,
        output_dir=output,
        work_dir=tmp_path / "work",
        locator_base="https://example.test/releases/v1.2.3",
        chunk_size=100,
    )
    assert len(receipt["chunks"]) > 1
    assert verify_evidence_custody(receipt, output)["valid"]
    reconstructed = b"".join(
        (output / item["filename"]).read_bytes() for item in receipt["chunks"]
    )
    archive = tmp_path / "reconstructed.zip"
    archive.write_bytes(reconstructed)
    with zipfile.ZipFile(archive) as value:
        assert value.namelist() == ["source/a.json", "source/b.log"]


def test_missing_or_corrupt_chunk_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "record.json"
    source.write_text("{}", encoding="utf-8")
    output = tmp_path / "assets"
    receipt = build_evidence_custody(
        [source],
        release="1.0.0",
        source_commit="b" * 40,
        output_dir=output,
        work_dir=tmp_path / "work",
        locator_base="https://example.test",
        chunk_size=10,
    )
    first = output / receipt["chunks"][0]["filename"]
    first.write_bytes(first.read_bytes() + b"tamper")
    assert not verify_evidence_custody(receipt, output)["valid"]
    first.unlink()
    assert not verify_evidence_custody(receipt, output)["valid"]


def test_verified_custody_is_safely_reconstructed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "proof.json").write_text('{"valid":true}\n', encoding="utf-8")
    assets = tmp_path / "assets"
    receipt = build_evidence_custody(
        [source],
        release="1.0.0",
        source_commit="c" * 40,
        output_dir=assets,
        work_dir=tmp_path / "work",
        locator_base="https://example.test",
        chunk_size=7,
    )
    output = tmp_path / "restored"
    result = reconstruct_evidence_custody(receipt, assets, output)
    assert result["valid"]
    assert result["extracted"]
    assert (output / "source/proof.json").read_text(encoding="utf-8") == (
        '{"valid":true}\n'
    )
    assert not reconstruct_evidence_custody(receipt, assets, output)["valid"]


def _receipt_for_archive(tmp_path: Path, members: list[tuple[str, bytes]]) -> tuple[dict, Path]:
    bundle_name = "pacify-x-v1.0.0-complete-evidence.zip"
    bundle = tmp_path / bundle_name
    with zipfile.ZipFile(bundle, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    data = bundle.read_bytes()
    assets = tmp_path / "assets"
    assets.mkdir()
    chunk_name = f"{bundle_name}.part-0001"
    (assets / chunk_name).write_bytes(data)
    return (
        {
            "bundle_filename": bundle_name,
            "bundle_format": "zip",
            "bundle_size": len(data),
            "bundle_sha256": hashlib.sha256(data).hexdigest(),
            "chunks": [
                {
                    "index": 1,
                    "filename": chunk_name,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ],
        },
        assets,
    )


def test_reconstruction_rejects_traversal_and_duplicate_members(tmp_path: Path) -> None:
    traversal, assets = _receipt_for_archive(tmp_path, [("../escape", b"bad")])
    assert not reconstruct_evidence_custody(
        traversal, assets, tmp_path / "traversal-output"
    )["valid"]
    assert not (tmp_path / "escape").exists()

    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    duplicate, duplicate_assets = _receipt_for_archive(
        duplicate_root,
        [("proof.json", b"one"), ("proof.json", b"two")],
    )
    assert not reconstruct_evidence_custody(
        duplicate, duplicate_assets, tmp_path / "duplicate-output"
    )["valid"]


def test_chunk_path_escape_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    receipt = build_evidence_custody(
        [source],
        release="1.0.0",
        source_commit="d" * 40,
        output_dir=tmp_path / "assets",
        work_dir=tmp_path / "work",
        locator_base="https://example.test",
    )
    receipt["chunks"][0]["filename"] = "../outside"
    assert not verify_evidence_custody(receipt, tmp_path / "assets")["valid"]
