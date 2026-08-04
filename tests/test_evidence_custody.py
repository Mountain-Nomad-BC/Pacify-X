from __future__ import annotations

from pathlib import Path
import zipfile

from runtime.evidence_custody import build_evidence_custody, verify_evidence_custody


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
