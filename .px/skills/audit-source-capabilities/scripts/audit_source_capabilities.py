"""Deterministically inventory a source tree and surface reusable mechanisms."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib
from typing import Iterable


TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".cmd",
    ".conf",
    ".css",
    ".csv",
    ".dockerfile",
    ".fish",
    ".go",
    ".h",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".md",
    ".mdc",
    ".mjs",
    ".mmd",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".scss",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {
    ".dockerignore",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    "dockerfile",
    "license",
    "makefile",
    "procfile",
}
DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".mypy_cache",
    ".ruff_cache",
    "venv",
}
MECHANISMS = {
    "atomic-state": r"(?i)\b(os\.replace|atomic[_ -]?(write|swap|rename)|fsync|write[_ -]?ahead|temp(?:orary)?[_ -]?file)\b",
    "bounded-retry": r"(?i)\b(exponential[_ -]?backoff|retry[_ -]?(budget|policy|after)|max[_ -]?retries|jitter|circuit[_ -]?breaker)\b",
    "contract-introspection": r"(?i)\b(openapi\(\)|metadata\.tables|contract[_ -]?drift|consumer[_ -]?scan|runtime[_ -]?introspect)\b",
    "derived-artifact-sync": r"(?i)\b(source[_ -]?of[_ -]?truth|generated[_ -]?file|regenerate|do not edit|architecture[_ -]?guardrail)\b",
    "dynamic-service-discovery": r"(?i)\b(service[_ -]?discovery|dns[_ -]?resolver|resolver\s+127\.0\.0\.11|re-resolv|stale[_ -]?(address|endpoint|identity))\b",
    "evidence-integrity": r"(?i)\b(sha256|evidence[_ -]?index|proof[_ -]?manifest|source[_ -]?manifest|content[_ -]?hash|claim[_ -]?to[_ -]?evidence)\b",
    "knowledge-integrity": r"(?i)\b(orphan|provenance|cardinality|alias[_ -]?conflict|mapping[_ -]?coverage|shacl|pyshacl)\b",
    "live-contract-validation": r"(?i)\b(docker\s+compose\s+exec|docker\s+exec|inject(?:ed|ion)?[_ -]?script|marker[_ -]?extract|live[_ -]?contract)\b",
    "observability-correlation": r"(?i)\b(correlation[_ -]?id|trace[_ -]?id|prometheus|loki|alertmanager|telemetry[_ -]?correlat|service[_ -]?health[_ -]?matrix)\b",
    "reversible-validation": r"(?i)\b(rollback|restore|snapshot|trap\s+[^\n]{0,300}\bEXIT\b|pre[_ -]?migration|post[_ -]?migration|round[_ -]?trip)\b",
    "security-aggregation": r"(?i)\b(sbom|gitleaks|trufflehog|grype|syft|sast|dast|findings[_ -]?summary|payload[_ -]?strip)\b",
    "state-isolation": r"(?i)\b(advisory[_ -]?lock|file[_ -]?lock|lease[_ -]?(owner|token)|project[_ -]?scope|no[_ -]?new[_ -]?privileges|cap[_ -]?drop|read[_ -]?only[_ -]?filesystem)\b",
    "text-repair": r"(?i)\b(ocr|garbl|token[_ -]?replacement|stutter[_ -]?pattern|normaliz(?:e|ation)[_ -]?dictionary)\b",
    "validation-completeness": r"(?i)\b(pass,?\s*fail,?\s*blocked|skipped,?\s*uncertain|coverage[_ -]?denominator|completion[_ -]?gate|unmapped[_ -]?(path|relationship)|global[_ -]?certification)\b",
    "visual-accessibility": r"(?i)\b(prefers-reduced-motion|requestanimationframe|preservedrawingbuffer|keyboard[_ -]?activation|visual[_ -]?tier)\b",
    "capability-admission": r"(?i)\b(admission[_ -]?gate|promotion[_ -]?requirements?|candidate[_ -]?staged|skill[_ -]?supply[_ -]?chain|provenance.{0,80}licen[cs])\b",
    "dependency-impact": r"(?i)\b(dependency[_ -]?graph|blast[_ -]?radius|downstream[_ -]?(consumer|effect)|transitive[_ -]?depend|change[_ -]?impact)\b",
    "configuration-drift": r"(?i)\b(config(?:uration)?[_ -]?drift|configuration[_ -]?parity|mirrored[_ -]?config|canonical[_ -]?config)\b",
    "resource-performance": r"(?i)\b(performance[_ -]?budget|memory[_ -]?budget|latency[_ -]?budget|resource[_ -]?pressure|load[_ -]?test|slow[_ -]?quer)\b",
    "evaluation-readiness": r"(?i)\b(golden[_ -]?(set|dataset)|evaluation[_ -]?dataset|retrieval[_ -]?quality|precision.{0,40}recall|ndcg|benchmark[_ -]?suite)\b",
    "prompt-memory-security": r"(?i)\b(prompt[_ -]?injection|memory[_ -]?poison|untrusted[_ -]?context|secret[_ -]?retrieval|context[_ -]?firewall)\b",
    "migration-safety": r"(?i)\b(schema[_ -]?migration|expand[_ -]?contract|compatibility[_ -]?window|forward[_ -]?migration|migration[_ -]?plan)\b",
    "failure-triage": r"(?i)\b(root[_ -]?cause|failure[_ -]?triage|stack[_ -]?trace|incident[_ -]?correlat|failure[_ -]?cluster)\b",
    "browser-evidence": r"(?i)\b(playwright|browser[_ -]?(test|audit|certif)|route[_ -]?crawl|screenshot.{0,40}failure|keyboard[_ -]?only)\b",
    "data-readiness": r"(?i)\b(data[_ -]?readiness|fallback[_ -]?classif|synthetic[_ -]?data|empty[_ -]?state|data[_ -]?provenance)\b",
    "retrieval-engineering": r"(?i)\b(hybrid[_ -]?(search|retrieval)|rerank|chunking[_ -]?strateg|embedding[_ -]?(model|optim)|knowledge[_ -]?graph)\b",
    "service-lifecycle": r"(?i)\b(container[_ -]?lifecycle|graceful[_ -]?shutdown|startup[_ -]?probe|readiness[_ -]?probe|health[_ -]?check)\b",
    "tool-lifecycle": r"(?i)\b(mcp[_ -]?server|json-rpc|tools/list|lazy[_ -]?load.{0,40}tool|tool[_ -]?catalog)\b",
    "research-extraction": r"(?i)\b(research[_ -]?to[_ -]?(operation|capability)|academic[_ -]?paper|claim[_ -]?evidence|citation[_ -]?provenance)\b",
    "orchestration-checkpoint": r"(?i)\b(checkpoint|punch[_ -]?card|workflow[_ -]?graph|depends_on|resume[_ -]?token)\b",
}
MECHANISM_NAMES = tuple(MECHANISMS)
COMBINED_MECHANISMS = re.compile(
    "|".join(
        f"(?P<m{index}>{pattern.removeprefix('(?i)')})"
        for index, pattern in enumerate(MECHANISMS.values())
    ),
    re.IGNORECASE,
)
COMPILED_MECHANISMS = {
    name: re.compile(pattern) for name, pattern in MECHANISMS.items()
}
MECHANISM_PREFILTERS = {
    "atomic-state": (
        b"os.replace",
        b"atomic",
        b"fsync",
        b"write-ahead",
        b"write_ahead",
        b"temporary",
        b"temp file",
    ),
    "bounded-retry": (b"backoff", b"retry", b"jitter", b"circuit"),
    "contract-introspection": (
        b"openapi()",
        b"metadata.tables",
        b"contract",
        b"consumer",
        b"introspect",
    ),
    "derived-artifact-sync": (
        b"source of truth",
        b"source_of_truth",
        b"generated",
        b"regenerate",
        b"do not edit",
        b"architecture guardrail",
    ),
    "dynamic-service-discovery": (
        b"service discovery",
        b"service_discovery",
        b"dns",
        b"resolver",
        b"re-resolv",
        b"stale address",
        b"stale endpoint",
        b"stale identity",
    ),
    "evidence-integrity": (
        b"sha256",
        b"evidence",
        b"proof manifest",
        b"source manifest",
        b"content hash",
        b"claim-to-evidence",
        b"claim_to_evidence",
    ),
    "knowledge-integrity": (
        b"orphan",
        b"provenance",
        b"cardinality",
        b"alias",
        b"mapping coverage",
        b"shacl",
    ),
    "live-contract-validation": (
        b"docker exec",
        b"docker compose exec",
        b"inject",
        b"marker",
        b"live contract",
        b"live_contract",
    ),
    "observability-correlation": (
        b"correlation",
        b"trace",
        b"prometheus",
        b"loki",
        b"alertmanager",
        b"telemetry",
        b"service health",
    ),
    "reversible-validation": (
        b"rollback",
        b"restore",
        b"snapshot",
        b"trap",
        b"pre-migration",
        b"pre_migration",
        b"post-migration",
        b"post_migration",
        b"round-trip",
        b"round_trip",
    ),
    "security-aggregation": (
        b"sbom",
        b"gitleaks",
        b"trufflehog",
        b"grype",
        b"syft",
        b"sast",
        b"dast",
        b"findings",
        b"payload strip",
    ),
    "state-isolation": (
        b"advisory lock",
        b"file lock",
        b"lease",
        b"project scope",
        b"no new privileges",
        b"no_new_privileges",
        b"cap drop",
        b"read-only filesystem",
    ),
    "text-repair": (b"ocr", b"garbl", b"token replacement", b"stutter", b"normaliz"),
    "validation-completeness": (
        b"pass",
        b"blocked",
        b"skipped",
        b"uncertain",
        b"denominator",
        b"completion gate",
        b"unmapped",
        b"global certification",
    ),
    "visual-accessibility": (
        b"prefers-reduced-motion",
        b"requestanimationframe",
        b"preservedrawingbuffer",
        b"keyboard activation",
        b"visual tier",
    ),
    "capability-admission": (
        b"admission",
        b"promotion",
        b"candidate staged",
        b"candidate_staged",
        b"skill supply chain",
        b"skill_supply_chain",
        b"provenance",
    ),
    "dependency-impact": (
        b"dependency graph",
        b"dependency_graph",
        b"blast radius",
        b"blast_radius",
        b"downstream",
        b"transitive",
        b"change impact",
    ),
    "configuration-drift": (
        b"config drift",
        b"config_drift",
        b"configuration drift",
        b"configuration parity",
        b"mirrored config",
        b"canonical config",
    ),
    "resource-performance": (
        b"performance budget",
        b"memory budget",
        b"latency budget",
        b"resource pressure",
        b"load test",
        b"slow quer",
    ),
    "evaluation-readiness": (
        b"golden set",
        b"golden dataset",
        b"evaluation dataset",
        b"retrieval quality",
        b"precision",
        b"ndcg",
        b"benchmark suite",
    ),
    "prompt-memory-security": (
        b"prompt injection",
        b"memory poison",
        b"untrusted context",
        b"secret retrieval",
        b"context firewall",
    ),
    "migration-safety": (
        b"schema migration",
        b"expand contract",
        b"compatibility window",
        b"forward migration",
        b"migration plan",
    ),
    "failure-triage": (
        b"root cause",
        b"failure triage",
        b"stack trace",
        b"incident correlat",
        b"failure cluster",
    ),
    "browser-evidence": (
        b"playwright",
        b"browser test",
        b"browser audit",
        b"browser certif",
        b"route crawl",
        b"screenshot",
        b"keyboard-only",
    ),
    "data-readiness": (
        b"data readiness",
        b"fallback classif",
        b"synthetic data",
        b"empty state",
        b"data provenance",
    ),
    "retrieval-engineering": (
        b"hybrid search",
        b"hybrid retrieval",
        b"rerank",
        b"chunking",
        b"embedding model",
        b"embedding optim",
        b"knowledge graph",
    ),
    "service-lifecycle": (
        b"container lifecycle",
        b"graceful shutdown",
        b"startup probe",
        b"readiness probe",
        b"health check",
    ),
    "tool-lifecycle": (
        b"mcp server",
        b"json-rpc",
        b"tools/list",
        b"lazy load",
        b"tool catalog",
    ),
    "research-extraction": (
        b"research to operation",
        b"research-to-operation",
        b"research to capability",
        b"research-to-capability",
        b"academic paper",
        b"claim evidence",
        b"citation provenance",
    ),
    "orchestration-checkpoint": (
        b"checkpoint",
        b"punch card",
        b"workflow graph",
        b"depends_on",
        b"resume token",
    ),
}
SKILL_NAME = re.compile(r"(?m)^name:\s*[\"']?([^\n\"']+)")
SKILL_DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?([^\n]+)")
STREAM_CHUNK_BYTES = 1024 * 1024
MAX_EXCLUDED_BOUNDARY_ENTRIES = 1_000_000
TEXT_OVERLAP_CHARACTERS = 1024
METADATA_PREFIX_BYTES = 12000


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _tokens(value: str) -> set[str]:
    return {item for item in _slug(value).split("-") if len(item) > 2}


def _excluded(relative: Path, excluded: set[str]) -> str | None:
    for part in relative.parts[:-1]:
        lowered = part.casefold()
        if lowered in excluded or lowered.startswith(".venv"):
            return part
    return None


def _is_text(path: Path) -> bool:
    return (
        path.suffix.casefold() in TEXT_EXTENSIONS
        or path.name.casefold() in TEXT_FILENAMES
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(STREAM_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_text(path: Path) -> tuple[str, str, Counter[str]]:
    """Hash and line-scan text without loading oversized files or regexing irrelevant lines."""
    digest = hashlib.sha256()
    prefix = bytearray()
    hit_counts: Counter[str] = Counter()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            if len(prefix) < METADATA_PREFIX_BYTES:
                prefix.extend(line[: METADATA_PREFIX_BYTES - len(prefix)])
            lowered = line.lower()
            decoded: str | None = None
            for name, triggers in MECHANISM_PREFILTERS.items():
                if not any(trigger in lowered for trigger in triggers):
                    continue
                if decoded is None:
                    decoded = line.decode("utf-8", errors="replace")
                hit_counts[name] += sum(
                    1 for _ in COMPILED_MECHANISMS[name].finditer(decoded)
                )
    return (
        digest.hexdigest(),
        bytes(prefix).decode("utf-8", errors="replace"),
        hit_counts,
    )


def _inventory_excluded_boundary(
    boundary: Path,
    source: Path,
    *,
    max_entries: int = MAX_EXCLUDED_BOUNDARY_ENTRIES,
) -> tuple[list[tuple[str, int]], list[str], list[str]]:
    """Inventory an excluded tree from directory metadata only.

    Exclusion is an I/O boundary, not merely a classification label.  Exact
    regular-file and byte denominators are retained without opening excluded
    file bodies.  Any entry that cannot be classified safely makes the audit
    incomplete instead of silently disappearing from the denominator.
    """
    if max_entries < 1:
        raise ValueError("max_entries must be positive")
    records: list[tuple[str, int]] = []
    errors: list[str] = []
    visited_entries = 0

    try:
        boundary_mode = os.stat(boundary, follow_symlinks=False).st_mode
    except OSError as error:
        return records, [], [f"{boundary}: {type(error).__name__}: {error}"]
    if stat.S_ISLNK(boundary_mode):
        return records, [], [f"{boundary}: excluded boundary is a symlink"]
    if not stat.S_ISDIR(boundary_mode):
        return records, [], [f"{boundary}: excluded boundary is not a directory"]

    symlinks: list[str] = []
    bounded = False
    pending = [boundary]
    while pending:
        current_path = pending.pop()
        try:
            with os.scandir(current_path) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as error:
            errors.append(
                f"{error.filename or current_path}: {type(error).__name__}: {error}"
            )
            continue
        child_directories: list[Path] = []
        for entry in entries:
            visited_entries += 1
            if visited_entries > max_entries:
                bounded = True
                break
            path = current_path / entry.name
            try:
                if entry.is_symlink():
                    symlinks.append(path.relative_to(source).as_posix())
                elif entry.is_dir(follow_symlinks=False):
                    child_directories.append(path)
                elif entry.is_file(follow_symlinks=False):
                    metadata = entry.stat(follow_symlinks=False)
                    records.append(
                        (path.relative_to(source).as_posix(), metadata.st_size)
                    )
                else:
                    errors.append(f"{path}: non-regular entry inside excluded boundary")
            except OSError as error:
                errors.append(f"{path}: {type(error).__name__}: {error}")
        if bounded:
            break
        pending.extend(reversed(child_directories))
    if bounded:
        errors.append(
            f"{boundary}: excluded boundary entry limit exceeded ({max_entries})"
        )
    records.sort(key=lambda item: item[0].casefold())
    symlinks.sort(key=str.casefold)
    return records, symlinks, errors


def _update_inventory_hash(
    digest: "hashlib._Hash",
    relative: str,
    size: int,
    content_sha256: str | None,
    *,
    entry_kind: str = "regular-file",
) -> None:
    encoded_path = relative.encode("utf-8", errors="replace")
    method = (
        b"content-sha256"
        if content_sha256 is not None
        else f"path-size-metadata:{entry_kind}".encode("ascii")
    )
    digest.update(len(encoded_path).to_bytes(8, "big"))
    digest.update(encoded_path)
    digest.update(size.to_bytes(16, "big", signed=False))
    digest.update(len(method).to_bytes(2, "big"))
    digest.update(method)
    if content_sha256 is not None:
        digest.update(bytes.fromhex(content_sha256))


def _catalog(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "id": str(item["id"]),
            "status": str(item.get("status", "candidate")),
            "tokens": _tokens(
                " ".join((str(item["id"]), *map(str, item.get("tags", ()))))
            ),
        }
        for item in data.get("skills", ())
    ]


def _matches(
    name: str, description: str, catalog: list[dict[str, object]]
) -> list[dict[str, object]]:
    candidate = _tokens(f"{name} {description}")
    ranked: list[dict[str, object]] = []
    for item in catalog:
        existing = set(item["tokens"])
        union = candidate | existing
        similarity = len(candidate & existing) / len(union) if union else 0.0
        if similarity:
            ranked.append(
                {
                    "id": item["id"],
                    "status": item["status"],
                    "similarity": round(similarity, 4),
                }
            )
    return sorted(
        ranked, key=lambda item: (-float(item["similarity"]), str(item["id"]))
    )[:5]


def audit(
    root: Path,
    *,
    existing_catalog: Path | None = None,
    excluded_names: Iterable[str] = (),
    max_bytes: int = 2_000_000,
) -> dict[str, object]:
    source = root.resolve()
    if not source.is_dir() or source == Path(source.anchor):
        raise ValueError("root must be an explicit non-filesystem-root directory")
    catalog = _catalog(existing_catalog)
    excluded = {item.casefold() for item in DEFAULT_EXCLUDES | set(excluded_names)}
    extension_counts: Counter[str] = Counter()
    excluded_counts: Counter[str] = Counter()
    mechanism_counts: Counter[str] = Counter()
    duplicate_hashes: defaultdict[str, list[str]] = defaultdict(list)
    records: list[dict[str, object]] = []
    errors: list[str] = []
    totals = Counter()
    inventory_hash = hashlib.sha256()

    excluded_boundaries: list[dict[str, object]] = []
    inventory_records: list[tuple[str, int, str | None, str]] = []
    paths: list[Path] = []
    for current, directories, filenames in os.walk(
        source, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(directories, key=str.casefold):
            candidate = current_path / name
            relative = candidate.relative_to(source)
            lowered = name.casefold()
            if (
                lowered in excluded
                or lowered.startswith(".venv")
                or lowered.endswith("-venv")
            ):
                excluded_counts[name] += 1
                totals["excluded_directories"] += 1
                (
                    boundary_records,
                    boundary_symlinks,
                    boundary_errors,
                ) = _inventory_excluded_boundary(candidate, source)
                inventory_records.extend(
                    (item_path, item_bytes, None, "regular-file")
                    for item_path, item_bytes in boundary_records
                )
                inventory_records.extend(
                    (item_path, 0, None, "unfollowed-symlink")
                    for item_path in boundary_symlinks
                )
                errors.extend(boundary_errors)
                boundary_hash = hashlib.sha256()
                for item_path, item_bytes in boundary_records:
                    _update_inventory_hash(
                        boundary_hash, item_path, item_bytes, None
                    )
                for item_path in boundary_symlinks:
                    _update_inventory_hash(
                        boundary_hash,
                        item_path,
                        0,
                        None,
                        entry_kind="unfollowed-symlink",
                    )
                totals["excluded_files"] += len(boundary_records)
                totals["excluded_bytes"] += sum(item[1] for item in boundary_records)
                totals["excluded_symlinks"] += len(boundary_symlinks)
                excluded_boundaries.append(
                    {
                        "path": relative.as_posix(),
                        "reason": name,
                        "file_count": len(boundary_records),
                        "byte_count": sum(item[1] for item in boundary_records),
                        "symlink_count": len(boundary_symlinks),
                        "inventory_method": "path-and-size-metadata",
                        "metadata_inventory_sha256": boundary_hash.hexdigest(),
                    }
                )
            elif candidate.is_symlink():
                totals["symlink_skipped"] += 1
                excluded_boundaries.append(
                    {"path": relative.as_posix(), "reason": "symlink"}
                )
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(filenames, key=str.casefold):
            path = current_path / name
            if name.startswith(".") and name.casefold().endswith(".lock"):
                try:
                    metadata = os.stat(path, follow_symlinks=False)
                    relative = path.relative_to(source).as_posix()
                    if stat.S_ISLNK(metadata.st_mode):
                        totals["symlink_skipped"] += 1
                        excluded_boundaries.append(
                            {"path": relative, "reason": "symlink"}
                        )
                    elif stat.S_ISREG(metadata.st_mode):
                        inventory_records.append(
                            (relative, metadata.st_size, None, "volatile-dot-lock")
                        )
                        totals["excluded_files"] += 1
                        totals["excluded_bytes"] += metadata.st_size
                        totals["excluded_volatile_locks"] += 1
                        volatile_hash = hashlib.sha256()
                        _update_inventory_hash(
                            volatile_hash,
                            relative,
                            metadata.st_size,
                            None,
                            entry_kind="volatile-dot-lock",
                        )
                        excluded_boundaries.append(
                            {
                                "path": relative,
                                "reason": "volatile-dot-lock",
                                "file_count": 1,
                                "byte_count": metadata.st_size,
                                "symlink_count": 0,
                                "inventory_method": "path-and-size-metadata",
                                "metadata_inventory_sha256": volatile_hash.hexdigest(),
                            }
                        )
                    else:
                        errors.append(f"{path}: non-regular hidden lock entry")
                except OSError as error:
                    errors.append(f"{path}: {type(error).__name__}: {error}")
                continue
            paths.append(path)

    for path in sorted(paths, key=lambda item: item.as_posix().casefold()):
        try:
            if not path.is_file() or path.is_symlink():
                if path.is_symlink():
                    totals["symlink_skipped"] += 1
                continue
            relative = path.relative_to(source)
            totals["files"] += 1
            size = path.stat().st_size
            totals["bytes"] += size
            extension_counts[path.suffix.casefold() or "<none>"] += 1
            if not _is_text(path):
                totals["non_text"] += 1
                digest = _hash_file(path)
                inventory_records.append(
                    (relative.as_posix(), size, digest, "regular-file")
                )
                continue
            oversized = size > max_bytes
            if oversized:
                totals["oversize"] += 1
                totals["oversize_stream_scanned"] += 1
            digest, metadata_prefix, hit_counts = _scan_text(path)
            inventory_records.append(
                (relative.as_posix(), size, digest, "regular-file")
            )
            hits = dict(sorted(hit_counts.items()))
            mechanism_counts.update(hits)
            skill_like = (
                path.name.casefold() == "skill.md" or "skill" in path.stem.casefold()
            )
            name_match = SKILL_NAME.search(metadata_prefix) if skill_like else None
            description_match = (
                SKILL_DESCRIPTION.search(metadata_prefix) if skill_like else None
            )
            skill = None
            if name_match:
                name = _slug(name_match.group(1).strip())
                description = (
                    description_match.group(1).strip().strip("\"'")
                    if description_match
                    else ""
                )
                skill = {
                    "name": name,
                    "description": description,
                    "catalog_matches": _matches(name, description, catalog),
                }
            filename_signal = bool(
                re.search(
                    r"(?i)(audit|certif|contract|discover|drift|evidence|guard|health|harden|migrat|orchestrat|provenance|recover|repair|restore|rollback|sanit|sync|validat)",
                    path.name,
                )
            )
            score = len(hits) * 2 + (4 if skill else 0) + (1 if filename_signal else 0)
            disposition = (
                "oversize_review_required"
                if oversized
                else ("review_required" if score >= 3 else "no_reusable_signal")
            )
            if score or skill or oversized:
                record = {
                    "path": relative.as_posix(),
                    "bytes": size,
                    "sha256": digest,
                    "mechanisms": hits,
                    "score": score,
                    "disposition": disposition,
                }
                if skill:
                    record["skill"] = skill
                records.append(record)
                duplicate_hashes[digest].append(relative.as_posix())
            totals["text_scanned"] += 1
        except (OSError, UnicodeError) as error:
            errors.append(f"{path}: {type(error).__name__}: {error}")

    for relative, size, digest, entry_kind in sorted(
        inventory_records, key=lambda item: item[0].casefold()
    ):
        _update_inventory_hash(
            inventory_hash,
            relative,
            size,
            digest,
            entry_kind=entry_kind,
        )
    totals["total_accounted_files"] = totals["files"] + totals["excluded_files"]
    totals["total_accounted_bytes"] = totals["bytes"] + totals["excluded_bytes"]

    duplicate_groups = [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(duplicate_hashes.items())
        if len(paths) > 1
    ]
    review = sum(
        item.get("disposition") in {"review_required", "oversize_review_required"}
        for item in records
    )
    return {
        "schema_version": "1.1",
        "scanner": "audit-source-capabilities/1.3.1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": source.as_posix(),
        "configuration": {"max_bytes": max_bytes, "excluded_names": sorted(excluded)},
        "coverage": {
            **dict(sorted(totals.items())),
            "extension_counts": dict(sorted(extension_counts.items())),
            "excluded_counts": dict(sorted(excluded_counts.items())),
            "inventory_sha256": inventory_hash.hexdigest(),
            "inventory_scope": "all regular files; content SHA-256 for included source and path/size metadata for explicitly excluded boundaries",
            "excluded_inventory_method": "path-and-size-metadata-no-body-read",
            "excluded_boundary_entry_limit": MAX_EXCLUDED_BOUNDARY_ENTRIES,
            "error_count": len(errors),
        },
        "mechanism_counts": dict(sorted(mechanism_counts.items())),
        "candidate_count": review,
        "records": records,
        "duplicate_candidate_groups": duplicate_groups,
        "excluded_boundaries": excluded_boundaries,
        "errors": errors,
        "complete": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing-catalog", type=Path)
    parser.add_argument("--exclude-name", action="append", default=[])
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--allow-errors", action="store_true")
    args = parser.parse_args()
    result = audit(
        args.root,
        existing_catalog=args.existing_catalog,
        excluded_names=args.exclude_name,
        max_bytes=args.max_bytes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "files": result["coverage"].get("files", 0),
                "text_scanned": result["coverage"].get("text_scanned", 0),
                "excluded": result["coverage"].get("excluded", 0),
                "candidate_count": result["candidate_count"],
                "error_count": result["coverage"]["error_count"],
                "output": str(args.output.resolve()),
            },
            indent=2,
        )
    )
    return 0 if result["complete"] or args.allow_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
