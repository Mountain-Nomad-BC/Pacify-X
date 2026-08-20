"""Authenticated, bounded, read-only lifecycle projection for lazy Studio catalogs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .skill_studio import _tree_attestation
from .studio_authority import StudioAuthorityStore
from .studio_models import digest


MAX_RECORD_BYTES = 1024 * 1024
MAX_REVISIONS = 1000
MAX_LIFECYCLE_ARTIFACTS = 24
LIFECYCLE_SCHEMA = "px.skill-lifecycle-transaction/1.0"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    stat = path.lstat()
    if not stat.st_size <= MAX_RECORD_BYTES or path.is_symlink() or not path.is_file():
        raise ValueError("Studio lifecycle record is not a bounded physical file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Studio lifecycle record is not an object")
    return value


def _verified(authority: StudioAuthorityStore, path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    return authority.verify_receipt(_json(path))


def _within(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def _file_sha(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("Studio lifecycle artifact target is not a physical file")
    return _sha(path)


def _verify_lifecycle_transaction(
    authority: StudioAuthorityStore,
    project_root: Path,
    relative_text: object,
    *,
    operation: str,
    skill_id: str,
    version: str,
    target_relative: str,
    tree_sha256: str,
) -> dict[str, Any]:
    if not isinstance(relative_text, str) or not relative_text:
        raise PermissionError("Authenticated lifecycle transaction is unavailable")
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != relative_text:
        raise ValueError("Studio lifecycle transaction path is invalid")
    journal_root = (
        project_root
        / ".engineering-bootstrap"
        / "studios"
        / "skills"
        / "lifecycle-transactions"
    ).resolve(strict=True)
    transaction = (project_root / relative).resolve(strict=True)
    if transaction.parent != journal_root or transaction.is_symlink() or not transaction.is_dir():
        raise PermissionError("Studio lifecycle transaction escapes custody")
    manifest = _verified(authority, transaction / "manifest.json")
    if not manifest:
        raise PermissionError("Studio lifecycle transaction authentication failed")
    if (
        manifest.get("schema_version") != LIFECYCLE_SCHEMA
        or manifest.get("transaction_id") != transaction.name
        or manifest.get("state") != "committed"
        or manifest.get("operation") != operation
        or manifest.get("skill_id") != skill_id
        or manifest.get("version") != version
    ):
        raise PermissionError("Studio lifecycle transaction binding changed")
    canonical = manifest.get("canonical")
    if (
        not isinstance(canonical, dict)
        or canonical.get("target_relative") != target_relative
        or canonical.get("after_tree_sha256") != tree_sha256
    ):
        raise PermissionError("Studio lifecycle canonical binding changed")
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or len(artifacts) > MAX_LIFECYCLE_ARTIFACTS
        or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise ValueError("Studio lifecycle artifact denominator is invalid")
    paths: set[str] = set()
    projection_hashes: dict[str, str | None] = {}
    for item in artifacts:
        path_text = str(item.get("path") or "")
        path = Path(path_text)
        if (
            not path_text
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != path_text
            or path_text in paths
        ):
            raise ValueError("Studio lifecycle artifact path is invalid")
        paths.add(path_text)
        expected = item.get("after_sha256")
        exists = item.get("after_exists") is True
        if exists != isinstance(expected, str):
            raise ValueError("Studio lifecycle artifact after-image is invalid")
        image_name = item.get("after_image")
        if exists:
            if not isinstance(image_name, str):
                raise ValueError("Studio lifecycle artifact image custody is invalid")
            image = transaction / image_name
            if _file_sha(image) != expected:
                raise PermissionError("Studio lifecycle after-image changed")
        elif image_name is not None or expected is not None:
            raise ValueError("Absent Studio lifecycle artifact has image custody")
        if _file_sha(project_root / path) != expected:
            raise PermissionError("Current Studio lifecycle projection differs from transaction")
        if item.get("role") == "projection":
            projection_hashes[path_text] = expected if isinstance(expected, str) else None
    return {"manifest": manifest, "projection_hashes": projection_hashes}


def project(root: Path, kind: str) -> dict[str, object]:
    project_root = root.resolve(strict=True)
    if kind not in {"agents", "workflows", "skills"}:
        raise ValueError("Studio catalog kind is invalid")
    base = project_root / ".engineering-bootstrap" / "studios" / kind
    rows: dict[str, dict[str, object]] = {}
    if not base.is_dir() or base.is_symlink():
        return {"schema_version": "px.studio-catalog-status/1.1", "kind": kind, "records": rows}
    try:
        authority = StudioAuthorityStore.open_existing(project_root)
    except Exception as error:
        return {
            "schema_version": "px.studio-catalog-status/1.1",
            "kind": kind,
            "records": rows,
            "verification_unavailable": type(error).__name__,
        }
    visited = 0
    stop = False
    for identity in sorted(base.iterdir(), key=lambda item: item.name):
        if stop:
            break
        revisions = identity / "revisions"
        if identity.is_symlink() or not revisions.is_dir() or revisions.is_symlink():
            continue
        for revision in sorted(revisions.iterdir(), key=lambda item: item.name):
            visited += 1
            if visited > MAX_REVISIONS:
                stop = True
                break
            if revision.is_symlink() or not revision.is_dir():
                continue
            record_path = revision / ("package-record.json" if kind == "skills" else "record.json")
            if not record_path.is_file() or record_path.is_symlink():
                continue
            relative = record_path.relative_to(project_root).as_posix()
            status = "candidate"
            authenticated = False
            reasons: list[str] = []
            lifecycle: dict[str, object] = {}
            try:
                envelope = _json(record_path)
                record = envelope.get("manifest") if kind == "skills" else envelope.get("record", envelope)
                if not isinstance(record, dict):
                    raise ValueError("Studio record payload is invalid")
                identity_value = str(record.get("skill_id" if kind == "skills" else "agent_id" if kind == "agents" else "workflow_id") or "")
                version = str(record.get("version") or revision.name)
                if not identity_value or version != revision.name:
                    raise ValueError("Studio revision identity does not match its canonical directory")
                record_sha = _sha(record_path)
                if kind == "agents":
                    try:
                        test = _verified(authority, revision / "test-receipt.json")
                        if test and test.get("agent_id") == identity_value and test.get("version") == version and test.get("agent_revision_sha256") == record_sha:
                            status = "tested" if test.get("passed") is True else "test-failed"
                            authenticated = True
                    except Exception as error:
                        reasons.append(f"test:{type(error).__name__}")
                    try:
                        admission = _verified(authority, revision / "admission-receipt.json")
                        if admission and admission.get("agent_id") == identity_value and admission.get("version") == version and admission.get("agent_revision_sha256") == record_sha:
                            status = "admitted" if admission.get("decision") == "admitted" else "rejected"
                            authenticated = True
                    except Exception as error:
                        reasons.append(f"admission:{type(error).__name__}")
                elif kind == "workflows":
                    try:
                        admission = _verified(authority, revision / "admission-receipt.json")
                        if admission and admission.get("workflow_id") == identity_value and admission.get("version") == version and admission.get("revision_sha256") == record_sha:
                            status = "admitted" if admission.get("decision") == "admitted" else "rejected"
                            authenticated = True
                    except Exception as error:
                        reasons.append(f"admission:{type(error).__name__}")
                else:
                    manifest_sha = digest(record)
                    payload = revision / str(envelope.get("payload_root") or "payload")
                    tree_sha = _tree_attestation(payload)[1]
                    if envelope.get("manifest_sha256") != manifest_sha or envelope.get("source_tree_sha256") != tree_sha:
                        raise PermissionError("Skill package record no longer matches its manifest or payload tree")
                    for receipt_name, success_status, failure_status in (
                        ("validation-receipt.json", "validated", "validation-failed"),
                        ("admission-receipt.json", "admitted", "rejected"),
                    ):
                        try:
                            receipt = _verified(authority, revision / receipt_name)
                            if receipt and receipt.get("skill_id") == identity_value and receipt.get("version") == version and receipt.get("manifest_sha256") == manifest_sha and receipt.get("source_tree_sha256") == tree_sha:
                                passed = receipt.get("passed") is True if receipt_name.startswith("validation") else receipt.get("decision") == "admitted"
                                status = success_status if passed else failure_status
                                authenticated = True
                        except Exception as error:
                            reasons.append(f"{receipt_name}:{type(error).__name__}")
                    try:
                        promotion_path = revision / "promotion-receipt.json"
                        promotion = _verified(authority, promotion_path)
                        if promotion and promotion.get("skill_id") == identity_value and promotion.get("version") == version:
                            canonical_root = (project_root / ".px" / "skills").resolve(strict=True)
                            target = (project_root / str(promotion.get("target_relative") or "")).resolve(strict=True)
                            if not _within(canonical_root, target):
                                raise PermissionError("Promoted skill target escapes canonical custody")
                            rollback = _verified(authority, revision / "rollback-receipt.json")
                            rolled_back = bool(
                                rollback
                                and rollback.get("skill_id") == identity_value
                                and rollback.get("version") in {None, version}
                            )
                            expected_tree = rollback.get("restored_tree_sha256") if rolled_back else promotion.get("promoted_tree_sha256")
                            if _tree_attestation(target)[1] != expected_tree:
                                raise PermissionError("Canonical skill no longer matches its authenticated lifecycle receipt")
                            active_receipt = rollback if rolled_back else promotion
                            operation = "rollback" if rolled_back else "promotion"
                            lifecycle_proof = _verify_lifecycle_transaction(
                                authority,
                                project_root,
                                active_receipt.get("lifecycle_transaction_relative"),
                                operation=operation,
                                skill_id=identity_value,
                                version=version,
                                target_relative=str(promotion.get("target_relative") or ""),
                                tree_sha256=str(expected_tree or ""),
                            )
                            projection_hashes = lifecycle_proof["projection_hashes"]
                            expected_projection_hashes = active_receipt.get("projection_after_sha256")
                            if (
                                not isinstance(expected_projection_hashes, dict)
                                or projection_hashes != expected_projection_hashes
                            ):
                                raise PermissionError("Lifecycle projection receipt binding changed")
                            rollback_available = False
                            backup_relative = promotion.get("backup_relative")
                            if backup_relative and not rolled_back:
                                backup_root = (project_root / ".px" / "preserved-skills").resolve(strict=True)
                                backup = (project_root / str(backup_relative)).resolve(strict=True)
                                promotion_manifest = lifecycle_proof["manifest"]
                                canonical = promotion_manifest.get("canonical")
                                if (
                                    not _within(backup_root, backup)
                                    or not isinstance(canonical, dict)
                                    or canonical.get("backup_relative") != backup_relative
                                    or _tree_attestation(backup)[1] != canonical.get("before_tree_sha256")
                                ):
                                    raise PermissionError("Rollback backup custody changed")
                                rollback_available = True
                            status = "rolled-back" if rolled_back else "promoted"
                            authenticated = True
                            lifecycle = {
                                "promotion_receipt_relative": promotion_path.relative_to(project_root).as_posix(),
                                "rollback_available": rollback_available,
                                "promoted_tree_sha256": promotion.get("promoted_tree_sha256"),
                                "rollback_target_relative": promotion.get("backup_relative"),
                                "lifecycle_transaction_relative": active_receipt.get("lifecycle_transaction_relative"),
                            }
                    except Exception as error:
                        reasons.append(f"promotion:{type(error).__name__}")
                reason = (
                    ";".join(reasons)
                    if reasons
                    else "authenticated lifecycle receipt"
                    if authenticated
                    else "no authenticated lifecycle receipt"
                )
            except Exception as error:
                status = "candidate"
                authenticated = False
                reason = f"authentication failed:{type(error).__name__}"
            rows[relative] = {"status": status, "authenticated": authenticated, "reason": reason, **lifecycle}
    return {
        "schema_version": "px.studio-catalog-status/1.1",
        "kind": kind,
        "records": rows,
        "visited_revisions": min(visited, MAX_REVISIONS),
        "truncated": stop,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=("agents", "workflows", "skills"), required=True)
    args = parser.parse_args()
    print(json.dumps(project(args.root, args.kind), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
