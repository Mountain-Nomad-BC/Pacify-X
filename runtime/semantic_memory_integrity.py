"""Validate durable PX memory references against identity/location inventories."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .semantic_memory_refs import extract_memory_references
from .semantic_memory_relocation import MemoryLocation


@dataclass(frozen=True, slots=True)
class MemoryReferenceIssue:
    code: str
    source_id: str
    reference: str
    detail: str


@dataclass(frozen=True, slots=True)
class MemoryIntegrityReport:
    issues: tuple[MemoryReferenceIssue, ...]
    checked_sources: int
    checked_references: int
    clean: bool


def validate_memory_references(
    contents: Mapping[str, str],
    locations: Mapping[str, MemoryLocation],
    *,
    project_id: str | None = None,
    max_references: int = 2048,
) -> MemoryIntegrityReport:
    if not isinstance(contents, Mapping) or not isinstance(locations, Mapping):
        raise TypeError("contents and locations must be mappings")
    if type(max_references) is not int or max_references < 1:
        raise ValueError("max_references must be a positive integer")
    if project_id is not None and (type(project_id) is not str or not project_id.strip()):
        raise ValueError("project_id must be nonempty text when provided")

    if any(type(source_id) is not str or not source_id for source_id in contents):
        raise ValueError("memory integrity source identifiers must be nonempty text")
    issues: list[MemoryReferenceIssue] = []
    total = 0
    for source_id in sorted(contents):
        content = contents[source_id]
        if type(content) is not str:
            raise TypeError("memory integrity source contents must be text")
        remaining = max_references - total
        if remaining < 1:
            if extract_memory_references(content, max_references=1):
                raise ValueError("memory reference budget exceeded")
            refs = ()
        else:
            refs = extract_memory_references(content, max_references=remaining)
            total += len(refs)
        for ref in refs:
            uri = ref.uri()
            # Scope is checked before target lookup to avoid leaking whether a foreign
            # project happens to contain the referenced memory identity.
            if project_id is not None and ref.project_id != project_id:
                issues.append(
                    MemoryReferenceIssue(
                        "foreign_project_reference",
                        source_id,
                        uri,
                        "reference escapes project scope",
                    )
                )
                continue
            locator = locations.get(ref.memory_id)
            if locator is None:
                issues.append(
                    MemoryReferenceIssue(
                        "stale_reference",
                        source_id,
                        uri,
                        "memory identity does not resolve",
                    )
                )
                continue
            if not isinstance(locator, MemoryLocation):
                raise TypeError("location inventory values must be MemoryLocation objects")
            if locator.project_id != ref.project_id:
                issues.append(
                    MemoryReferenceIssue(
                        "project_mismatch",
                        source_id,
                        uri,
                        f"target belongs to {locator.project_id}",
                    )
                )
                continue
            # A pinned URI identifies one exact revision.  The current location record
            # cannot prove historical-revision availability merely because it is newer.
            if ref.revision is not None and locator.record_revision != ref.revision:
                issues.append(
                    MemoryReferenceIssue(
                        "revision_not_available",
                        source_id,
                        uri,
                        f"current target revision is {locator.record_revision}",
                    )
                )
    ordered = tuple(sorted(issues, key=lambda item: (item.source_id, item.reference, item.code)))
    return MemoryIntegrityReport(ordered, len(contents), total, not ordered)
