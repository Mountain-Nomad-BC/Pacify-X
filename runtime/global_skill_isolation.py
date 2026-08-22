"""Preview-first, recoverable isolation of Codex user-global agent skills."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .file_lock import FileLock
from .native_skills import copy_verified, inventory_tree, tree_hash


SCHEMA = "px.global-skill-isolation/1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(prepared, path)


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_bytes(payload)
    os.replace(prepared, path)


def _installer_manifest_path(live: Path) -> Path:
    return live.parent / ".skill-lock.json"


def _isolate_installer_manifest(
    control: Path,
    live: Path,
    operation_id: str,
) -> dict[str, object]:
    """Retain installer intent so an updater cannot repopulate an isolated tree."""
    manifest = _installer_manifest_path(live)
    if not manifest.is_file():
        return {"status": "absent", "source": manifest.as_posix()}
    original = manifest.read_bytes()
    try:
        parsed = json.loads(original)
    except json.JSONDecodeError as error:
        raise ValueError("global skill installer manifest is invalid JSON") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("skills", {}), dict):
        raise ValueError("global skill installer manifest contract is invalid")
    skills = dict(parsed.get("skills", {}))
    if not skills:
        return {
            "status": "already-empty",
            "source": manifest.as_posix(),
            "skill_count": 0,
        }
    custody = control / "installer-metadata" / f"{operation_id}.skill-lock.json"
    custody.parent.mkdir(parents=True, exist_ok=True)
    if custody.exists() and custody.read_bytes() != original:
        raise RuntimeError("global skill installer custody already exists with different bytes")
    if not custody.exists():
        prepared = custody.with_name(f".{custody.name}.{uuid4().hex}.prepared")
        prepared.write_bytes(original)
        os.replace(prepared, custody)
    digest = hashlib.sha256(original).hexdigest()
    if hashlib.sha256(custody.read_bytes()).hexdigest() != digest:
        raise RuntimeError("global skill installer custody differs from the live manifest")
    _write_json(
        manifest,
        {
            "version": parsed.get("version", 3),
            "skills": {},
            "dismissed": parsed.get("dismissed", {}),
        },
    )
    replacement = json.loads(manifest.read_text(encoding="utf-8"))
    if replacement.get("skills") != {}:
        raise RuntimeError("global skill installer manifest was not neutralized")
    return {
        "status": "isolated",
        "source": manifest.as_posix(),
        "custody": custody.as_posix(),
        "sha256": digest,
        "skill_count": len(skills),
        "retention": "permanent; exact original bytes retained for explicit restore",
    }


def _restore_installer_manifest(journal: dict[str, Any], live: Path) -> dict[str, object]:
    records = [
        *(row.get("installer_manifest", {}) for row in reversed(journal.get("reconciliations", ())) if isinstance(row, dict)),
        journal.get("installer_manifest", {}),
    ]
    retained = next(
        (
            row
            for row in records
            if isinstance(row, dict)
            and row.get("status") == "isolated"
            and row.get("custody")
        ),
        None,
    )
    if retained is None:
        return {"status": "no-retained-installer-manifest"}
    custody = Path(str(retained["custody"])).resolve()
    if not custody.is_file():
        raise RuntimeError("retained global skill installer manifest is absent")
    original = custody.read_bytes()
    if hashlib.sha256(original).hexdigest() != retained.get("sha256"):
        raise RuntimeError("retained global skill installer manifest hash changed")
    manifest = _installer_manifest_path(live)
    if manifest.exists():
        try:
            current = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError("current global skill installer manifest is not replaceable") from error
        if not isinstance(current, dict) or current.get("skills") != {}:
            raise RuntimeError("current global skill installer manifest contains live skill entries")
    _write_bytes(manifest, original)
    return {
        "status": "restored",
        "source": manifest.as_posix(),
        "custody": custody.as_posix(),
        "sha256": retained["sha256"],
    }


def _snapshot(source: Path, identity: str) -> dict[str, Any]:
    records = inventory_tree(source)
    return {
        "schema_version": "px.global-skill-tree-snapshot/1.0",
        "snapshot_id": identity,
        "source": source.resolve().as_posix(),
        "file_count": len(records),
        "size_bytes": sum(int(row["size_bytes"]) for row in records),
        "tree_sha256": tree_hash(records),
        "files": records,
    }


def _default_paths(
    root: Path,
    source: Path | None,
    relocation_root: Path | None,
) -> tuple[Path, Path, Path]:
    project = root.resolve()
    live = (source or (Path.home() / ".agents" / "skills")).resolve()
    relocation = (relocation_root or (Path.home() / ".px_canonical_skills")).resolve()
    control = project / ".px" / "global-skill-isolation"
    if live == relocation or live in relocation.parents or relocation in live.parents:
        raise ValueError("global skill source and relocation custody must be disjoint")
    return live, relocation, control


def _matching_permanent_backup(root: Path, source: Path, expected_hash: str) -> Path | None:
    custody = root.resolve() / ".px" / "preserved-skills" / "initial"
    manifest_path = custody / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for row in manifest.get("sources", ()):
        if not isinstance(row, dict) or row.get("tree_sha256") != expected_hash:
            continue
        original = Path(str(row.get("original_path", "")))
        if original and original.resolve() != source:
            continue
        candidate = custody / str(row.get("relative_backup", ""))
        if candidate.is_dir() and tree_hash(inventory_tree(candidate)) == expected_hash:
            return candidate
    return None


def _prior_permanent_backups(root: Path, source: Path) -> list[dict[str, object]]:
    custody = root.resolve() / ".px" / "preserved-skills" / "initial"
    manifest_path = custody / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for row in manifest.get("sources", ()):
        if not isinstance(row, dict):
            continue
        original = Path(str(row.get("original_path", "")))
        if original and original.resolve() == source:
            rows.append(
                {
                    "id": row.get("id"),
                    "path": (custody / str(row.get("relative_backup", ""))).as_posix(),
                    "tree_sha256": row.get("tree_sha256"),
                    "retained": True,
                }
            )
    return rows


def _verified_transaction_backup(journal: dict[str, Any], expected_hash: str) -> Path | None:
    candidates = [
        (journal.get("permanent_backup"), journal.get("tree_sha256")),
        *(
            (row.get("permanent_backup"), row.get("tree_sha256"))
            for row in journal.get("reconciliations", ())
            if isinstance(row, dict)
        ),
    ]
    for value, declared_hash in candidates:
        if not value or declared_hash != expected_hash:
            continue
        candidate = Path(str(value)).resolve()
        if candidate.is_dir() and tree_hash(inventory_tree(candidate)) == expected_hash:
            return candidate
    return None


def _reconciliation_identity(
    journal: dict[str, Any], relocation: Path, expected_hash: str
) -> tuple[int, str, Path]:
    generation = len(journal.get("reconciliations", ())) + 1
    while True:
        operation_id = f"global-skills-reconcile-{generation:03d}-{expected_hash[:16]}"
        destination = relocation / operation_id
        if not destination.exists():
            return generation, operation_id, destination
        generation += 1


def _reconcile_reappeared_skills(
    project: Path,
    live: Path,
    relocation: Path,
    control: Path,
    journal_path: Path,
    journal: dict[str, Any],
) -> dict[str, Any]:
    """Move a re-materialized host tree into a new recoverable generation."""
    pending = journal.get("pending_reconciliation")
    if not isinstance(pending, dict):
        if not live.is_dir() or not any(live.iterdir()):
            return {"valid": True, "mode": "already-committed", "journal": journal}
        first = _snapshot(live, "reconcile-a")
        second = _snapshot(live, "reconcile-b")
        if first["files"] != second["files"]:
            raise RuntimeError("reappeared global skill tree changed between required snapshots")
        expected = str(first["tree_sha256"])
        generation, operation_id, destination = _reconciliation_identity(
            journal, relocation, expected
        )
        prefix = f"reconcile-{generation:03d}"
        _write_json(control / f"{prefix}-snapshot-a.json", first)
        _write_json(control / f"{prefix}-snapshot-b.json", second)
        backup = _verified_transaction_backup(journal, expected)
        if backup is None:
            backup = _matching_permanent_backup(project, live, expected)
        if backup is None:
            backup = (
                project
                / ".px"
                / "preserved-skills"
                / "host-isolation"
                / operation_id
                / "verified-copy"
            )
            receipt = copy_verified(live, backup)
            if receipt["tree_sha256"] != expected:
                raise RuntimeError("reappeared skill backup differs from source snapshots")
        pending = {
            "generation": generation,
            "operation_id": operation_id,
            "state": "snapshots-and-backup-verified",
            "created_at": _now(),
            "source": live.as_posix(),
            "destination": destination.as_posix(),
            "permanent_backup": backup.as_posix(),
            "tree_sha256": expected,
            "file_count": first["file_count"],
            "size_bytes": first["size_bytes"],
            "snapshot_a": f"{prefix}-snapshot-a.json",
            "snapshot_b": f"{prefix}-snapshot-b.json",
            "snapshot_pre_move": f"{prefix}-snapshot-pre-move.json",
            "retention": "permanent; never auto-purge",
        }
        journal["pending_reconciliation"] = pending
        _write_json(journal_path, journal)
    expected = str(pending["tree_sha256"])
    destination = Path(str(pending["destination"])).resolve()
    relocation.mkdir(parents=True, exist_ok=True)
    if pending["state"] == "snapshots-and-backup-verified":
        immediate = _snapshot(live, "reconcile-pre-move")
        _write_json(control / str(pending["snapshot_pre_move"]), immediate)
        if immediate["tree_sha256"] != expected:
            pending["state"] = "blocked-source-drift"
            _write_json(journal_path, journal)
            raise RuntimeError("reappeared skill tree changed immediately before relocation")
        pending["pre_move_tree_sha256"] = immediate["tree_sha256"]
        pending["state"] = "pre-move-verified"
        _write_json(journal_path, journal)
    if pending["state"] == "pre-move-verified":
        if destination.exists():
            raise FileExistsError(f"reconciliation custody already exists: {destination}")
        os.replace(live, destination)
        pending["state"] = "source-relocated"
        _write_json(journal_path, journal)
    if pending["state"] == "source-relocated":
        pending["installer_manifest"] = _isolate_installer_manifest(
            control, live, str(pending["operation_id"])
        )
        pending["state"] = "installer-manifest-isolated"
        _write_json(journal_path, journal)
    if pending["state"] == "installer-manifest-isolated":
        if not destination.is_dir() or tree_hash(inventory_tree(destination)) != expected:
            raise RuntimeError("reconciled global skill custody differs from source")
        if live.exists() and (not live.is_dir() or any(live.iterdir())):
            raise RuntimeError("cannot recreate empty host facade over new live data")
        live.mkdir(parents=True, exist_ok=True)
        pending["state"] = "committed"
        pending["committed_at"] = _now()
        journal.setdefault("reconciliations", []).append(pending)
        journal.pop("pending_reconciliation", None)
        journal["last_reconciled_at"] = pending["committed_at"]
        _write_json(journal_path, journal)
    return {
        "schema_version": SCHEMA,
        "valid": True,
        "mode": "reappeared-source-reconciled",
        "source_host_visible_skill_count": len(list(live.rglob("SKILL.md"))),
        "reconciliation": pending,
        "journal": journal,
    }


def preview_global_skill_isolation(
    root: Path,
    *,
    source: Path | None = None,
    relocation_root: Path | None = None,
) -> dict[str, Any]:
    """Perform two read-only snapshots and describe the exact proposed effects."""
    live, relocation, control = _default_paths(root, source, relocation_root)
    journal_path = control / "journal.json"
    if journal_path.is_file():
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("schema_version") != SCHEMA:
            return {
                "schema_version": SCHEMA,
                "valid": False,
                "mode": "existing-transaction",
                "apply": False,
                "journal": journal,
                "approval_required": True,
            }
        pending = journal.get("pending_reconciliation")
        if journal.get("state") == "committed" and (
            isinstance(pending, dict)
            or (live.is_dir() and any(live.iterdir()))
        ):
            if isinstance(pending, dict):
                return {
                    "schema_version": SCHEMA,
                    "valid": False,
                    "mode": "reconciliation-incomplete",
                    "apply": False,
                    "journal": journal,
                    "approval_required": True,
                }
            first = _snapshot(live, "reconcile-preview-a")
            second = _snapshot(live, "reconcile-preview-b")
            stable = first["files"] == second["files"]
            generation, operation_id, destination = _reconciliation_identity(
                journal, relocation, str(first["tree_sha256"])
            )
            backup = _verified_transaction_backup(journal, str(first["tree_sha256"]))
            return {
                "schema_version": SCHEMA,
                "valid": stable and not destination.exists(),
                "mode": "reappeared-source-preview",
                "apply": False,
                "approval_required": True,
                "source": live.as_posix(),
                "destination": destination.as_posix(),
                "generation": generation,
                "operation_id": operation_id,
                "snapshots_match": stable,
                "snapshot": {
                    "file_count": first["file_count"],
                    "size_bytes": first["size_bytes"],
                    "tree_sha256": first["tree_sha256"],
                },
                "permanent_backup": {
                    "reuse_verified_existing": backup is not None,
                    "path": backup.as_posix() if backup else None,
                    "retention": "permanent; never auto-purge",
                },
                "journal": journal,
                "effects_if_applied": [
                    "retain every earlier original and reconciliation generation",
                    "verify two matching snapshots and an immediate pre-move snapshot",
                    "verify or create a permanent byte-identical backup",
                    "move only the reappeared host-visible tree into a new recoverable generation",
                    "retain the exact installer manifest and clear its active skill entries",
                    "recreate the empty host discovery facade",
                ],
            }
        return {
            "schema_version": SCHEMA,
            "valid": journal.get("schema_version") == SCHEMA,
            "mode": "existing-transaction",
            "apply": False,
            "journal": journal,
            "approval_required": journal.get("state") not in {"committed", "restored"},
        }
    if not live.is_dir():
        return {
            "schema_version": SCHEMA,
            "valid": True,
            "mode": "nothing-host-visible",
            "apply": False,
            "source": live.as_posix(),
            "approval_required": False,
        }
    first = _snapshot(live, "preview-a")
    second = _snapshot(live, "preview-b")
    stable = first["files"] == second["files"]
    backup = (
        _matching_permanent_backup(root, live, str(first["tree_sha256"]))
        if stable
        else None
    )
    operation_id = f"global-skills-{str(first['tree_sha256'])[:16]}"
    destination = relocation / operation_id
    new_backup = (
        root.resolve()
        / ".px"
        / "preserved-skills"
        / "host-isolation"
        / operation_id
        / "verified-copy"
    )
    return {
        "schema_version": SCHEMA,
        "valid": stable and not destination.exists(),
        "mode": "preview",
        "apply": False,
        "approval_required": True,
        "source": live.as_posix(),
        "destination": destination.as_posix(),
        "journal": (control / "journal.json").as_posix(),
        "snapshots_match": stable,
        "snapshot": {
            "file_count": first["file_count"],
            "size_bytes": first["size_bytes"],
            "tree_sha256": first["tree_sha256"],
        },
        "permanent_backup": {
            "reuse_verified_existing": backup is not None,
            "path": backup.as_posix() if backup else new_backup.as_posix(),
            "retention": "permanent; never auto-purge",
        },
        "prior_permanent_backups": _prior_permanent_backups(root, live),
        "effects_if_applied": [
            "write two matching full-tree snapshot records and a phase journal",
            "verify or create a byte-identical permanent PX backup",
            "take an immediate pre-move full-tree equality snapshot",
            "move the user-global skills tree into recoverable .px_canonical_skills custody",
            "retain the exact installer manifest and clear its active skill entries",
            "recreate an empty .agents/skills directory so Codex no longer enumerates the moved bodies",
        ],
        "rollback": "explicit restore verifies custody and moves the original tree back only when the live source is absent or empty",
    }


def isolate_global_skills(
    root: Path,
    *,
    source: Path | None = None,
    relocation_root: Path | None = None,
    apply: bool = False,
    _stop_after_state: str | None = None,
) -> dict[str, Any]:
    """Execute the previewed move only under explicit ``apply=True`` authority."""
    if not apply:
        return preview_global_skill_isolation(
            root, source=source, relocation_root=relocation_root
        )
    project = root.resolve()
    live, relocation, control = _default_paths(project, source, relocation_root)
    journal_path = control / "journal.json"
    control.mkdir(parents=True, exist_ok=True)
    with FileLock(control / ".isolation.lock"):
        if journal_path.is_file():
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal.get("schema_version") != SCHEMA:
                raise ValueError("unsupported global skill isolation journal")
            if journal.get("state") == "committed":
                destination = Path(str(journal["destination"]))
                expected = str(journal["tree_sha256"])
                if not destination.is_dir() or tree_hash(inventory_tree(destination)) != expected:
                    raise RuntimeError("committed relocated global skill custody is invalid")
                if isinstance(journal.get("pending_reconciliation"), dict) or (
                    live.is_dir() and any(live.iterdir())
                ):
                    return _reconcile_reappeared_skills(
                        project, live, relocation, control, journal_path, journal
                    )
                if not live.is_dir():
                    live.mkdir(parents=True, exist_ok=True)
                return {"valid": True, "mode": "already-committed", "journal": journal}
        else:
            if not live.is_dir():
                raise FileNotFoundError(f"global skill source is absent: {live}")
            first = _snapshot(live, "global-a")
            second = _snapshot(live, "global-b")
            _write_json(control / "snapshot-a.json", first)
            _write_json(control / "snapshot-b.json", second)
            if first["files"] != second["files"]:
                raise RuntimeError("global skill tree changed between required snapshots")
            operation_id = f"global-skills-{str(first['tree_sha256'])[:16]}"
            destination = relocation / operation_id
            if destination.exists():
                raise FileExistsError(f"relocation custody already exists: {destination}")
            backup = _matching_permanent_backup(
                project, live, str(first["tree_sha256"])
            )
            if backup is None:
                backup = (
                    project
                    / ".px"
                    / "preserved-skills"
                    / "host-isolation"
                    / operation_id
                    / "verified-copy"
                )
                backup_receipt = copy_verified(live, backup)
                if backup_receipt["tree_sha256"] != first["tree_sha256"]:
                    raise RuntimeError("new permanent backup differs from source snapshots")
            journal = {
                "schema_version": SCHEMA,
                "state": "snapshots-and-backup-verified",
                "operation_id": operation_id,
                "created_at": _now(),
                "source": live.as_posix(),
                "destination": destination.as_posix(),
                "permanent_backup": backup.as_posix(),
                "tree_sha256": first["tree_sha256"],
                "file_count": first["file_count"],
                "size_bytes": first["size_bytes"],
                "snapshot_a": "snapshot-a.json",
                "snapshot_b": "snapshot-b.json",
                "pre_move_tree_sha256": None,
                "retention": "permanent; never auto-purge",
                "rollback": "explicit verified restore",
            }
            _write_json(journal_path, journal)
        expected = str(journal["tree_sha256"])
        destination = Path(str(journal["destination"])).resolve()
        relocation.mkdir(parents=True, exist_ok=True)
        if journal["state"] == "snapshots-and-backup-verified":
            immediate = _snapshot(live, "global-pre-move")
            _write_json(control / "snapshot-pre-move.json", immediate)
            if immediate["tree_sha256"] != expected:
                journal["state"] = "blocked-source-drift"
                _write_json(journal_path, journal)
                raise RuntimeError("global skill tree changed immediately before relocation")
            journal["pre_move_tree_sha256"] = immediate["tree_sha256"]
            journal["state"] = "pre-move-verified"
            _write_json(journal_path, journal)
        if journal["state"] == "pre-move-verified":
            os.replace(live, destination)
            journal["state"] = "source-relocated"
            _write_json(journal_path, journal)
            if _stop_after_state == "source-relocated":
                raise RuntimeError("injected isolation stop after source-relocated")
        if journal["state"] == "source-relocated":
            journal["installer_manifest"] = _isolate_installer_manifest(
                control, live, str(journal["operation_id"])
            )
            journal["state"] = "installer-manifest-isolated"
            _write_json(journal_path, journal)
        if journal["state"] == "installer-manifest-isolated":
            if tree_hash(inventory_tree(destination)) != expected:
                raise RuntimeError("relocated global skill tree differs from source")
            if live.exists():
                if not live.is_dir() or any(live.iterdir()):
                    raise RuntimeError("cannot create empty host facade root over live data")
            else:
                live.mkdir(parents=True)
            journal["state"] = "committed"
            journal["committed_at"] = _now()
            _write_json(journal_path, journal)
        return {
            "schema_version": SCHEMA,
            "valid": journal["state"] == "committed",
            "mode": "applied",
            "source_host_visible_skill_count": len(list(live.rglob("SKILL.md"))),
            "journal": journal,
        }


def restore_global_skills(
    root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Restore the exact relocated original; preview unless explicitly applied."""
    control = root.resolve() / ".px" / "global-skill-isolation"
    journal_path = control / "journal.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    source = Path(str(journal["source"])).resolve()
    destination = Path(str(journal["destination"])).resolve()
    expected = str(journal["tree_sha256"])
    if journal.get("state") != "committed":
        raise RuntimeError("global skill isolation is not committed")
    if not destination.is_dir() or tree_hash(inventory_tree(destination)) != expected:
        raise RuntimeError("relocated original failed restore verification")
    if source.exists() and (not source.is_dir() or any(source.iterdir())):
        raise RuntimeError("restore target must be absent or empty")
    preview = {
        "schema_version": SCHEMA,
        "valid": True,
        "apply": apply,
        "source": source.as_posix(),
        "relocated_original": destination.as_posix(),
        "tree_sha256": expected,
        "effect": "move the verified relocated original back to the global Codex discovery path and restore its exact retained installer manifest",
    }
    if not apply:
        return preview
    if source.is_dir():
        source.rmdir()
    source.parent.mkdir(parents=True, exist_ok=True)
    os.replace(destination, source)
    if tree_hash(inventory_tree(source)) != expected:
        raise RuntimeError("restored global skill tree failed equality verification")
    installer_manifest = _restore_installer_manifest(journal, source)
    journal["state"] = "restored"
    journal["restored_at"] = _now()
    journal["installer_manifest_restore"] = installer_manifest
    _write_json(journal_path, journal)
    return {**preview, "restored": True, "journal": journal}
