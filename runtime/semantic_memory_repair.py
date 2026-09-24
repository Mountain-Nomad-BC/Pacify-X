"""Plan exact legacy ``mem:alias`` rewrites; fuzzy matches are suggestions only.

This module returns candidate text.  It never persists source files/memory records and
therefore cannot grant write authority to a model or caller.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Mapping

from .semantic_code_types import stable_sha256
from .semantic_memory_aliases import MemoryAliasRegistry
from .semantic_memory_refs import parse_memory_reference

_LEGACY = re.compile(r"(?<![A-Za-z0-9_./-])mem:([A-Za-z0-9_./-]+)")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyReferenceRewrite:
    source_id: str
    legacy_reference: str
    canonical_reference: str
    occurrences: int

    def __post_init__(self) -> None:
        if type(self.source_id) is not str or not self.source_id:
            raise ValueError("rewrite source_id must be nonempty text")
        if not self.legacy_reference.startswith("mem:"):
            raise ValueError("legacy_reference must use mem: syntax")
        parse_memory_reference(self.canonical_reference)
        if type(self.occurrences) is not int or self.occurrences < 1:
            raise ValueError("rewrite occurrences must be a positive integer")


@dataclass(frozen=True, slots=True)
class MemoryReferenceRepairPlan:
    rewrites: tuple[LegacyReferenceRewrite, ...]
    unresolved: tuple[tuple[str, str, tuple[str, ...]], ...]
    source_sha256s: tuple[tuple[str, str], ...]
    plan_sha256: str

    def __post_init__(self) -> None:
        if type(self.rewrites) is not tuple or type(self.unresolved) is not tuple or type(self.source_sha256s) is not tuple:
            raise TypeError("repair plan collections must be tuples")
        sources = [source_id for source_id, _ in self.source_sha256s]
        if len(set(sources)) != len(sources):
            raise ValueError("repair plan source hashes must be unique by source_id")
        for source_id, digest in self.source_sha256s:
            if type(source_id) is not str or not source_id:
                raise ValueError("repair plan source_id must be nonempty text")
            if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
                raise ValueError("repair plan source digest must be SHA-256")
        rewrite_keys = [(item.source_id, item.legacy_reference) for item in self.rewrites]
        if len(set(rewrite_keys)) != len(rewrite_keys):
            raise ValueError("repair plan rewrites must be unique per source/reference")
        if type(self.plan_sha256) is not str or _SHA256_RE.fullmatch(self.plan_sha256) is None:
            raise ValueError("plan_sha256 must be a SHA-256 digest")


def _plan_identity(
    rewrites: tuple[LegacyReferenceRewrite, ...],
    unresolved: tuple[tuple[str, str, tuple[str, ...]], ...],
    source_sha256s: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    return {
        "rewrites": [
            (item.source_id, item.legacy_reference, item.canonical_reference, item.occurrences)
            for item in rewrites
        ],
        "unresolved": unresolved,
        "source_sha256s": source_sha256s,
    }


def plan_legacy_reference_repair(
    contents: Mapping[str, str], aliases: MemoryAliasRegistry
) -> MemoryReferenceRepairPlan:
    if not isinstance(contents, Mapping):
        raise TypeError("contents must be a mapping")
    if not isinstance(aliases, MemoryAliasRegistry):
        raise TypeError("aliases must be a MemoryAliasRegistry")
    if any(type(source_id) is not str or not source_id for source_id in contents):
        raise ValueError("repair source identifiers must be nonempty text")
    rewrites: list[LegacyReferenceRewrite] = []
    unresolved: list[tuple[str, str, tuple[str, ...]]] = []
    source_sha256s: list[tuple[str, str]] = []
    for source_id in sorted(contents):
        content = contents[source_id]
        if type(content) is not str:
            raise TypeError("repair source contents must be text")
        source_sha256s.append((source_id, _content_sha256(content)))
        counts: dict[str, int] = {}
        for match in _LEGACY.finditer(content):
            alias = match.group(1)
            counts[alias] = counts.get(alias, 0) + 1
        for alias in sorted(counts):
            target = aliases.resolve(alias)
            legacy = f"mem:{alias}"
            if target is not None:
                rewrites.append(
                    LegacyReferenceRewrite(source_id, legacy, target.uri(), counts[alias])
                )
            else:
                candidates = tuple(item.alias for item in aliases.candidates(alias))
                unresolved.append((source_id, legacy, candidates))
    rewrites_tuple = tuple(rewrites)
    unresolved_tuple = tuple(unresolved)
    hashes_tuple = tuple(source_sha256s)
    identity = _plan_identity(rewrites_tuple, unresolved_tuple, hashes_tuple)
    return MemoryReferenceRepairPlan(
        rewrites_tuple,
        unresolved_tuple,
        hashes_tuple,
        stable_sha256(identity),
    )


def apply_legacy_reference_repair(
    contents: Mapping[str, str],
    plan: MemoryReferenceRepairPlan,
    *,
    write: bool = False,
) -> dict[str, str]:
    if type(write) is not bool:
        raise TypeError("write must be a boolean")
    if write:
        raise PermissionError(
            "semantic memory repair is candidate-only; persistent mutation requires the canonical owner"
        )
    if not isinstance(contents, Mapping):
        raise TypeError("contents must be a mapping")
    if not isinstance(plan, MemoryReferenceRepairPlan):
        raise TypeError("plan must be a MemoryReferenceRepairPlan")
    if stable_sha256(_plan_identity(plan.rewrites, plan.unresolved, plan.source_sha256s)) != plan.plan_sha256:
        raise RuntimeError("memory repair plan digest mismatch")

    expected_hashes = dict(plan.source_sha256s)
    output = dict(contents)
    for source_id, expected_sha in expected_hashes.items():
        if source_id not in output:
            raise RuntimeError("repair source disappeared")
        if type(output[source_id]) is not str:
            raise TypeError("repair source contents must be text")
        if _content_sha256(output[source_id]) != expected_sha:
            raise RuntimeError("repair source changed since planning")

    by_source: dict[str, dict[str, LegacyReferenceRewrite]] = {}
    for item in plan.rewrites:
        by_source.setdefault(item.source_id, {})[item.legacy_reference] = item

    for source_id, source_rewrites in by_source.items():
        seen = {key: 0 for key in source_rewrites}

        def replace_match(match: re.Match[str]) -> str:
            legacy = f"mem:{match.group(1)}"
            item = source_rewrites.get(legacy)
            if item is None:
                return match.group(0)
            seen[legacy] += 1
            return item.canonical_reference

        output[source_id] = _LEGACY.sub(replace_match, output[source_id])
        for legacy, item in source_rewrites.items():
            if seen[legacy] != item.occurrences:
                raise RuntimeError("legacy reference count changed since planning")
    return output
