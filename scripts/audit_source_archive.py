"""Audit the exact Git/GitHub source-archive boundary without extracting it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from typing import Any


MAX_SOURCE_ARCHIVE_BYTES = 128 * 1024 * 1024


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


def audit_source_archive(
    root: Path, *, revision: str = "HEAD", worktree_attributes: bool = False
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    command = ["git", "-C", str(root), "archive", "--format=tar"]
    if worktree_attributes:
        command.append("--worktree-attributes")
    command.append(revision)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    members: list[str] = []
    forbidden: list[str] = []
    total_bytes = 0
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                members.append(member.name)
                total_bytes += member.size
                if _forbidden(member.name):
                    forbidden.append(member.name)
    except tarfile.TarError as error:
        process.kill()
        process.wait(timeout=10)
        return {
            "schema_version": "px.source-archive-audit/1.0",
            "valid": False,
            "revision": revision,
            "errors": [f"invalid Git archive: {type(error).__name__}"],
        }
    stderr = (
        process.stderr.read().decode("utf-8", errors="replace")
        if process.stderr
        else ""
    )
    exit_code = process.wait(timeout=30)
    errors = []
    if exit_code != 0:
        errors.append(stderr.strip() or f"git archive exited {exit_code}")
    if forbidden:
        errors.append(f"archive contains {len(forbidden)} host/evidence custody members")
    if total_bytes > MAX_SOURCE_ARCHIVE_BYTES:
        errors.append("archive exceeds the 128 MiB uncompressed source budget")
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
