"""Audit the exact Git/GitHub source-archive boundary without extracting it."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from typing import Any
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager


MAX_SOURCE_ARCHIVE_BYTES = 256 * 1024 * 1024
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
        or parts[:2] == (".engineering-bootstrap", "coordination")
    )


def _inspect_archive(
    archive_path: Path, *, revision: str, worktree_attributes: bool
) -> dict[str, Any]:
    members: list[str] = []
    forbidden: list[str] = []
    total_bytes = 0
    if archive_path.stat().st_size > MAX_SOURCE_ARCHIVE_BYTES:
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": ["archive exceeds the 256 MiB physical source budget"],
        }
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                members.append(member.name)
                total_bytes += member.size
                if _forbidden(member.name):
                    forbidden.append(member.name)
    except tarfile.TarError as error:
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
        errors.append("archive exceeds the 256 MiB uncompressed source budget")
    required = {
        "pyproject.toml",
        "runtime/cli.py",
        "registry/operational_gap_ledger.jsonl",
        ".engineering-bootstrap/project-registry.json",
    }
    missing = sorted(required - set(members))
    if missing:
        errors.append("archive is missing required bootstrap authority")
    return {
        "schema_version": "px.source-archive-audit/1.0",
        "valid": not errors,
        "revision": revision,
        "worktree_attributes": worktree_attributes,
        "file_count": len(members),
        "uncompressed_bytes": total_bytes,
        "maximum_uncompressed_bytes": MAX_SOURCE_ARCHIVE_BYTES,
        "forbidden_members": forbidden,
        "missing_required_members": missing,
        "errors": errors,
    }


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
        root / ".engineering-bootstrap" / "resource-lifecycle" / "ledger.json"
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
        if command_builder is None:
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
                    "--format=tar",
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
