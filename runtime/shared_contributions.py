"""Immutable shared-learning contribution and verification lineage.

This module is storage-neutral and authority-neutral.  Contribution records point
at existing PX memory/evidence identities; they are not a second memory store and
never grant publication, promotion, or execution authority.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

CONTRIBUTION_SCHEMA = "px.shared-contribution/1.0"
VERIFICATION_SCHEMA = "px.verification-record/1.0"
CONTRIBUTION_TYPES = frozenset({"setup", "result", "insight", "hypothesis", "report", "negative_result", "correction", "wip"})
CONTRIBUTION_CLASSES = frozenset({"light", "heavy"})
VISIBILITY_STATES = frozenset({"private", "project", "team", "public-candidate"})
PUBLICATION_STATES = frozenset({"unpublished", "review-candidate", "approved", "published", "rejected", "revoked"})
VERDICTS = frozenset({"confirmed", "partial", "failed", "inconclusive"})
_SHA = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 value")
    return value


def _text(value: object, label: str, maximum: int = 4096) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} must be non-empty bounded text")
    return text


def _timestamp(value: str | None) -> str:
    text = value or datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("contribution timestamp must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("contribution timestamp must include timezone")
    return text


def make_contribution(
    *,
    project_id: str,
    publisher_id: str,
    contribution_type: str,
    description: str,
    contribution_class: str = "light",
    parent_sha256: Sequence[str] = (),
    memory_refs: Sequence[str] = (),
    evidence_sha256: Sequence[str] = (),
    tags: Sequence[str] = (),
    visibility: str = "project",
    publication_state: str = "unpublished",
    metadata: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    project = _text(project_id, "project_id", 256)
    publisher = _text(publisher_id, "publisher_id", 256)
    description = _text(description, "description", 8192)
    if contribution_type not in CONTRIBUTION_TYPES:
        raise ValueError("unknown contribution type")
    if contribution_class not in CONTRIBUTION_CLASSES:
        raise ValueError("unknown contribution class")
    if visibility not in VISIBILITY_STATES or publication_state not in PUBLICATION_STATES:
        raise ValueError("invalid contribution visibility/publication state")
    parents = tuple(sorted(set(_sha(item, "parent contribution") for item in parent_sha256)))
    evidence = tuple(sorted(set(_sha(item, "contribution evidence") for item in evidence_sha256)))
    memories = tuple(sorted(set(_text(item, "memory reference", 512) for item in memory_refs)))
    if contribution_type in {"result", "negative_result", "correction"} and not evidence:
        raise ValueError("measured/corrective contributions require evidence")
    if contribution_type == "hypothesis" and publication_state == "published":
        raise ValueError("untested hypothesis cannot be published as a result")
    if publication_state == "published" and visibility != "public-candidate":
        raise ValueError("published contribution must have public-candidate visibility")
    body = {
        "schema_version": CONTRIBUTION_SCHEMA,
        "project_id": project,
        "publisher_id": publisher,
        "contribution_type": contribution_type,
        "contribution_class": contribution_class,
        "description": description,
        "parent_sha256": list(parents),
        "memory_refs": list(memories),
        "evidence_sha256": list(evidence),
        "tags": sorted(set(_text(item, "tag", 128) for item in tags)),
        "visibility": visibility,
        "publication_state": publication_state,
        "metadata": dict(metadata or {}),
        "created_at": _timestamp(created_at),
        "authority_granted": False,
    }
    return {**body, "record_sha256": content_hash(body)}


def validate_contribution(record: Mapping[str, Any]) -> None:
    if record.get("schema_version") != CONTRIBUTION_SCHEMA:
        raise ValueError("contribution schema mismatch")
    body = {str(k): v for k, v in record.items() if k != "record_sha256"}
    if _sha(record.get("record_sha256"), "contribution record") != content_hash(body):
        raise ValueError("contribution hash mismatch")
    if record.get("authority_granted") is not False:
        raise ValueError("contribution cannot grant authority")
    rebuilt = make_contribution(
        project_id=str(record.get("project_id", "")), publisher_id=str(record.get("publisher_id", "")),
        contribution_type=str(record.get("contribution_type", "")), description=str(record.get("description", "")),
        contribution_class=str(record.get("contribution_class", "")), parent_sha256=list(record.get("parent_sha256") or ()),
        memory_refs=list(record.get("memory_refs") or ()), evidence_sha256=list(record.get("evidence_sha256") or ()),
        tags=list(record.get("tags") or ()), visibility=str(record.get("visibility", "")),
        publication_state=str(record.get("publication_state", "")), metadata=dict(record.get("metadata") or {}),
        created_at=str(record.get("created_at", "")),
    )
    if dict(record) != rebuilt:
        raise ValueError("contribution semantic identity mismatch")


def make_verification_record(
    *, target_sha256: str, verifier_id: str, evaluator_sha256: str, reproduction_sha256: str,
    verdict: str, evidence_sha256: Sequence[str], verified_at: str | None = None,
) -> dict[str, Any]:
    target = _sha(target_sha256, "verification target")
    evaluator = _sha(evaluator_sha256, "evaluator")
    reproduction = _sha(reproduction_sha256, "reproduction")
    verifier = _text(verifier_id, "verifier_id", 256)
    if verdict not in VERDICTS:
        raise ValueError("verification verdict is invalid")
    evidence = tuple(sorted(set(_sha(item, "verification evidence") for item in evidence_sha256)))
    if not evidence:
        raise ValueError("verification requires independent evidence")
    body = {
        "schema_version": VERIFICATION_SCHEMA,
        "target_sha256": target,
        "verifier_id": verifier,
        "evaluator_sha256": evaluator,
        "reproduction_sha256": reproduction,
        "verdict": verdict,
        "evidence_sha256": list(evidence),
        "verified_at": _timestamp(verified_at),
        "authority_granted": False,
    }
    return {**body, "record_sha256": content_hash(body)}


def validate_verification(record: Mapping[str, Any]) -> None:
    if record.get("schema_version") != VERIFICATION_SCHEMA:
        raise ValueError("verification schema mismatch")
    body = {str(k): v for k, v in record.items() if k != "record_sha256"}
    if _sha(record.get("record_sha256"), "verification record") != content_hash(body):
        raise ValueError("verification hash mismatch")
    if record.get("authority_granted") is not False:
        raise ValueError("verification cannot grant authority")
    rebuilt = make_verification_record(
        target_sha256=str(record.get("target_sha256", "")), verifier_id=str(record.get("verifier_id", "")),
        evaluator_sha256=str(record.get("evaluator_sha256", "")), reproduction_sha256=str(record.get("reproduction_sha256", "")),
        verdict=str(record.get("verdict", "")), evidence_sha256=list(record.get("evidence_sha256") or ()),
        verified_at=str(record.get("verified_at", "")),
    )
    if dict(record) != rebuilt:
        raise ValueError("verification semantic identity mismatch")


class ContributionGraph:
    def __init__(self, records: Iterable[Mapping[str, Any]]) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.children: dict[str, set[str]] = defaultdict(set)
        for raw in records:
            validate_contribution(raw)
            row = dict(raw)
            digest = str(row["record_sha256"])
            if digest in self.records and self.records[digest] != row:
                raise ValueError("contribution identity collision")
            self.records[digest] = row
        for digest, row in self.records.items():
            for parent in row["parent_sha256"]:
                if parent not in self.records:
                    raise ValueError(f"missing contribution parent: {parent}")
                if self.records[parent]["project_id"] != row["project_id"]:
                    raise ValueError("cross-project contribution lineage is forbidden")
                self.children[parent].add(digest)
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set(); visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting: raise ValueError("contribution graph contains a cycle")
            if node in visited: return
            visiting.add(node)
            for child in sorted(self.children.get(node, ())): visit(child)
            visiting.remove(node); visited.add(node)
        for node in sorted(self.records): visit(node)

    def negative_results(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.records.items() if v["contribution_type"] == "negative_result"))


def verification_summary(contribution: Mapping[str, Any], verifications: Iterable[Mapping[str, Any]], *, minimum_confirmations: int = 1) -> dict[str, Any]:
    validate_contribution(contribution)
    if type(minimum_confirmations) is not int or isinstance(minimum_confirmations, bool) or minimum_confirmations < 1:
        raise ValueError("minimum confirmations must be a positive integer")
    target = str(contribution["record_sha256"]); publisher = str(contribution["publisher_id"])
    latest: dict[str, Mapping[str, Any]] = {}
    for row in verifications:
        validate_verification(row)
        if row["target_sha256"] != target: continue
        verifier = str(row["verifier_id"])
        previous = latest.get(verifier)
        row_time = datetime.fromisoformat(str(row["verified_at"]).replace("Z", "+00:00"))
        if previous is None:
            latest[verifier] = row
        else:
            previous_time = datetime.fromisoformat(str(previous["verified_at"]).replace("Z", "+00:00"))
            if row_time > previous_time:
                latest[verifier] = row
            elif row_time == previous_time and row["record_sha256"] != previous["record_sha256"]:
                raise ValueError("ambiguous verification records share verifier and timestamp")
    independent = [row for verifier, row in latest.items() if verifier != publisher]
    counts = {name: sum(1 for row in independent if row["verdict"] == name) for name in VERDICTS}
    passed = counts["confirmed"] >= minimum_confirmations and counts["failed"] == 0
    return {
        "schema_version": "px.shared-contribution-verification-summary/1.0", "target_sha256": target,
        "independent_verifier_count": len(independent), "self_verifier_count": len(latest) - len(independent),
        "verdict_counts": dict(sorted(counts.items())), "minimum_confirmations": minimum_confirmations,
        "passed": passed, "negative_result_retained": contribution["contribution_type"] == "negative_result",
        "verification_sha256": sorted(str(row["record_sha256"]) for row in independent), "authority_granted": False,
    }
