"""Bounded read-only tooling signals and one CPU-authoritative text corpus."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import time
from typing import Callable

from .archive_io import reject_path_links
from .bounded_walk import bounded_walk, WalkLimits, FilesystemWalkError
from .input_files import (
    contained_file,
    read_file_image,
    relative_source_path,
    check_deadline,
    cooperative_deadline,
)
from .json_io import decode_json_object, bounded_json_text
from .numeric_inputs import bounded_integer, bounded_text, bounded_sequence


SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "quarantine",
    "repo_quarantine",
    ".quarantine",
    "_quarantine",
}
_CUSTODY_NAMES = {"quarantine", "repo_quarantine", ".quarantine", "_quarantine"}
_POLICY = "never_auto_install; submit a separate bounded proposal and obtain explicit approval"
_SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cpp",
    ".c",
    ".h",
}


def _root(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValueError("project/framework root must be a Path")
    bounded_text(str(path), "root path", maximum=4096, strip=False)
    if any(part.casefold() in _CUSTODY_NAMES for part in path.parts):
        raise ValueError("custody/quarantine root is excluded from acquisition")
    absolute = path.absolute()
    bounded_text(str(absolute), "absolute root path", maximum=4096, strip=False)
    if any(part.casefold() in _CUSTODY_NAMES for part in absolute.parts):
        raise ValueError("custody/quarantine root is excluded from acquisition")
    reject_path_links(path)
    return absolute


def _exclude(root: Path, relative: str) -> bool:
    parts = relative.split("/")
    if any(part.casefold() in _CUSTODY_NAMES for part in parts):
        return True
    if any(part.casefold() in SKIP_DIRECTORIES for part in parts[:-1]):
        return True
    if parts[-1].casefold() not in SKIP_DIRECTORIES:
        return False
    info = (root / relative).lstat()
    return (
        stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    )


def _walk(project: Path, maximum_files: int, deadline: float, *, search: bool):
    check_deadline(deadline)
    return bounded_walk(
        project,
        limits=WalkLimits(
            max_files=maximum_files,
            max_depth=64,
            max_bytes=64 * 1024 * 1024 if search else 64 * 1024**3,
            max_entries=40000,
            max_directories=20000,
            max_duration_seconds=max(0.001, deadline - time.monotonic()),
        ),
        exclude=lambda relative: _exclude(project, relative),
    )


def search_project_text(
    project: Path, needle: str, *, resolver: Callable[[str], str | None] = shutil.which
) -> tuple[str, ...]:
    """Complete bounded literal results; resolver availability grants no execution."""
    if (
        type(needle) is not str
        or not needle
        or len(needle) > 4096
        or len(needle.encode("utf-8")) > 4096
    ):
        raise ValueError("search needle must be nonempty text within 4096 UTF-8 bytes")
    deadline = time.monotonic() + 60.0
    project = _root(project)
    walked = _walk(project, 20000, deadline, search=True)
    sources = []
    used = 0
    for entry in walked.files:
        check_deadline(deadline)
        relative_source_path(entry.relative)
        path, info = contained_file(project, entry.relative)
        if info.st_size != entry.size or info.st_size > 1024 * 1024:
            raise ValueError(
                "search source changed or exceeded its image budget before acquisition"
            )
        used += info.st_size
        if used > 64 * 1024 * 1024:
            raise ValueError("search aggregate source image budget exceeded")
        sources.append((entry.relative, path, info))
    found = []
    output_bytes = 2
    for relative, path, info in sources:
        raw = read_file_image(path, info, limit=1024 * 1024, deadline=deadline)
        text = (
            raw.decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        check_deadline(deadline)
        if needle in text:
            output_bytes += (
                len(json.dumps(relative, ensure_ascii=False).encode("utf-8")) + 4
            )
            if output_bytes > 1024 * 1024 or len(found) >= 20000:
                raise ValueError("search result budget exceeded")
            found.append(relative)
    result = tuple(sorted(found, key=lambda value: (value.casefold(), value)))
    bounded_json_text(list(result), max_bytes=1024 * 1024)
    check_deadline(deadline)
    return result


def _location(resolver, candidate: str) -> str | None:
    if not callable(resolver):
        raise ValueError("resolver must be callable")
    try:
        value = resolver(candidate)
    except OSError:
        return None
    if value is None:
        return None
    return bounded_text(value, "resolver location", maximum=4096, strip=False)


def optional_tool_status(
    resolver: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    deadline = time.monotonic() + 60.0
    path = _location(resolver, "rg")
    check_deadline(deadline)
    return {
        "name": "ripgrep",
        "available": bool(path),
        "path": path,
        "required": False,
        "disposition": "optional_performance_enhancement",
        "eligible": False,
        "eligibility_reason": "native search requires current admission, exact-image ownership, parity and benchmark evidence",
    }


def _inventory(
    project: Path, *, maximum_files: int, deadline: float | None = None
) -> dict[str, object]:
    maximum_files = bounded_integer(maximum_files, "maximum_files", maximum=20000)
    deadline = cooperative_deadline(deadline)
    walked = _walk(_root(project), maximum_files, deadline, search=False)
    markdown = source = 0
    directories = set()
    for entry in walked.entries:
        if entry.kind == "directory":
            directories.add(entry.relative)
        else:
            suffix = Path(entry.relative).suffix.casefold()
            markdown += suffix in {".md", ".mdx"}
            source += suffix in _SOURCE_SUFFIXES
    check_deadline(deadline)
    return {
        "examined_files": walked.file_count,
        "markdown_files": markdown,
        "source_files": source,
        "directories": directories,
        "truncated": False,
    }


def _registry(root: Path, deadline: float):
    path, info = contained_file(
        _root(root), "registry/initial_tool_recommendations.json"
    )
    raw = read_file_image(path, info, limit=1024 * 1024, deadline=deadline)
    payload = decode_json_object(
        raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000
    )
    if (
        set(payload) != {"schema_version", "loading_rule", "tools"}
        or payload["schema_version"] != "1.0"
    ):
        raise ValueError("tool recommendation registry header is invalid")
    bounded_text(payload["loading_rule"], "loading rule", maximum=4096, strip=False)
    records = bounded_sequence(payload["tools"], "tools", maximum=256)
    identities = set()
    all_candidates = set()
    required = {
        "id",
        "display_name",
        "candidates",
        "relevance",
        "recommend_when",
        "missing_disposition",
        "install_effect",
        "approval_required",
        "auto_install",
    }
    optional = {"built_in_alternatives", "source_alias_disposition"}
    for record in records:
        check_deadline(deadline)
        if (
            type(record) is not dict
            or not required <= set(record)
            or set(record) - required - optional
        ):
            raise ValueError("tool recommendation fields are not exact")
        identity = bounded_text(record["id"], "tool id", maximum=256, strip=False)
        if identity in identities:
            raise ValueError("duplicate tool id")
        identities.add(identity)
        for key in (
            "display_name",
            "relevance",
            "missing_disposition",
            "install_effect",
        ):
            bounded_text(record[key], key, maximum=512, strip=False)
        if (
            record["approval_required"] is not True
            or record["auto_install"] is not False
        ):
            raise ValueError(
                "tool recommendations require explicit approval and forbid auto-install"
            )
        for candidate in bounded_sequence(
            record["candidates"], "resolver candidates", maximum=16, minimum=1
        ):
            all_candidates.add(
                bounded_text(candidate, "resolver candidate", maximum=256, strip=False)
            )
        if len(all_candidates) > 256:
            raise ValueError("distinct resolver work budget exceeded")
        rule = record["recommend_when"]
        allowed = {"minimum_markdown_files", "minimum_source_files", "or_directory"}
        if type(rule) is not dict or not rule or set(rule) - allowed:
            raise ValueError("recommendation rule is invalid")
        for key in ("minimum_markdown_files", "minimum_source_files"):
            if key in rule:
                bounded_integer(rule[key], key, minimum=0, maximum=20000)
        if "or_directory" in rule:
            relative_source_path(rule["or_directory"])
        for alternative in bounded_sequence(
            record.get("built_in_alternatives", []), "built-in alternatives", maximum=64
        ):
            bounded_text(alternative, "built-in alternative", maximum=256, strip=False)
        if "source_alias_disposition" in record:
            bounded_text(
                record["source_alias_disposition"],
                "source alias disposition",
                maximum=256,
                strip=False,
            )
    return records


def _incomplete(project: Path, error: str) -> dict[str, object]:
    result = {
        "schema_version": "1.0",
        "valid": False,
        "project": project.as_posix(),
        "read_only": True,
        "executed_changes": False,
        "inventory": {
            "examined_files": None,
            "markdown_files": None,
            "source_files": None,
            "truncated": True,
        },
        "recommendations": [],
        "approval_requests": [],
        "installation_policy": _POLICY,
        "errors": [error[:512]],
    }

    bounded_json_text(result, max_bytes=1024 * 1024)
    return result


def assess_project_tooling(
    root: Path,
    project: Path,
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    maximum_files: int = 5000,
) -> dict[str, object]:
    maximum_files = bounded_integer(maximum_files, "maximum_files", maximum=20000)
    if not callable(resolver):
        raise ValueError("resolver must be callable")
    deadline = time.monotonic() + 60.0
    root, project = _root(root), _root(project)
    if not project.is_dir():
        return _incomplete(project, "project directory does not exist")
    records = _registry(root, deadline)
    try:
        inventory = _inventory(project, maximum_files=maximum_files, deadline=deadline)
    except (FilesystemWalkError, OSError) as error:
        return _incomplete(project, type(error).__name__ + ": " + str(error))
    check_deadline(deadline)
    results, approvals = [], []
    locations = {}
    for record in records:
        found = []
        for candidate in record["candidates"]:
            check_deadline(deadline)
            if candidate not in locations:
                locations[candidate] = _location(resolver, candidate)
            check_deadline(deadline)
            if locations[candidate] is not None:
                found.append(locations[candidate])
        rule = record["recommend_when"]
        relevant = (
            (
                "minimum_markdown_files" in rule
                and inventory["markdown_files"] >= rule["minimum_markdown_files"]
            )
            or (
                "minimum_source_files" in rule
                and inventory["source_files"] >= rule["minimum_source_files"]
            )
            or (
                "or_directory" in rule
                and rule["or_directory"] in inventory["directories"]
            )
        )
        detected = bool(found)
        disposition = (
            (
                "available_for_separately_approved_configuration"
                if relevant
                else "available_not_selected"
            )
            if detected
            else (
                record["missing_disposition"]
                if relevant
                else "not_relevant_to_current_project_signals"
            )
        )
        results.append(
            {
                "id": record["id"],
                "display_name": record["display_name"],
                "detected": detected,
                "locations": sorted(set(found)),
                "relevant": relevant,
                "disposition": disposition,
                "built_in_alternatives": record.get("built_in_alternatives", []),
                "auto_install": False,
                "executed_changes": False,
            }
        )
        if relevant and not detected and disposition == "offer_optional_installation":
            approvals.append(
                {
                    "id": f"install-{record['id']}",
                    "tool": record["id"],
                    "effect": record["install_effect"],
                    "approval_required": True,
                    "status": "not_requested",
                    "reason": "optional tool is relevant to observed project signals but is not available",
                }
            )
    result = {
        "schema_version": "1.0",
        "valid": True,
        "project": project.as_posix(),
        "read_only": True,
        "executed_changes": False,
        "inventory": {
            key: value for key, value in inventory.items() if key != "directories"
        },
        "recommendations": results,
        "approval_requests": approvals,
        "installation_policy": _POLICY,
        "errors": [],
    }
    bounded_json_text(result, max_bytes=1024 * 1024)
    check_deadline(deadline)
    return result
