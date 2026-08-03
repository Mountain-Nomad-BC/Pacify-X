"""Read-only, signal-based first-run tooling assessment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable


SKIP_DIRECTORIES = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "build", "dist", "quarantine", "repo_quarantine"}


def search_project_text(project: Path, needle: str, *, resolver: Callable[[str], str | None] = shutil.which) -> tuple[str, ...]:
    """Search text deterministically; ripgrep is optional acceleration only."""
    project = project.resolve()
    executable = resolver("rg")
    if executable:
        try:
            completed = subprocess.run([executable, "--files-with-matches", "--fixed-strings", needle, "."], cwd=project, capture_output=True, text=True, timeout=30, shell=False, env={"PATH": str(Path(executable).parent), "NO_COLOR": "1"})
            if completed.returncode in {0, 1}:
                return tuple(sorted((line.removeprefix("./").removeprefix(".\\").replace("\\", "/") for line in completed.stdout.splitlines()), key=lambda value: (value.casefold(), value)))
        except (OSError, subprocess.TimeoutExpired):
            pass
    found = []
    for base, names, files in os.walk(project, followlinks=False):
        names[:] = sorted(name for name in names if name not in SKIP_DIRECTORIES)
        for name in sorted(files):
            path = Path(base) / name
            try:
                if needle in path.read_text(encoding="utf-8", errors="replace"):
                    found.append(path.relative_to(project).as_posix())
            except OSError:
                continue
    return tuple(sorted(found, key=lambda value: (value.casefold(), value)))


def optional_tool_status(resolver: Callable[[str], str | None] = shutil.which) -> dict[str, object]:
    path = resolver("rg")
    return {"name": "ripgrep", "available": bool(path), "path": path, "required": False, "disposition": "optional_performance_enhancement"}


def _inventory(project: Path, *, maximum_files: int) -> dict[str, object]:
    markdown = source = 0
    directories: set[str] = set()
    examined = 0
    truncated = False
    for base, names, files in os.walk(project, followlinks=False):
        names[:] = sorted(name for name in names if name not in SKIP_DIRECTORIES)
        relative_base = Path(base).relative_to(project)
        directories.update(path.as_posix() for name in names if (path := relative_base / name))
        for name in sorted(files):
            examined += 1
            if examined > maximum_files:
                truncated = True
                break
            suffix = Path(name).suffix.casefold()
            markdown += suffix in {".md", ".mdx"}
            source += suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rs", ".rb", ".php", ".cpp", ".c", ".h"}
        if truncated:
            break
    return {"examined_files": min(examined, maximum_files), "markdown_files": markdown, "source_files": source, "directories": directories, "truncated": truncated}


def assess_project_tooling(
    root: Path,
    project: Path,
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    maximum_files: int = 5_000,
) -> dict[str, object]:
    root = root.resolve()
    project = project.resolve()
    if not project.is_dir():
        return {"schema_version": "1.0", "valid": False, "project": project.as_posix(), "errors": ["project directory does not exist"]}
    if maximum_files < 1 or maximum_files > 20_000:
        raise ValueError("maximum_files must be between 1 and 20000")
    registry = json.loads((root / "registry/initial_tool_recommendations.json").read_text(encoding="utf-8"))
    inventory = _inventory(project, maximum_files=maximum_files)
    results: list[dict[str, object]] = []
    approvals: list[dict[str, object]] = []
    for record in registry["tools"]:
        locations: list[str] = []
        for candidate in record["candidates"]:
            try:
                location = resolver(str(candidate))
            except OSError:
                location = None
            if location:
                locations.append(str(location))
        rule = record["recommend_when"]
        relevant = (
            int(inventory["markdown_files"]) >= int(rule.get("minimum_markdown_files", 10**9))
            or int(inventory["source_files"]) >= int(rule.get("minimum_source_files", 10**9))
            or str(rule.get("or_directory", "missing")) in inventory["directories"]
        )
        detected = bool(locations)
        if detected:
            disposition = "available_for_separately_approved_configuration" if relevant else "available_not_selected"
        elif relevant:
            disposition = str(record["missing_disposition"])
        else:
            disposition = "not_relevant_to_current_project_signals"
        item = {
            "id": record["id"],
            "display_name": record["display_name"],
            "detected": detected,
            "locations": sorted(set(locations)),
            "relevant": relevant,
            "disposition": disposition,
            "built_in_alternatives": record.get("built_in_alternatives", []),
            "auto_install": False,
            "executed_changes": False,
        }
        results.append(item)
        if relevant and not detected and disposition == "offer_optional_installation":
            approvals.append({
                "id": f"install-{record['id']}",
                "tool": record["id"],
                "effect": record["install_effect"],
                "approval_required": True,
                "status": "not_requested",
                "reason": "optional tool is relevant to observed project signals but is not available",
            })
    return {
        "schema_version": "1.0",
        "valid": True,
        "project": project.as_posix(),
        "read_only": True,
        "executed_changes": False,
        "inventory": {key: value for key, value in inventory.items() if key != "directories"},
        "recommendations": results,
        "approval_requests": approvals,
        "installation_policy": "never_auto_install; submit a separate bounded proposal and obtain explicit approval",
        "errors": [],
    }
