"""Recoverably archive superseded project-map snapshots.

Dry-run is the default.  Apply mode writes and verifies a deterministic ZIP
before reclaiming only the exact archived snapshot directories.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import zipfile


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    value = path.lstat()
    return path.is_symlink() or bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def plan(root: Path, *, keep_latest: int = 2) -> dict[str, object]:
    root = root.resolve(strict=True)
    history = (root / ".engineering-bootstrap/project-map-history").resolve(strict=True)
    if history.parent != (root / ".engineering-bootstrap").resolve(strict=True):
        raise ValueError("project-map history is outside the bounded PX root")
    if keep_latest < 1 or keep_latest > 20:
        raise ValueError("keep_latest must be between 1 and 20")
    snapshots = sorted(path for path in history.iterdir() if path.is_dir())
    if any(_is_reparse(path) for path in snapshots):
        raise ValueError("project-map history contains a reparse-point snapshot")
    selected = snapshots[:-keep_latest] if len(snapshots) > keep_latest else []
    files: list[dict[str, object]] = []
    for snapshot in selected:
        if snapshot.resolve().parent != history:
            raise ValueError("project-map snapshot escaped the history root")
        for path in sorted(snapshot.rglob("*")):
            if _is_reparse(path):
                raise ValueError("project-map history contains a reparse point")
            if path.is_file():
                files.append(
                    {
                        "path": path.relative_to(history).as_posix(),
                        "sha256": _sha256(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
    manifest = {
        "schema_version": "px.project-map-history-archive-manifest/1.0",
        "history_root": ".engineering-bootstrap/project-map-history",
        "retained_live_snapshots": [path.name for path in snapshots[-keep_latest:]],
        "archived_snapshots": [path.name for path in selected],
        "file_count": len(files),
        "size_bytes": sum(int(row["size_bytes"]) for row in files),
        "files": files,
    }
    manifest_sha256 = hashlib.sha256(_canonical(manifest)).hexdigest()
    return {
        "valid": True,
        "apply": False,
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
        "selected_count": len(selected),
        "selected_paths": [path.as_posix() for path in selected],
    }


def _write_archive(history: Path, target: Path, manifest: dict[str, object]) -> None:
    temporary = target.with_suffix(".zip.prepared")
    if temporary.exists():
        raise ValueError("prepared project-map archive already exists")
    with zipfile.ZipFile(
        temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        manifest_info = zipfile.ZipInfo("MANIFEST.json", FIXED_ZIP_TIME)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(manifest_info, _canonical(manifest) + b"\n")
        for row in manifest["files"]:
            source = history / str(row["path"])
            info = zipfile.ZipInfo(str(row["path"]), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())
    os.replace(temporary, target)


def _verify_archive(path: Path, manifest: dict[str, object]) -> None:
    expected = {str(row["path"]): row for row in manifest["files"]}
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise ValueError("project-map archive CRC verification failed")
        names = [name for name in archive.namelist() if name != "MANIFEST.json"]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("project-map archive membership verification failed")
        stored_manifest = json.loads(archive.read("MANIFEST.json"))
        if stored_manifest != manifest:
            raise ValueError("project-map archive manifest verification failed")
        for name, row in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != row["sha256"]:
                raise ValueError(f"project-map archive member hash mismatch: {name}")


def apply(root: Path, *, keep_latest: int = 2) -> dict[str, object]:
    root = root.resolve(strict=True)
    decision = plan(root, keep_latest=keep_latest)
    manifest = decision["manifest"]
    if not manifest["archived_snapshots"]:
        return {**decision, "apply": True, "changed": False}
    history = (root / str(manifest["history_root"])).resolve(strict=True)
    archive_root = root / ".engineering-bootstrap/project-map-history-archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    first = manifest["archived_snapshots"][0]
    last = manifest["archived_snapshots"][-1]
    target = archive_root / (
        f"project-map-history-{first}-{last}-{decision['manifest_sha256'][:16]}.zip"
    )
    if target.exists():
        _verify_archive(target, manifest)
    else:
        _write_archive(history, target, manifest)
        _verify_archive(target, manifest)
    for name in manifest["archived_snapshots"]:
        snapshot = (history / str(name)).resolve(strict=True)
        if snapshot.parent != history or _is_reparse(snapshot):
            raise ValueError("project-map archive reclamation target is unsafe")
    for name in manifest["archived_snapshots"]:
        shutil.rmtree(history / str(name))
    archive_sha256 = _sha256(target)
    receipt = {
        "schema_version": "px.project-map-history-archive-receipt/1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "archive": target.relative_to(root).as_posix(),
        "archive_sha256": archive_sha256,
        "manifest_sha256": decision["manifest_sha256"],
        "archived_snapshots": manifest["archived_snapshots"],
        "retained_live_snapshots": manifest["retained_live_snapshots"],
        "file_count": manifest["file_count"],
        "source_size_bytes": manifest["size_bytes"],
        "archive_size_bytes": target.stat().st_size,
        "reclaimed_bytes": int(manifest["size_bytes"]) - target.stat().st_size,
        "recovery": "Verify archive_sha256, then extract below .engineering-bootstrap/project-map-history.",
        "hard_delete_without_archive": False,
    }
    receipt_path = (
        root
        / ".engineering-bootstrap/cleanup-receipts"
        / f"project-map-history-{decision['manifest_sha256'][:16]}.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    prepared = receipt_path.with_suffix(".json.prepared")
    prepared.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.replace(prepared, receipt_path)
    return {
        **decision,
        "apply": True,
        "changed": True,
        "archive": target.as_posix(),
        "archive_sha256": archive_sha256,
        "archive_size_bytes": target.stat().st_size,
        "reclaimed_bytes": receipt["reclaimed_bytes"],
        "receipt": receipt_path.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--keep-latest", type=int, default=2)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        apply(args.root, keep_latest=args.keep_latest)
        if args.apply
        else plan(args.root, keep_latest=args.keep_latest)
    )
    bounded = {key: value for key, value in result.items() if key != "manifest"}
    print(json.dumps(bounded, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
