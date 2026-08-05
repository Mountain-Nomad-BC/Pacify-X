"""Audit text artifacts against project-owned canonical terminology."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
import re


def audit_glossary(
    glossary: Mapping[str, object],
    paths: Iterable[Path],
    *,
    project_root: Path,
    max_file_bytes: int = 1_000_000,
) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    terms = glossary.get("terms", ())
    if not isinstance(terms, Sequence) or isinstance(terms, (str, bytes)):
        raise ValueError("glossary terms must be an array")
    aliases: list[tuple[str, str]] = []
    canonical_seen: set[str] = set()
    for item in terms:
        if not isinstance(item, Mapping):
            raise ValueError("glossary term must be an object")
        canonical = str(item.get("canonical", "")).strip()
        if not canonical or canonical.casefold() in canonical_seen:
            raise ValueError("canonical terms must be nonempty and unique")
        canonical_seen.add(canonical.casefold())
        for alias in item.get("aliases", ()):
            value = str(alias).strip()
            if value and value.casefold() != canonical.casefold():
                aliases.append((value, canonical))
    selected_paths = tuple(sorted({item.resolve(strict=True) for item in paths}))
    issues = []
    skipped = []
    for path in selected_paths:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError(f"glossary audit path escapes project: {path}") from error
        if not path.is_file() or path.stat().st_size > max_file_bytes:
            skipped.append(relative)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for alias, canonical in aliases:
            pattern = re.compile(r"(?i)(?<!\w)" + re.escape(alias) + r"(?!\w)")
            for match in pattern.finditer(text):
                issues.append(
                    {
                        "path": relative,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "alias": match.group(0),
                        "canonical": canonical,
                    }
                )
    issues.sort(key=lambda item: (item["path"], item["line"], item["alias"].casefold()))
    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "skipped": sorted(skipped),
        "files_checked": len(selected_paths) - len(skipped),
    }
