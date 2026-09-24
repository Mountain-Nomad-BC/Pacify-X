"""Stable read-only parity findings for derived operational projections."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ParityFinding:
    finding_id: str
    kind: str
    severity: str
    left_id: str | None
    right_id: str | None
    detail: str
    authority_granted: bool = False


def stable_finding_id(kind: str, *parts: Any) -> str:
    if type(kind) is not str or not kind or len(kind.encode()) > 128:
        raise ValueError("finding kind must be bounded text")
    return f"{kind}:{_sha([kind, *parts])[:20]}"


def compare_identifier_sets(left: Iterable[str], right: Iterable[str], *, left_name: str, right_name: str) -> tuple[ParityFinding, ...]:
    l = {str(item) for item in left}; r = {str(item) for item in right}
    findings: list[ParityFinding] = []
    for missing in sorted(l - r):
        findings.append(ParityFinding(stable_finding_id("missing_right", left_name, right_name, missing), "missing_right", "high", missing, None, f"{missing!r} exists in {left_name} but not {right_name}"))
    for extra in sorted(r - l):
        findings.append(ParityFinding(stable_finding_id("missing_left", left_name, right_name, extra), "missing_left", "medium", None, extra, f"{extra!r} exists in {right_name} but not {left_name}"))
    return tuple(findings)


def find_dead_references(nodes: Iterable[str], edges: Iterable[tuple[str, str, str]]) -> tuple[ParityFinding, ...]:
    known = {str(node) for node in nodes}
    findings: list[ParityFinding] = []
    for edge in edges:
        if type(edge) is not tuple or len(edge) != 3:
            raise ValueError("edge must be a source/relation/target tuple")
        src, relation, dst = map(str, edge)
        if src not in known:
            findings.append(ParityFinding(stable_finding_id("dead_source", src, relation, dst), "dead_source", "high", src, dst, f"missing source node for {relation}"))
        if dst not in known:
            findings.append(ParityFinding(stable_finding_id("dead_target", src, relation, dst), "dead_target", "high", src, dst, f"missing target node for {relation}"))
    return tuple(sorted(findings, key=lambda row: row.finding_id))


def compare_projection_revisions(authority_revisions: Mapping[str, str], projected_revisions: Mapping[str, str]) -> tuple[ParityFinding, ...]:
    findings = list(compare_identifier_sets(authority_revisions, projected_revisions, left_name="authority", right_name="projection"))
    for identifier in sorted(set(authority_revisions) & set(projected_revisions)):
        left = str(authority_revisions[identifier]); right = str(projected_revisions[identifier])
        if left != right:
            findings.append(ParityFinding(stable_finding_id("stale_projection", identifier, left, right), "stale_projection", "high", identifier, identifier, f"projection revision {right!r} does not match authority revision {left!r}"))
    return tuple(sorted(findings, key=lambda row: row.finding_id))


def parity_summary(findings: Iterable[ParityFinding]) -> dict[str, Any]:
    rows = tuple(findings)
    if any(type(row) is not ParityFinding for row in rows):
        raise ValueError("parity_summary requires ParityFinding records")
    ordered = sorted(rows, key=lambda row: row.finding_id)
    return {
        "valid": not any(row.severity == "high" for row in ordered),
        "finding_count": len(ordered),
        "finding_ids": [row.finding_id for row in ordered],
        "summary_sha256": _sha([row.__dict__ if hasattr(row, "__dict__") else [row.finding_id, row.kind, row.severity, row.left_id, row.right_id, row.detail] for row in ordered]),
        "authority_granted": False,
    }
