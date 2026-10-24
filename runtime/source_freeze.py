"""Content-addressed source freeze implementing punch card BASE-001.

BASE-001 asks for three things: prove a clean working tree, record commit/tree/
package versions, and create a rollback tag or worktree. The repository owner
declined Git at this stage, so this module provides file preservation while Git-specific acceptance
remains deferred:

* ``freeze_source`` records a content-addressed identity of the AUTHORED tree,
  a per-file manifest of path, byte length and sha256, and the extension,
  Python and platform versions.
* ``verify_freeze`` reports whether the live tree still matches that identity
  and names the exact files that drifted.
* ``restore_from_freeze`` reconstructs the exact bytes into an explicit target
  directory.

Campaign acceptance boundary
----------------------------
File manifests and retained bytes prove source identity and recovery. They do
not prove a clean Git checkout, a starting commit, or a Git rollback anchor.
Those Git-specific requirements are explicitly owner-deferred for the preserved
standalone campaign and remain unsatisfied until later Git reconciliation.
Historical receipts remain unchanged; new receipts record this distinction.

Restore never writes into the live tree unless an explicit target directory is
given, and even then it writes only into that directory. It does not overwrite
the repository in place.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.source_boundary import AUTHORED, authored_paths

FREEZE_SCHEMA = "px.source-freeze/1.0"
FREEZE_RELATIVE = Path("registry/source_freeze.json")
ARCHIVE_RELATIVE = Path("registry/source-freeze/authored-tree.zip")

# Keep literal Git acceptance separate from demonstrated file preservation.
D001_DEVIATION_ADR = {
    "adr_id": "ADR-BASE-001-002",
    "supersedes": "ADR-BASE-001-001",
    "locked_decision": "D-001",
    "title": "Preserve standalone source; defer Git-specific acceptance",
    "status": "owner-deferred-git",
    "deviation": (
        "The owner explicitly authorizes architecture work against the preserved "
        "standalone tree. Do not initialize, reconstruct, rewrite or modify Git "
        "history. Git-specific acceptance is deferred, not satisfied by equivalence."
    ),
    "git_acceptance": {
        "state": "deferred_by_owner",
        "satisfied": False,
        "starting_commit": None,
        "requirements": [
            "Clean real Git checkout proven",
            "Starting Git commit recorded",
            "Git rollback tag or worktree created",
        ],
    },
    "preservation_controls": [
        "Deterministic per-file manifest and content-addressed tree identity",
        "Retained source bytes and archive digest",
        "Byte-exact restore and explicit drift verification",
    ],
    "consequence": (
        "File preservation does not provide shared Git history, branch isolation "
        "or merge conflict detection. No Git-specific acceptance is unlocked."
    ),
    "revisit_when": (
        "After architecture work, integration, validation and certification, "
        "the owner reconciles the preserved tree with the Git repository."
    ),
}


class SourceFreezeError(ValueError):
    """Raised when a freeze operation is invalid or unsafe."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return _sha256_bytes(_canonical(value).encode("utf-8"))


@dataclass(frozen=True)
class FreezeReceipt:
    tree_sha256: str
    file_count: int
    byte_count: int
    receipt: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return dict(self.receipt)


def _manifest(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in paths:
        target = root / relative
        if not target.is_file():
            raise SourceFreezeError("authored source disappeared during capture")
        from .archive_io import reject_path_links

        reject_path_links(target)
        data = target.read_bytes()
        rows.append(
            {"path": relative, "bytes": len(data), "sha256": _sha256_bytes(data)}
        )
    rows.sort(key=lambda row: row["path"])
    return rows


def _versions(root: Path) -> dict[str, Any]:
    package: dict[str, Any] = {}
    package_path = root / "extension" / "package.json"
    if package_path.is_file():
        value = json.loads(package_path.read_text(encoding="utf-8"))
        package = {"name": value.get("name"), "version": value.get("version")}
    distribution: dict[str, Any] = {}
    project_path = root / "pyproject.toml"
    if project_path.is_file():
        project = tomllib.loads(project_path.read_text(encoding="utf-8")).get("project", {})
        distribution = {"name": project.get("name"), "version": project.get("version")}
    return {
        "distribution_package": distribution,
        "extension_package": package,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def freeze_source(root: Path, *, freeze_id: str, note: str = "", current_campaign: bool = False) -> FreezeReceipt:
    """Freeze the authored tree identity and retain its exact bytes."""
    root = Path(root).resolve(strict=True)
    paths = authored_paths(root)
    if not paths:
        raise SourceFreezeError("source freeze requires at least one authored file")
    rows = _manifest(root, paths)
    tree = hashlib.sha256()
    for row in rows:
        tree.update(row["path"].encode("utf-8"))
        tree.update(b"\0")
        tree.update(bytes.fromhex(row["sha256"]))
        tree.update(b"\0")
    total = sum(row["bytes"] for row in rows)

    # Retain exact bytes so the freeze is a real rollback anchor, not only an
    # integrity record. Entries are written in sorted path order with a fixed
    # timestamp so the archive is byte-reproducible.
    archive_relative = ARCHIVE_RELATIVE
    receipt_relative = FREEZE_RELATIVE
    if current_campaign:
        directory = Path("registry/source-freeze/current-campaign") / tree.hexdigest()
        archive_relative = directory / "authored-tree.zip"
        receipt_relative = directory / ("receipt-" + _sha256_bytes(freeze_id.encode("utf-8")) + ".json")
    archive_path = root / archive_relative
    from .archive_io import reject_path_links

    reject_path_links(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if current_campaign and archive_path.exists():
        with zipfile.ZipFile(archive_path) as bundle:
            if bundle.namelist() != [row["path"] for row in rows]:
                raise SourceFreezeError("current source archive member inventory differs")
            for row in rows:
                if bundle.getinfo(row["path"]).file_size != row["bytes"]:
                    raise SourceFreezeError("current source archive member byte count differs")
                data = bundle.read(row["path"])
                if len(data) != row["bytes"] or _sha256_bytes(data) != row["sha256"]:
                    raise SourceFreezeError("current source archive bytes differ")
    else:
        prepared_archive = archive_path.with_name(archive_path.name + ".new")
        reject_path_links(prepared_archive)
        with zipfile.ZipFile(prepared_archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for row in rows:
                data = (root / row["path"]).read_bytes()
                if len(data) != row["bytes"] or _sha256_bytes(data) != row["sha256"]:
                    raise SourceFreezeError("source changed during archive capture")
                info = zipfile.ZipInfo(row["path"], date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, data)
        if _manifest(root, authored_paths(root)) != rows:
            raise SourceFreezeError("source inventory changed during freeze")
        prepared_archive.replace(archive_path)

    versions = _versions(root)
    if _manifest(root, authored_paths(root)) != rows:
        raise SourceFreezeError("source inventory changed during freeze")

    receipt: dict[str, Any] = {
        "schema_version": FREEZE_SCHEMA,
        "freeze_id": freeze_id,
        "note": note,
        "boundary": {
            "classification": AUTHORED,
            "authority": "runtime/source_boundary.py authored_paths",
        },
        "tree_sha256": tree.hexdigest(),
        "file_count": len(rows),
        "byte_count": total,
        "versions": versions,
        "archive": {
            "path": archive_relative.as_posix(),
            "sha256": _sha256_bytes(archive_path.read_bytes()),
            "byte_size": archive_path.stat().st_size,
        },
        "architecture_decision_record": D001_DEVIATION_ADR,
        "files": rows,
    }
    receipt["receipt_sha256"] = _digest(receipt)

    target = root / receipt_relative
    reject_path_links(target)
    if current_campaign:
        receipt["receipt_path"] = receipt_relative.as_posix()
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = _digest(receipt)
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing != receipt:
                raise SourceFreezeError("current content-addressed freeze receipt differs")
            return FreezeReceipt(tree.hexdigest(), len(rows), total, existing)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return FreezeReceipt(
        tree_sha256=receipt["tree_sha256"],
        file_count=len(rows),
        byte_count=total,
        receipt=receipt,
    )


def read_freeze(root: Path, *, relative: Path = FREEZE_RELATIVE) -> dict[str, Any]:
    from .archive_io import portable_member_name, reject_path_links

    relative = Path(portable_member_name(relative.as_posix(), allow_directory=False))
    target = Path(root).resolve(strict=True) / relative
    reject_path_links(target)
    if not target.is_file():
        raise SourceFreezeError("no source freeze has been published")
    receipt = json.loads(target.read_text(encoding="utf-8"))
    stored = str(receipt.get("receipt_sha256") or "")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if _digest(body) != stored:
        raise SourceFreezeError("source freeze receipt digest is invalid")
    return receipt


def verify_freeze(root: Path, *, relative: Path = FREEZE_RELATIVE) -> dict[str, Any]:
    """Compare the live authored tree against the frozen identity."""
    root = Path(root).resolve(strict=True)
    receipt = read_freeze(root, relative=relative)
    expected = {row["path"]: row for row in receipt.get("files", [])}
    actual_paths = authored_paths(root)
    actual = {path: _sha256_bytes((root / path).read_bytes()) for path in actual_paths}

    changed = sorted(
        path for path in expected.keys() & actual.keys() if expected[path]["sha256"] != actual[path]
    )
    missing = sorted(expected.keys() - actual.keys())
    added = sorted(actual.keys() - expected.keys())
    drift = changed or missing or added
    return {
        "valid": not drift,
        "frozen_tree_sha256": receipt["tree_sha256"],
        "frozen_file_count": receipt["file_count"],
        "changed": changed,
        "missing": missing,
        "added": added,
        "drift_count": len(changed) + len(missing) + len(added),
        "note": (
            "The live tree is byte-identical to the freeze."
            if not drift
            else "The live tree has drifted from the freeze."
        ),
    }


def restore_from_freeze(root: Path, target_directory: Path, *, relative: Path = FREEZE_RELATIVE) -> dict[str, Any]:
    """Reconstruct the exact frozen bytes into an explicit target directory.

    This never writes into the live repository. It extracts into
    ``target_directory`` and verifies every restored file against the manifest,
    so a corrupt or truncated archive fails closed instead of producing a
    plausible-looking tree.
    """
    root = Path(root).resolve(strict=True)
    receipt = read_freeze(root, relative=relative)
    from .archive_io import portable_member_name, reject_path_links

    archive = root / portable_member_name(str(receipt["archive"]["path"]), allow_directory=False)
    reject_path_links(archive)
    if not archive.is_file():
        raise SourceFreezeError("freeze archive is missing")
    if _sha256_bytes(archive.read_bytes()) != receipt["archive"]["sha256"]:
        raise SourceFreezeError("freeze archive digest does not match the receipt")
    reject_path_links(Path(target_directory).absolute())
    destination = Path(target_directory).resolve()
    if destination == root or root in destination.parents:
        raise SourceFreezeError("restore target must not be inside the live repository")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise SourceFreezeError("restore target must be an empty directory or absent")
    expected = {}
    for row in receipt.get("files", []):
        name = portable_member_name(row["path"], allow_directory=False)
        if name in expected:
            raise SourceFreezeError("duplicate source freeze manifest path")
        expected[name] = row
    restored = 0
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) != len(expected) or {info.filename for info in members} != set(expected):
            raise SourceFreezeError("archive member inventory differs from manifest")
        # Preflight every path and payload before publishing any recovery file.
        for info in members:
            name = portable_member_name(info.filename, allow_directory=False)
            target = destination / name
            reject_path_links(target)
            row = expected[name]
            data = bundle.read(info)
            if len(data) != row["bytes"] or _sha256_bytes(data) != row["sha256"]:
                raise SourceFreezeError(f"restored file does not match the freeze manifest: {name}")
        for info in members:
            target = destination / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(bundle.read(info))
            restored += 1
    return {
        "restored": restored,
        "target": destination.as_posix(),
        "tree_sha256": receipt["tree_sha256"],
        "byte_exact": True,
    }
