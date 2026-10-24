from __future__ import annotations

import json
from pathlib import Path

import pytest

"""PX-GAP-0012: the content-addressed source freeze implementing BASE-001.

Covers: the freeze records a tree digest, per-file manifest and versions; the
freeze round-trips so the exact bytes can be restored; verify_freeze detects and
attributes a single-byte drift; an unmodified tree verifies clean; restore never
writes into the live tree; and the D-001 Git deviation is recorded explicitly.
"""

from runtime.source_freeze import (
    D001_DEVIATION_ADR,
    FREEZE_SCHEMA,
    SourceFreezeError,
    freeze_source,
    read_freeze,
    restore_from_freeze,
    verify_freeze,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tiny_repo(tmp_path: Path) -> Path:
    """A miniature repository with its own freeze artifacts."""
    root = tmp_path / "repo"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "b.md").write_text("plan\n", encoding="utf-8")
    (root / "extension").mkdir(parents=True)
    (root / "extension" / "package.json").write_text(
        json.dumps({"name": "tiny", "version": "0.9.0"}), encoding="utf-8"
    )
    # Build output must never enter the freeze.
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("noise\n", encoding="utf-8")
    return root


def test_freeze_records_identity_manifest_and_versions(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    receipt = freeze_source(root, freeze_id="tiny-001")
    body = read_freeze(root)
    assert body["schema_version"] == FREEZE_SCHEMA
    assert receipt.tree_sha256 == body["tree_sha256"]
    assert body["file_count"] == 3
    assert body["byte_count"] == sum(row["bytes"] for row in body["files"])
    for row in body["files"]:
        assert row["path"] and row["sha256"] and row["bytes"] > 0
    versions = body["versions"]
    assert versions["extension_package"]["version"] == "0.9.0"
    assert versions["python"]
    assert versions["platform"]


def test_freeze_excludes_vendored_and_generated_content(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    body = freeze_source(root, freeze_id="tiny-002")
    paths = {row["path"] for row in body.receipt["files"]}
    assert "node_modules/junk.js" not in paths
    assert "runtime/a.py" in paths and "docs/b.md" in paths


def test_d001_deviation_is_recorded_explicitly(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    body = freeze_source(root, freeze_id="tiny-003")
    adr = body.receipt["architecture_decision_record"]
    assert adr["adr_id"] == D001_DEVIATION_ADR["adr_id"]
    assert adr["locked_decision"] == "D-001"
    assert adr["status"] == "owner-deferred-git"
    assert adr["supersedes"] == "ADR-BASE-001-001"
    assert adr["git_acceptance"]["state"] == "deferred_by_owner"
    assert adr["git_acceptance"]["satisfied"] is False
    assert adr["git_acceptance"]["starting_commit"] is None
    assert len(adr["git_acceptance"]["requirements"]) == 3
    assert "equivalence" not in adr
    assert len(adr["preservation_controls"]) == 3
    assert adr["consequence"] and adr["revisit_when"]


def test_freeze_round_trips_and_restores_byte_exact(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-004")
    target = tmp_path / "restored"
    report = restore_from_freeze(root, target)
    assert report["restored"] == 3
    assert report["byte_exact"] is True
    assert (target / "runtime" / "a.py").read_bytes() == (root / "runtime" / "a.py").read_bytes()
    assert (target / "docs" / "b.md").read_bytes() == (root / "docs" / "b.md").read_bytes()
    # Vendored content stays out of the restore.
    assert not (target / "node_modules").exists()


def test_restore_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-005")
    first = tmp_path / "r1"
    second = tmp_path / "r2"
    restore_from_freeze(root, first)
    restore_from_freeze(root, second)
    for path in sorted(first.rglob("*")):
        if path.is_file():
            mirror = second / path.relative_to(first)
            assert mirror.read_bytes() == path.read_bytes(), path


def test_freeze_archive_is_reproducible(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-006")
    archive = root / "registry/source-freeze/authored-tree.zip"
    first = archive.read_bytes()
    freeze_source(root, freeze_id="tiny-006")
    assert archive.read_bytes() == first, "archive must be byte-reproducible"


def test_verify_reports_clean_for_an_unmodified_tree(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-007")
    report = verify_freeze(root)
    assert report["valid"] is True
    assert report["drift_count"] == 0
    assert report["changed"] == [] and report["missing"] == [] and report["added"] == []


def test_verify_detects_and_attributes_a_single_byte_drift(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-008")
    (root / "runtime" / "a.py").write_text("A = 2\n", encoding="utf-8")
    report = verify_freeze(root)
    assert report["valid"] is False
    assert report["drift_count"] == 1
    assert report["changed"] == ["runtime/a.py"]


def test_verify_detects_added_and_missing_files(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-009")
    (root / "docs" / "b.md").unlink()
    (root / "docs" / "c.md").write_text("new\n", encoding="utf-8")
    report = verify_freeze(root)
    assert report["valid"] is False
    assert report["missing"] == ["docs/b.md"]
    assert report["added"] == ["docs/c.md"]


def test_restore_refuses_to_write_inside_the_live_repository(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-010")
    with pytest.raises(SourceFreezeError, match="must not be inside the live repository"):
        restore_from_freeze(root, root / "runtime")
    with pytest.raises(SourceFreezeError, match="must not be inside the live repository"):
        restore_from_freeze(root, root)


def test_tampered_archive_fails_closed(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-011")
    archive = root / "registry/source-freeze/authored-tree.zip"
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(SourceFreezeError, match="digest does not match"):
        restore_from_freeze(root, tmp_path / "out")


def test_tampered_receipt_fails_closed(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    freeze_source(root, freeze_id="tiny-012")
    receipt_path = root / "registry/source_freeze.json"
    body = json.loads(receipt_path.read_text(encoding="utf-8"))
    body["tree_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    with pytest.raises(SourceFreezeError, match="receipt digest is invalid"):
        read_freeze(root)

def test_current_campaign_freeze_preserves_existing_freeze_and_exact_source_bytes(tmp_path):
    import zipfile
    root = _tiny_repo(tmp_path)
    old = freeze_source(root, freeze_id="legacy-reference")
    legacy_receipt = (root / "registry/source_freeze.json").read_bytes()
    legacy_archive = (root / old.receipt["archive"]["path"]).read_bytes()
    original_source_bytes = (root / "runtime/a.py").read_bytes()
    current = freeze_source(root, freeze_id="fresh-campaign", current_campaign=True)
    assert current.receipt["receipt_path"].startswith("registry/source-freeze/current-campaign/")
    assert (root / "registry/source_freeze.json").read_bytes() == legacy_receipt
    assert (root / old.receipt["archive"]["path"]).read_bytes() == legacy_archive
    assert read_freeze(root, relative=Path(current.receipt["receipt_path"]))["freeze_id"] == "fresh-campaign"
    with zipfile.ZipFile(root / current.receipt["archive"]["path"]) as bundle:
        assert bundle.read("runtime/a.py") == original_source_bytes
    repeat = freeze_source(root, freeze_id="fresh-campaign", current_campaign=True)
    assert repeat.receipt == current.receipt
    (root / "runtime/a.py").write_text("A = 2\n")
    next_freeze = freeze_source(root, freeze_id="fresh-campaign", current_campaign=True)
    assert next_freeze.tree_sha256 != current.tree_sha256
    assert (root / current.receipt["archive"]["path"]).is_file()
    assert next_freeze.receipt["architecture_decision_record"]["git_acceptance"]["satisfied"] is False


def test_changed_source_during_capture_does_not_publish_current_receipt(tmp_path, monkeypatch):
    root = _tiny_repo(tmp_path)
    original = Path.read_bytes
    reads = 0

    def changing(path):
        nonlocal reads
        data = original(path)
        if path == root / "runtime/a.py":
            reads += 1
            if reads == 2:
                return data + b"changed during capture"
        return data

    monkeypatch.setattr(Path, "read_bytes", changing)
    with pytest.raises(SourceFreezeError, match="source changed during archive capture"):
        freeze_source(root, freeze_id="fresh-campaign", current_campaign=True)
    assert not list((root / "registry/source-freeze/current-campaign").rglob("receipt-*.json"))


def test_current_capture_verification_and_restore_use_selected_receipt(tmp_path):
    root = _tiny_repo(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nname = "pacify-x"\nversion = "1.2.3"\n', encoding="utf-8")
    current = freeze_source(root, freeze_id="fresh-only", current_campaign=True)
    relative = Path(current.receipt["receipt_path"])
    assert not (root / "registry/source_freeze.json").exists()
    assert current.receipt["versions"]["distribution_package"] == {"name": "pacify-x", "version": "1.2.3"}
    assert verify_freeze(root, relative=relative)["valid"] is True
    original = (root / "runtime/a.py").read_bytes()
    (root / "runtime/a.py").write_bytes(b"changed source")
    assert verify_freeze(root, relative=relative)["changed"] == ["runtime/a.py"]
    destination = tmp_path / "restored-current"
    restored = restore_from_freeze(root, destination, relative=relative)
    assert restored["byte_exact"] is True
    assert (destination / "runtime/a.py").read_bytes() == original


def test_restore_checks_every_member_before_writing_any_destination(tmp_path):
    import hashlib
    import zipfile
    from runtime.source_freeze import _digest

    root = _tiny_repo(tmp_path)
    capture = freeze_source(root, freeze_id="recovery-preflight", current_campaign=True)
    receipt = capture.receipt
    archive = root / receipt["archive"]["path"]
    with zipfile.ZipFile(archive) as bundle:
        members = [(name, bundle.read(name)) for name in bundle.namelist()]
    with zipfile.ZipFile(archive, "w") as bundle:
        for index, (name, data) in enumerate(members):
            bundle.writestr(name, data + b"corrupt" if index == len(members) - 1 else data)
    receipt["archive"]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = _digest(receipt)
    relative = Path(receipt["receipt_path"])
    (root / relative).write_text(json.dumps(receipt), encoding="utf-8")
    destination = tmp_path / "safe-output"
    with pytest.raises(SourceFreezeError):
        restore_from_freeze(root, destination, relative=relative)
    assert not destination.exists(), "failed recovery must not publish a partially restored tree"
