"""Audit the exact Git/GitHub source-archive boundary without extracting it."""

from __future__ import annotations

import argparse
import hashlib
import io
from collections.abc import Callable, Sequence
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
import time
from typing import Any
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager


# The authoritative source tree has grown well past the 262.5 MiB baseline this
# bound was originally measured against: the tracked tree is currently ~755 MiB
# uncompressed across ~9.1k files, dominated by generated projections under
# .agentic_engineering_os_px/project-map/ and docs/architecture/. Those projections
# expand alongside the runtime and are planned to grow again, so this ceiling is
# set with wide headroom to stop recurring mid-campaign re-certifications.
# It remains a real guard: the forbidden-member and required-member audits below
# still bound what may enter the archive.
MAX_SOURCE_ARCHIVE_BYTES = 1536 * 1024 * 1024
ArchiveCommandBuilder = Callable[[Path], Sequence[str]]


def _forbidden(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts:
        return False
    top = parts[0]
    return (
        top in {".tmp", ".VSCodeCounter", "evidence"}
        or top.startswith(".tmp_")
        or top.startswith("tmp_")
        or parts[:2]
        in {
            (".px", "global-skill-isolation"),
            (".px", "preserved-extension-installations"),
            (".px", "preserved-skills"),
        }
        or parts[:2] == (".agentic_engineering_os_px", "coordination")
    )


def _inspect_archive(
    archive_path: Path, *, revision: str, worktree_attributes: bool,
    current_manifest: dict[str, str] | None = None,
) -> dict[str, Any]:
    members: list[str] = []
    forbidden: list[str] = []
    total_bytes = 0
    archive_bytes = archive_path.stat().st_size
    if archive_bytes > MAX_SOURCE_ARCHIVE_BYTES:
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": [f"archive exceeds the {MAX_SOURCE_ARCHIVE_BYTES // (1024 * 1024)} MiB physical source budget"],
            "archive_bytes": archive_bytes,
            "maximum_archive_bytes": MAX_SOURCE_ARCHIVE_BYTES,
        }
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive:
                if current_manifest is not None:
                    if not member.isfile() or member.name in members or member.name not in current_manifest:
                        raise ValueError("current archive has an unexpected or duplicate member")
                    image = archive.extractfile(member)
                    if image is None:
                        raise ValueError("current archive member cannot be read")
                    measured = hashlib.sha256()
                    for block in iter(lambda: image.read(1024 * 1024), b""):
                        measured.update(block)
                    if measured.hexdigest() != current_manifest[member.name]:
                        raise ValueError("current archive member hash differs from captured source")
                if not member.isfile():
                    continue
                members.append(member.name)
                total_bytes += member.size
                if _forbidden(member.name):
                    forbidden.append(member.name)
    except (tarfile.TarError, ValueError) as error:
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": [f"invalid Git archive: {type(error).__name__}"],
        }
    errors = []
    if forbidden:
        errors.append(f"archive contains {len(forbidden)} host/evidence custody members")
    if total_bytes > MAX_SOURCE_ARCHIVE_BYTES:
        errors.append(
            f"archive exceeds the {MAX_SOURCE_ARCHIVE_BYTES // (1024 * 1024)} MiB uncompressed source budget"
        )
    required = {
        "pyproject.toml",
        "runtime/cli.py",
        "runtime/operational_gap_ledger.py",
        ".agentic_engineering_os_px/project-registry.json",
    }
    if current_manifest is not None:
        required.remove(".agentic_engineering_os_px/project-registry.json")
        required.add("policies/rev1xx-validation.json")
        if set(members) != set(current_manifest):
            errors.append("current archive inventory differs from captured source")
    missing = sorted(required - set(members))
    if missing:
        errors.append("archive is missing required bootstrap authority")
    return {
        "schema_version": "px.source-archive-audit/1.0",
        "valid": not errors,
        "revision": revision,
        "worktree_attributes": worktree_attributes,
        "archive_bytes": archive_bytes,
        "maximum_archive_bytes": MAX_SOURCE_ARCHIVE_BYTES,
        "file_count": len(members),
        "uncompressed_bytes": total_bytes,
        "maximum_uncompressed_bytes": MAX_SOURCE_ARCHIVE_BYTES,
        "forbidden_members": forbidden,
        "missing_required_members": missing,
        "errors": errors,
    }


def _audit_current_source(root: Path, archive_path: Path, timeout_seconds: float) -> dict[str, Any]:
    """Measure preserved current files; Git acceptance remains explicitly deferred."""
    from runtime.archive_io import reject_path_links
    from runtime.plan_registry import _planning_object, _require_current_campaign
    from runtime.source_boundary import authored_paths

    _require_current_campaign(_planning_object(root / "policies/rev1xx-validation.json"))
    started = time.monotonic()
    paths = authored_paths(root)
    manifest: dict[str, str] = {}
    total = 0
    with tarfile.open(archive_path, "x") as archive:
        for relative in paths:
            if time.monotonic() - started > timeout_seconds:
                raise ValueError("current archive capture exceeded its deadline")
            path = root / relative
            reject_path_links(path)
            size = path.stat().st_size
            total += size
            if size > 128 * 1024**2 or total > MAX_SOURCE_ARCHIVE_BYTES:
                raise ValueError("current archive source exceeds its byte bound")
            data = path.read_bytes()
            if len(data) != size:
                raise ValueError("current archive source changed during capture")
            manifest[relative] = hashlib.sha256(data).hexdigest()
            member = tarfile.TarInfo(relative)
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    if authored_paths(root) != paths:
        raise ValueError("current source inventory changed during capture")
    for relative, expected in manifest.items():
        if time.monotonic() - started > timeout_seconds:
            raise ValueError("current archive verification exceeded its deadline")
        path = root / relative
        reject_path_links(path)
        if path.stat().st_size > 128 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("current source bytes changed during capture")
    result = _inspect_archive(archive_path, revision="current-preserved-source",
                              worktree_attributes=False, current_manifest=manifest)
    result.update(validation_basis="current_implementation", historical_prerequisites=False,
                  source_manifest_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                  git_acceptance={"status":"explicitly_deferred_by_owner", "satisfied":False})
    return result


def audit_source_archive(
    root: Path,
    *,
    revision: str = "HEAD",
    worktree_attributes: bool = False,
    timeout_seconds: float = 120.0,
    resource_manager: ResourceManager | None = None,
    cleanup_root: Path | None = None,
    command_builder: ArchiveCommandBuilder | None = None,
) -> dict[str, Any]:
    """Audit an archive produced by one registered, bounded owned process tree."""

    root = root.resolve(strict=True)
    if timeout_seconds <= 0:
        raise ValueError("archive timeout must be positive")
    manager = resource_manager or ResourceManager(
        root / ".agentic_engineering_os_px" / "resource-lifecycle" / "ledger.json"
    )
    allowed_cleanup_root = (cleanup_root or Path(tempfile.gettempdir())).resolve(
        strict=True
    )
    run_id = f"source-archive-audit-{uuid4().hex}"
    workspace = manager.create_workspace(
        allowed_cleanup_root,
        project_id="pacify-x",
        run_id=run_id,
        lane_id="source-archive-audit",
        creator="scripts.audit_source_archive",
        prefix="pacify-x-source-archive-",
    )
    workspace_path = Path(str(workspace.path)).resolve(strict=True)
    archive_path = workspace_path / "source.tar"
    payload: dict[str, Any]
    try:
        if command_builder is None and (root / "policies/rev1xx-validation.json").exists():
            try:
                payload = _audit_current_source(root, archive_path, timeout_seconds)
            except (OSError, ValueError, RuntimeError) as error:
                payload = {"schema_version":"px.source-archive-audit/1.0", "valid":False,
                           "validation_basis":"current_implementation", "errors":[str(error)]}
        elif command_builder is None:
            git = shutil.which("git")
            if git is None:
                payload = {
                    "schema_version": "px.source-archive-audit/1.0",
                    "valid": False,
                    "revision": revision,
                    "errors": ["git executable is unavailable"],
                }
            else:
                command = [
                    str(Path(git).resolve(strict=True)),
                    "-C",
                    str(root),
                    "archive",
                    "--format=tar.gz",
                    f"--output={archive_path}",
                ]
                if worktree_attributes:
                    command.append("--worktree-attributes")
                command.append(revision)
                payload = _run_archive_process(
                    root,
                    archive_path,
                    command,
                    manager=manager,
                    run_id=run_id,
                    timeout_seconds=timeout_seconds,
                    revision=revision,
                    worktree_attributes=worktree_attributes,
                )
        else:
            payload = _run_archive_process(
                root,
                archive_path,
                list(command_builder(archive_path)),
                manager=manager,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                revision=revision,
                worktree_attributes=worktree_attributes,
            )
    finally:
        cleanup = manager.reclaim_ephemeral_path(
            workspace.resource_id, reason="source_archive_audit_complete"
        )
    payload["workspace_cleanup"] = {
        "cleanup_id": cleanup.cleanup_id,
        "resources_reclaimed": cleanup.resources_reclaimed,
        "resources_failed": cleanup.resources_failed,
        "errors": list(cleanup.errors),
    }
    if cleanup.resources_reclaimed != 1 or cleanup.errors:
        payload["valid"] = False
        payload.setdefault("errors", []).append("archive workspace cleanup failed")
    return payload


def _run_archive_process(
    root: Path,
    archive_path: Path,
    command: Sequence[str],
    *,
    manager: ResourceManager,
    run_id: str,
    timeout_seconds: float,
    revision: str,
    worktree_attributes: bool,
) -> dict[str, Any]:
    if not command:
        raise ValueError("archive command must not be empty")
    output_limit = 64 * 1024
    budget = {
        "startup_timeout_seconds": timeout_seconds,
        "idle_timeout_seconds": timeout_seconds,
        "total_timeout_seconds": timeout_seconds,
        "graceful_shutdown_seconds": 2.0,
        "force_shutdown_seconds": 15.0,
        "stdout_limit_bytes": output_limit,
        "stderr_limit_bytes": output_limit,
    }
    action = {
        "action_id": f"source-archive:{run_id}",
        "effects": ["process", "filesystem-write"],
        "allowed_effects": ["process", "filesystem-write"],
        "target_paths": [str(archive_path)],
        "owned_paths": [str(root), str(archive_path.parent)],
        "budget": budget,
        "limits": dict(budget),
        "approval": True,
        "policy_override_requested": False,
    }
    result = ProcessSupervisor(manager).run(
        command,
        cwd=root,
        action=action,
        project_id="pacify-x",
        run_id=run_id,
        lane_id="source-archive-audit",
        creator="scripts.audit_source_archive",
    )
    process_evidence = {
        "status": result.status,
        "exit_code": result.exit_code,
        "tree_closed": result.tree_closed,
        "resource_id": result.resource_id,
        "receipt_path": result.receipt_path,
        "stdout_dropped_bytes": result.stdout.dropped_bytes,
        "stderr_dropped_bytes": result.stderr.dropped_bytes,
    }
    if result.status != "exited" or result.exit_code != 0 or not result.tree_closed:
        detail = result.stderr.text.strip()
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": [detail or f"git archive process ended as {result.status}"],
            "process": process_evidence,
        }
    if not archive_path.is_file():
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": ["git archive process produced no archive"],
            "process": process_evidence,
        }
    payload = _inspect_archive(
        archive_path,
        revision=revision,
        worktree_attributes=worktree_attributes,
    )
    payload["process"] = process_evidence
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--worktree-attributes", action="store_true")
    args = parser.parse_args()
    result = audit_source_archive(
        args.root,
        revision=args.revision,
        worktree_attributes=args.worktree_attributes,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
