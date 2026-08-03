"""Recoverably externalize an explicit set of project-relative paths."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _inventory(path: Path) -> dict[str, str]:
    if path.is_file():
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*")) if item.is_file()
    }


def quarantine_paths(workspace: Path, project: Path, destination: Path, manifest: Path, paths: list[Path], reason: str) -> dict[str, object]:
    workspace = workspace.resolve(); project = project.resolve()
    destination = destination.resolve(); manifest = manifest.resolve()
    if not _inside(project, workspace) or not project.is_dir():
        raise ValueError("project must be an existing directory inside the workspace")
    if not _inside(destination, workspace) or _inside(destination, project) or destination.exists():
        raise ValueError("destination must be new, external to the project, and inside the workspace")
    if not _inside(manifest, workspace) or _inside(manifest, project) or manifest.exists():
        raise ValueError("manifest must be new, external to the project, and inside the workspace")
    sources: list[tuple[Path, Path, dict[str, str]]] = []
    seen: set[Path] = set()
    for relative in paths:
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"path must be project-relative: {relative}")
        source = (project / relative).resolve()
        if not _inside(source, project) or source == project or not source.exists() or source in seen:
            raise ValueError(f"invalid, missing, broad, or duplicate source: {relative}")
        seen.add(source)
        sources.append((source, relative, _inventory(source)))
    destination.mkdir(parents=True)
    records: list[dict[str, object]] = []
    for source, relative, before in sources:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        after = _inventory(target)
        if source.exists() or before != after:
            raise RuntimeError(f"post-move reconciliation failed: {relative}")
        records.append({"source": relative.as_posix(), "destination": target.relative_to(workspace).as_posix(), "file_count": len(after), "files": [{"path": key, "sha256": value} for key, value in sorted(after.items())]})
    payload = {
        "schema_version": "1.0", "operation": "recoverable_external_quarantine",
        "created_utc": datetime.now(timezone.utc).isoformat(), "reason": reason,
        "project": project.relative_to(workspace).as_posix(), "destination": destination.relative_to(workspace).as_posix(),
        "path_count": len(records), "file_count": sum(int(item["file_count"]) for item in records),
        "inventory_reconciled": True, "hard_delete": False,
        "recovery": "Move an exact recorded destination back to its original project-relative source only after approved review.",
        "records": records,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--path", type=Path, action="append", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    result = quarantine_paths(args.workspace, args.project, args.destination, args.manifest, args.path, args.reason)
    print(json.dumps({key: result[key] for key in ("operation", "path_count", "file_count", "inventory_reconciled", "hard_delete")}, indent=2))
